#!/usr/bin/env python3
"""Run a deterministic Blender 4.4 drape comparison for the measured library."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from image2outfit.material import load_material_library  # noqa: E402
from image2outfit.material_blender import (  # noqa: E402
    BlenderMaterialProjection,
    load_blender_calibration_profile,
    project_material_library_to_blender,
)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--library",
        type=Path,
        default=Path("config/materials/kes-woven-fabrics-2025.v1.json"),
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path("config/materials/blender-4.4-kes-calibration.v1.json"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path(".image2outfit/material-calibration")
    )
    parser.add_argument("--frame-end", type=int, default=80)
    parser.add_argument("--grid", type=int, default=25)
    return parser.parse_args(argv)


def blender_arguments() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def clean_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in tuple(bpy.data.collections):
        if collection.name != "Collection":
            bpy.data.collections.remove(collection)


def grid_mesh(name: str, size: float, count: int) -> bpy.types.Mesh:
    if count < 5:
        raise ValueError("grid must contain at least five vertices per axis")
    half = size / 2
    step = size / (count - 1)
    vertices = [
        (-half + column * step, -half + row * step, 0.0)
        for row in range(count)
        for column in range(count)
    ]
    faces: list[tuple[int, int, int, int]] = []
    for row in range(count - 1):
        for column in range(count - 1):
            first = row * count + column
            faces.append((first, first + 1, first + count + 1, first + count))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    return mesh


def create_material(name: str, index: int, total: int) -> bpy.types.Material:
    hue = index / max(total, 1)
    red = 0.35 + 0.45 * abs(math.sin(hue * math.tau))
    green = 0.35 + 0.45 * abs(math.sin((hue + 1 / 3) * math.tau))
    blue = 0.35 + 0.45 * abs(math.sin((hue + 2 / 3) * math.tau))
    material = bpy.data.materials.new(name)
    material.diffuse_color = (red, green, blue, 1.0)
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    if principled is not None:
        principled.inputs["Base Color"].default_value = (red, green, blue, 1.0)
        principled.inputs["Roughness"].default_value = 0.72
    return material


def set_properties(owner: Any, values: dict[str, Any], label: str) -> dict[str, Any]:
    actual: dict[str, Any] = {}
    for name, value in values.items():
        if not hasattr(owner, name):
            raise RuntimeError(f"Blender 4.4 property missing: {label}.{name}")
        setattr(owner, name, value)
        stored = getattr(owner, name)
        actual[name] = (
            bool(stored)
            if isinstance(value, bool)
            else int(stored)
            if isinstance(value, int)
            else float(stored)
        )
    return actual


def create_collider(
    projection: BlenderMaterialProjection,
    location_x: float,
    collection: bpy.types.Collection,
) -> tuple[bpy.types.Object, dict[str, Any]]:
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=48,
        ring_count=24,
        radius=0.48,
        location=(location_x, 0.0, 0.48),
    )
    collider = bpy.context.object
    collider.name = f"Collider__{projection.material_id}"
    for source in tuple(collider.users_collection):
        source.objects.unlink(collider)
    collection.objects.link(collider)
    collider.modifiers.new(name="Collision", type="COLLISION")
    if collider.collision is None:
        raise RuntimeError("Collision modifier did not expose Object.collision")
    actual = set_properties(
        collider.collision,
        dict(projection.collider_settings),
        f"{collider.name}.collision",
    )
    material = bpy.data.materials.new(f"ColliderMaterial__{projection.material_id}")
    material.diffuse_color = (0.12, 0.12, 0.14, 1.0)
    material.metallic = 0.0
    material.roughness = 0.5
    collider.data.materials.append(material)
    return collider, actual


def create_cloth(
    projection: BlenderMaterialProjection,
    location_x: float,
    collection: bpy.types.Collection,
    grid_count: int,
    frame_end: int,
    index: int,
    total: int,
) -> tuple[bpy.types.Object, dict[str, Any]]:
    size = 1.65
    mesh = grid_mesh(f"Mesh__{projection.material_id}", size, grid_count)
    cloth = bpy.data.objects.new(f"Cloth__{projection.material_id}", mesh)
    cloth.location = (location_x, 0.0, 1.22)
    collection.objects.link(cloth)
    cloth.data.materials.append(create_material(cloth.name, index, total))

    cloth_modifier = cloth.modifiers.new(name="Cloth", type="CLOTH")
    surface_area = size * size
    vertex_mass = projection.vertex_mass_kg(surface_area, len(mesh.vertices))
    cloth_values = dict(projection.cloth_settings)
    cloth_values["mass"] = vertex_mass
    actual_cloth = set_properties(
        cloth_modifier.settings, cloth_values, f"{cloth.name}.settings"
    )
    actual_collision = set_properties(
        cloth_modifier.collision_settings,
        dict(projection.cloth_collision_settings),
        f"{cloth.name}.collision_settings",
    )
    cloth_modifier.point_cache.frame_start = 1
    cloth_modifier.point_cache.frame_end = frame_end

    solidify = cloth.modifiers.new(name="RenderThickness", type="SOLIDIFY")
    solidify.thickness = projection.render_settings["solidify_thickness"]
    solidify.offset = 0.0

    return cloth, {
        "surfaceAreaM2": surface_area,
        "vertexCount": len(mesh.vertices),
        "vertexMassKg": vertex_mass,
        "clothSettings": actual_cloth,
        "clothCollisionSettings": actual_collision,
        "solidifyThicknessM": float(solidify.thickness),
    }


def look_at(camera: bpy.types.Object, target: Vector) -> None:
    direction = target - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def configure_render(scene: bpy.types.Scene, output: Path) -> bpy.types.Object:
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 1440
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.render.filepath = str(output / "comparison.png")
    scene.render.use_file_extension = True
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.world.color = (0.035, 0.04, 0.055)

    bpy.ops.object.camera_add(location=(0.0, -13.5, 7.2))
    camera = bpy.context.object
    camera.name = "CalibrationCamera"
    camera.data.lens = 52
    look_at(camera, Vector((0.0, 0.0, 0.48)))
    scene.camera = camera

    bpy.ops.object.light_add(type="AREA", location=(0.0, -1.5, 9.0))
    key = bpy.context.object
    key.name = "KeyLight"
    key.data.energy = 1500
    key.data.shape = "RECTANGLE"
    key.data.size = 8.0
    key.data.size_y = 4.0
    look_at(key, Vector((0.0, 0.0, 0.5)))

    bpy.ops.object.light_add(type="AREA", location=(0.0, 5.0, 4.0))
    fill = bpy.context.object
    fill.name = "FillLight"
    fill.data.energy = 900
    fill.data.size = 7.0
    look_at(fill, Vector((0.0, 0.0, 0.5)))
    return camera


def convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    ordered = sorted(set(points))
    if len(ordered) <= 1:
        return ordered

    def cross(
        origin: tuple[float, float],
        first: tuple[float, float],
        second: tuple[float, float],
    ) -> float:
        return (first[0] - origin[0]) * (second[1] - origin[1]) - (
            first[1] - origin[1]
        ) * (second[0] - origin[0])

    lower: list[tuple[float, float]] = []
    for point in ordered:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(ordered):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def polygon_area(points: list[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    return abs(
        sum(
            first[0] * second[1] - second[0] * first[1]
            for first, second in zip(points, points[1:] + points[:1], strict=True)
        )
    ) / 2


def object_metrics(
    cloth: bpy.types.Object, initial_area: float
) -> dict[str, float | str]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = cloth.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        coordinates = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()
    xs = [value.x for value in coordinates]
    ys = [value.y for value in coordinates]
    zs = [value.z for value in coordinates]
    local_xy = [(x - cloth.location.x, y - cloth.location.y) for x, y in zip(xs, ys)]
    footprint = polygon_area(convex_hull(local_xy))
    rounded = "\n".join(
        f"{value.x:.6f},{value.y:.6f},{value.z:.6f}" for value in coordinates
    ).encode("utf-8")
    return {
        "minimumZ": min(zs),
        "maximumZ": max(zs),
        "verticalRange": max(zs) - min(zs),
        "meanZ": statistics.fmean(zs),
        "standardDeviationZ": statistics.pstdev(zs),
        "spanX": max(xs) - min(xs),
        "spanY": max(ys) - min(ys),
        "footprintAreaM2": footprint,
        "footprintRatio": footprint / initial_area,
        "vertexSha256": hashlib.sha256(rounded).hexdigest(),
    }


def maximum_signature_distance(records: list[dict[str, Any]]) -> float:
    fields = ("verticalRange", "standardDeviationZ", "footprintRatio")
    ranges: dict[str, float] = {}
    for field in fields:
        values = [float(item["metrics"][field]) for item in records]
        ranges[field] = max(values) - min(values)
    maximum = 0.0
    for index, first in enumerate(records):
        for second in records[index + 1 :]:
            distance = math.sqrt(
                sum(
                    (
                        (
                            float(first["metrics"][field])
                            - float(second["metrics"][field])
                        )
                        / ranges[field]
                        if ranges[field] > 0
                        else 0.0
                    )
                    ** 2
                    for field in fields
                )
            )
            maximum = max(maximum, distance)
    return maximum


def render_scene(
    scene: bpy.types.Scene,
    camera: bpy.types.Object,
    output: Path,
    records: list[dict[str, Any]],
) -> list[dict[str, str]]:
    images: list[dict[str, str]] = []
    all_test_objects = [
        obj
        for obj in bpy.data.objects
        if obj.name.startswith(("Cloth__", "Collider__"))
    ]
    combined = output / "comparison.png"
    scene.render.resolution_x = 1440
    scene.render.resolution_y = 720
    scene.render.filepath = str(combined)
    for obj in all_test_objects:
        obj.hide_render = False
    camera.location = (0.0, -13.5, 7.2)
    look_at(camera, Vector((0.0, 0.0, 0.48)))
    bpy.ops.render.render(write_still=True)
    images.append({"kind": "comparison", "path": combined.name, "sha256": sha256(combined)})

    scene.render.resolution_x = 640
    scene.render.resolution_y = 640
    for record in records:
        material_id = record["materialId"]
        for obj in all_test_objects:
            obj.hide_render = not obj.name.endswith(material_id)
        location_x = float(record["locationX"])
        camera.location = (location_x, -4.2, 2.9)
        look_at(camera, Vector((location_x, 0.0, 0.55)))
        path = output / f"{material_id}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        images.append(
            {
                "kind": "material",
                "materialId": material_id,
                "path": path.name,
                "sha256": sha256(path),
            }
        )
    for obj in all_test_objects:
        obj.hide_render = False
    return images


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.frame_end < 20:
        raise SystemExit("frame-end must be at least 20")

    library_path = args.library.resolve()
    profile_path = args.profile.resolve()
    materials = load_material_library(library_path)
    profile = load_blender_calibration_profile(profile_path)
    actual_version = ".".join(str(value) for value in bpy.app.version)
    if actual_version != profile.blender_version:
        raise RuntimeError(
            f"Blender version mismatch: expected {profile.blender_version}, got {actual_version}"
        )
    projections = project_material_library_to_blender(materials, profile)

    clean_scene()
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = args.frame_end
    scene.render.fps = 30
    camera = configure_render(scene, output)

    records: list[dict[str, Any]] = []
    spacing = 2.15
    center = (len(projections) - 1) / 2
    for index, (material, projection) in enumerate(
        zip(materials, projections, strict=True)
    ):
        location_x = (index - center) * spacing
        collection = bpy.data.collections.new(f"Test__{projection.material_id}")
        scene.collection.children.link(collection)
        collider, collider_actual = create_collider(
            projection, location_x, collection
        )
        cloth, cloth_actual = create_cloth(
            projection,
            location_x,
            collection,
            args.grid,
            args.frame_end,
            index,
            len(projections),
        )
        records.append(
            {
                "materialId": projection.material_id,
                "locationX": location_x,
                "realDrapeCoefficient": material.real_drape_coefficient,
                "projection": projection.to_dict(),
                "projectionSha256": projection.fingerprint(),
                "runtime": {
                    **cloth_actual,
                    "colliderSettings": collider_actual,
                    "clothObject": cloth.name,
                    "colliderObject": collider.name,
                },
            }
        )

    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
    scene.frame_set(scene.frame_end)
    bpy.context.view_layer.update()

    initial_area = 1.65 * 1.65
    for record in records:
        cloth = bpy.data.objects[record["runtime"]["clothObject"]]
        record["metrics"] = object_metrics(cloth, initial_area)

    distance = maximum_signature_distance(records)
    distinct = len(
        {
            (
                round(float(item["metrics"]["verticalRange"]), 4),
                round(float(item["metrics"]["standardDeviationZ"]), 4),
                round(float(item["metrics"]["footprintRatio"]), 4),
            )
            for item in records
        }
    )
    evidence_passed = distinct >= 4 and distance >= 0.15
    images = render_scene(scene, camera, output, records)
    blend_path = output / "material-drape-calibration.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)

    report = {
        "schemaVersion": 1,
        "phase": "material-drape-calibration",
        "blenderVersion": actual_version,
        "library": {
            "path": library_path.relative_to(ROOT).as_posix(),
            "sha256": sha256(library_path),
        },
        "profile": {
            "path": profile_path.relative_to(ROOT).as_posix(),
            "sha256": sha256(profile_path),
            "profileId": profile.profile_id,
        },
        "frameEnd": args.frame_end,
        "gridVerticesPerAxis": args.grid,
        "sameGeometryForAllMaterials": True,
        "sequentialFrameEvaluation": True,
        "records": records,
        "comparison": {
            "distinctDrapeSignatureCount": distinct,
            "maximumNormalizedSignatureDistance": distance,
            "passed": evidence_passed,
            "meaning": "PASS proves that the same geometry produces materially distinct Blender drapes; it does not prove absolute real-to-sim calibration.",
        },
        "images": images,
        "blend": {"path": blend_path.name, "sha256": sha256(blend_path)},
        "passed": evidence_passed,
    }
    report_path = output / "material-drape-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if evidence_passed else 2


if __name__ == "__main__":
    raise SystemExit(main(blender_arguments()))
