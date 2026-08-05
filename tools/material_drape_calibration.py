#!/usr/bin/env python3
"""Run a deterministic Blender 4.4 circular drape comparison."""

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

SPECIMEN_RADIUS_M = 0.82
SUPPORT_RADIUS_M = 0.22
SUPPORT_TOP_Z_M = 0.8
INITIAL_SPECIMEN_Z_M = 0.82


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
    parser.add_argument("--frame-end", type=int, default=120)
    parser.add_argument("--rings", type=int, default=14)
    parser.add_argument("--segments", type=int, default=64)
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


def circular_mesh(
    name: str, radius: float, rings: int, segments: int
) -> bpy.types.Mesh:
    if rings < 4 or segments < 24:
        raise ValueError(
            "circular specimen requires at least four rings and 24 segments"
        )
    vertices: list[tuple[float, float, float]] = [(0.0, 0.0, 0.0)]
    for ring in range(1, rings + 1):
        radial = radius * ring / rings
        for segment in range(segments):
            angle = math.tau * segment / segments
            vertices.append((radial * math.cos(angle), radial * math.sin(angle), 0.0))

    faces: list[tuple[int, ...]] = []
    first_ring = 1
    for segment in range(segments):
        faces.append(
            (
                0,
                first_ring + segment,
                first_ring + (segment + 1) % segments,
            )
        )
    for ring in range(2, rings + 1):
        inner = 1 + (ring - 2) * segments
        outer = 1 + (ring - 1) * segments
        for segment in range(segments):
            next_segment = (segment + 1) % segments
            faces.append(
                (
                    inner + segment,
                    outer + segment,
                    outer + next_segment,
                    inner + next_segment,
                )
            )
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


def dark_material(name: str) -> bpy.types.Material:
    material = bpy.data.materials.new(name)
    material.diffuse_color = (0.1, 0.11, 0.14, 1.0)
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    if principled is not None:
        principled.inputs["Base Color"].default_value = (0.1, 0.11, 0.14, 1.0)
        principled.inputs["Roughness"].default_value = 0.52
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


def collision_object(
    obj: bpy.types.Object,
    settings: dict[str, float],
) -> dict[str, Any]:
    obj.modifiers.new(name="Collision", type="COLLISION")
    if obj.collision is None:
        raise RuntimeError("Collision modifier did not expose Object.collision")
    return set_properties(obj.collision, settings, f"{obj.name}.collision")


def create_floor(
    scene: bpy.types.Scene, contact_static_friction: float
) -> dict[str, Any]:
    bpy.ops.mesh.primitive_plane_add(size=18.0, location=(0.0, 0.0, 0.0))
    floor = bpy.context.object
    floor.name = "CalibrationFloor"
    floor.data.materials.append(dark_material("FloorMaterial"))
    return collision_object(
        floor,
        {
            "cloth_friction": contact_static_friction,
            "thickness_outer": 0.002,
        },
    )


def create_support(
    projection: BlenderMaterialProjection,
    location_x: float,
    collection: bpy.types.Collection,
) -> tuple[bpy.types.Object, dict[str, Any]]:
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=64,
        radius=SUPPORT_RADIUS_M,
        depth=SUPPORT_TOP_Z_M,
        location=(location_x, 0.0, SUPPORT_TOP_Z_M / 2),
    )
    support = bpy.context.object
    support.name = f"Support__{projection.material_id}"
    for source in tuple(support.users_collection):
        source.objects.unlink(support)
    collection.objects.link(support)
    support.data.materials.append(
        dark_material(f"SupportMaterial__{projection.material_id}")
    )
    actual = collision_object(support, dict(projection.collider_settings))
    return support, actual


def create_cloth(
    projection: BlenderMaterialProjection,
    location_x: float,
    collection: bpy.types.Collection,
    rings: int,
    segments: int,
    frame_end: int,
    index: int,
    total: int,
) -> tuple[bpy.types.Object, dict[str, Any]]:
    mesh = circular_mesh(
        f"Mesh__{projection.material_id}", SPECIMEN_RADIUS_M, rings, segments
    )
    cloth = bpy.data.objects.new(f"Cloth__{projection.material_id}", mesh)
    cloth.location = (location_x, 0.0, INITIAL_SPECIMEN_Z_M)
    collection.objects.link(cloth)
    cloth.data.materials.append(create_material(cloth.name, index, total))

    cloth_modifier = cloth.modifiers.new(name="Cloth", type="CLOTH")
    surface_area = math.pi * SPECIMEN_RADIUS_M**2
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

    bpy.ops.object.camera_add(location=(0.0, -10.0, 6.3))
    camera = bpy.context.object
    camera.name = "CalibrationCamera"
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 6.0
    look_at(camera, Vector((0.0, 0.0, 0.42)))
    scene.camera = camera

    bpy.ops.object.light_add(type="AREA", location=(0.0, -1.5, 8.0))
    key = bpy.context.object
    key.name = "KeyLight"
    key.data.energy = 1700
    key.data.shape = "RECTANGLE"
    key.data.size = 9.0
    key.data.size_y = 5.0
    look_at(key, Vector((0.0, 0.0, 0.4)))

    bpy.ops.object.light_add(type="AREA", location=(0.0, 5.0, 4.5))
    fill = bpy.context.object
    fill.name = "FillLight"
    fill.data.energy = 950
    fill.data.size = 8.0
    look_at(fill, Vector((0.0, 0.0, 0.4)))
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
    return (
        abs(
            sum(
                first[0] * second[1] - second[0] * first[1]
                for first, second in zip(points, points[1:] + points[:1], strict=True)
            )
        )
        / 2
    )


def object_metrics(
    cloth: bpy.types.Object, initial_area: float
) -> dict[str, float | str]:
    solidify = cloth.modifiers.get("RenderThickness")
    original_show = solidify.show_viewport if solidify is not None else False
    if solidify is not None:
        solidify.show_viewport = False
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = cloth.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            coordinates = [
                evaluated.matrix_world @ vertex.co for vertex in mesh.vertices
            ]
        finally:
            evaluated.to_mesh_clear()
    finally:
        if solidify is not None:
            solidify.show_viewport = original_show
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


def average_ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(indexed):
        end = position + 1
        while end < len(indexed) and math.isclose(
            indexed[end][1], indexed[position][1]
        ):
            end += 1
        rank = (position + 1 + end) / 2
        for index, _ in indexed[position:end]:
            ranks[index] = rank
        position = end
    return ranks


def pearson(first: list[float], second: list[float]) -> float:
    first_mean = statistics.fmean(first)
    second_mean = statistics.fmean(second)
    numerator = sum(
        (left - first_mean) * (right - second_mean)
        for left, right in zip(first, second, strict=True)
    )
    first_scale = math.sqrt(sum((value - first_mean) ** 2 for value in first))
    second_scale = math.sqrt(sum((value - second_mean) ** 2 for value in second))
    if math.isclose(first_scale, 0.0) or math.isclose(second_scale, 0.0):
        return 0.0
    return numerator / (first_scale * second_scale)


def spearman(first: list[float], second: list[float]) -> float:
    return pearson(average_ranks(first), average_ranks(second))


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


def plausibility_errors(record: dict[str, Any]) -> list[str]:
    metrics = record["metrics"]
    errors: list[str] = []
    if float(metrics["minimumZ"]) < -0.02:
        errors.append("below-floor")
    if float(metrics["maximumZ"]) > INITIAL_SPECIMEN_Z_M + 0.08:
        errors.append("upward-explosion")
    if float(metrics["verticalRange"]) < 0.12:
        errors.append("insufficient-drape-range")
    if float(metrics["verticalRange"]) > 1.0:
        errors.append("excessive-drape-range")
    if float(metrics["standardDeviationZ"]) < 0.02:
        errors.append("flat-flight-state")
    if not 0.07 <= float(metrics["footprintRatio"]) <= 1.05:
        errors.append("invalid-footprint")
    return errors


def render_scene(
    scene: bpy.types.Scene,
    camera: bpy.types.Object,
    output: Path,
    records: list[dict[str, Any]],
) -> list[dict[str, str]]:
    images: list[dict[str, str]] = []
    test_objects = [
        obj for obj in bpy.data.objects if obj.name.startswith(("Cloth__", "Support__"))
    ]
    combined = output / "comparison.png"
    scene.render.resolution_x = 1440
    scene.render.resolution_y = 720
    scene.render.filepath = str(combined)
    for obj in test_objects:
        obj.hide_render = False
    camera.data.ortho_scale = 6.0
    camera.location = (0.0, -10.0, 6.3)
    look_at(camera, Vector((0.0, 0.0, 0.42)))
    bpy.ops.render.render(write_still=True)
    images.append(
        {"kind": "comparison", "path": combined.name, "sha256": sha256(combined)}
    )

    scene.render.resolution_x = 640
    scene.render.resolution_y = 640
    for record in records:
        material_id = record["materialId"]
        for obj in test_objects:
            obj.hide_render = not obj.name.endswith(material_id)
        location_x = float(record["locationX"])
        camera.data.ortho_scale = 2.25
        camera.location = (location_x, -3.4, 2.45)
        look_at(camera, Vector((location_x, 0.0, 0.42)))
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
    for obj in test_objects:
        obj.hide_render = False
    return images


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.frame_end < 60:
        raise SystemExit("frame-end must be at least 60")

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
    floor_settings = create_floor(scene, profile.contact.static_friction)

    records: list[dict[str, Any]] = []
    spacing = 2.05
    center = (len(projections) - 1) / 2
    for index, (material, projection) in enumerate(
        zip(materials, projections, strict=True)
    ):
        location_x = (index - center) * spacing
        collection = bpy.data.collections.new(f"Test__{projection.material_id}")
        scene.collection.children.link(collection)
        support, support_actual = create_support(projection, location_x, collection)
        cloth, cloth_actual = create_cloth(
            projection,
            location_x,
            collection,
            args.rings,
            args.segments,
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
                    "supportSettings": support_actual,
                    "clothObject": cloth.name,
                    "supportObject": support.name,
                },
            }
        )

    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
    scene.frame_set(scene.frame_end)
    bpy.context.view_layer.update()

    initial_area = math.pi * SPECIMEN_RADIUS_M**2
    for record in records:
        cloth = bpy.data.objects[record["runtime"]["clothObject"]]
        record["metrics"] = object_metrics(cloth, initial_area)
        record["plausibilityErrors"] = plausibility_errors(record)

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
    real_coefficients = [float(item["realDrapeCoefficient"]) for item in records]
    simulated_footprints = [
        float(item["metrics"]["footprintRatio"]) for item in records
    ]
    rank_correlation = spearman(real_coefficients, simulated_footprints)
    failed_materials = [
        {
            "materialId": item["materialId"],
            "errors": item["plausibilityErrors"],
        }
        for item in records
        if item["plausibilityErrors"]
    ]
    evidence_passed = distinct >= 5 and distance >= 0.15 and not failed_materials
    images = render_scene(scene, camera, output, records)
    blend_path = output / "material-drape-calibration.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)

    report = {
        "schemaVersion": 2,
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
        "fixture": {
            "type": "circular-drape-over-central-pedestal",
            "specimenRadiusM": SPECIMEN_RADIUS_M,
            "supportRadiusM": SUPPORT_RADIUS_M,
            "supportTopZM": SUPPORT_TOP_Z_M,
            "initialSpecimenZM": INITIAL_SPECIMEN_Z_M,
            "rings": args.rings,
            "segments": args.segments,
            "floorCollisionSettings": floor_settings,
        },
        "frameEnd": args.frame_end,
        "sameGeometryForAllMaterials": True,
        "sequentialFrameEvaluation": True,
        "records": records,
        "comparison": {
            "distinctDrapeSignatureCount": distinct,
            "maximumNormalizedSignatureDistance": distance,
            "spearmanRealDrapeCoefficientVsFootprintRatio": rank_correlation,
            "plausibilityFailures": failed_materials,
            "passed": evidence_passed,
            "meaning": "PASS proves plausible, materially distinct same-geometry Blender drapes. It does not prove absolute real-to-sim calibration or measured contact friction.",
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
