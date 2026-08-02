#!/usr/bin/env python3
"""Build an original VRChat-first wide cargo outfit for SiroinoSotai.

The design is intentionally not a replica of a retail garment. It keeps the
useful visual grammar—wide legs, knee openings, asymmetric belts, cargo pockets,
and metal hardware—while producing an original, logo-free Unity product.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import bpy
import bmesh
from PIL import Image, ImageDraw, ImageFont

import siroino_strappy_knit_build as c

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "siroino-wide-cargo"


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def repo_path(value: str) -> Path:
    return c.repo_path(value)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_texture_maps(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    size = 1024
    maps: dict[str, list] = {
        "fabric_albedo": [],
        "fabric_normal": [],
        "fabric_roughness": [],
        "strap_albedo": [],
        "strap_normal": [],
        "strap_roughness": [],
    }
    for y in range(size):
        for x in range(size):
            warp = math.sin(x * math.tau / 9.0)
            weft = math.sin(y * math.tau / 11.0)
            diagonal = math.sin((x + y * 1.7) * math.tau / 31.0)
            micro = math.sin(x * 0.61 + y * 0.37)
            value = max(4, min(18, int(9 + 2 * warp + 1.5 * weft + 2 * diagonal + micro)))
            maps["fabric_albedo"].append((value, value + 1, value + 3))
            maps["fabric_normal"].append(
                (
                    int(128 + 14 * warp + 6 * diagonal),
                    int(128 + 11 * weft - 4 * diagonal),
                    252,
                )
            )
            maps["fabric_roughness"].append(int(183 + 11 * diagonal + 5 * micro))

            ridge = 0.5 + 0.5 * math.sin(x * math.tau / 20.0)
            strap_value = int(5 + 5 * ridge + micro)
            maps["strap_albedo"].append((strap_value, strap_value, strap_value + 2))
            maps["strap_normal"].append(
                (int(128 + 21 * math.sin(x * math.tau / 20.0)), 128, 251)
            )
            maps["strap_roughness"].append(int(147 + 18 * (1.0 - ridge)))

    result: dict[str, Path] = {}
    specifications = (
        ("fabric_albedo", "black_cargo_albedo.png", "RGB"),
        ("fabric_normal", "black_cargo_normal.png", "RGB"),
        ("fabric_roughness", "black_cargo_roughness.png", "L"),
        ("strap_albedo", "black_strap_albedo.png", "RGB"),
        ("strap_normal", "black_strap_normal.png", "RGB"),
        ("strap_roughness", "black_strap_roughness.png", "L"),
    )
    for key, name, mode in specifications:
        path = directory / name
        image = Image.new(mode, (size, size))
        image.putdata(maps[key])
        image.save(path, optimize=True)
        result[key] = path
    return result


def clean_topology(obj: bpy.types.Object) -> None:
    """Triangulate and remove every zero-area polygon before shape keys exist."""
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-7, edges=list(bm.edges))
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    zero_area = [face for face in bm.faces if face.calc_area() <= 1e-12]
    if zero_area:
        bmesh.ops.delete(bm, geom=zero_area, context="FACES")
    loose = [vertex for vertex in bm.verts if not vertex.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update(calc_edges=True)

    mesh.calc_loop_triangles()
    bad_polygons = {
        triangle.polygon_index
        for triangle in mesh.loop_triangles
        if (
            (mesh.vertices[triangle.vertices[1]].co - mesh.vertices[triangle.vertices[0]].co)
            .cross(mesh.vertices[triangle.vertices[2]].co - mesh.vertices[triangle.vertices[0]].co)
            .length_squared
            <= 1e-20
        )
    }
    if bad_polygons:
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()
        bmesh.ops.delete(
            bm,
            geom=[bm.faces[index] for index in sorted(bad_polygons)],
            context="FACES",
        )
        loose = [vertex for vertex in bm.verts if not vertex.link_faces]
        if loose:
            bmesh.ops.delete(bm, geom=loose, context="VERTS")
        bm.to_mesh(mesh)
        bm.free()
        mesh.update(calc_edges=True)


def finish_skinned(
    obj: bpy.types.Object,
    body: bpy.types.Object,
    *,
    add_shape_keys: bool = True,
) -> bpy.types.Object:
    clean_topology(obj)
    c.transfer_nearest_body_weights(obj, body)
    if add_shape_keys:
        c.add_nearest_shape_keys(obj, body)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    return obj


def mesh_object(
    name: str,
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    material: bpy.types.Material,
    armature: bpy.types.Object,
    body: bpy.types.Object,
    *,
    solidify: float = 0.0014,
    bevel: float = 0.0008,
    add_shape_keys: bool = True,
) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = armature
    armature_modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    armature_modifier.object = armature
    armature_modifier.use_deform_preserve_volume = True

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if solidify > 0:
        modifier = obj.modifiers.new("Fabric thickness", "SOLIDIFY")
        modifier.thickness = solidify
        modifier.offset = 0.0
        modifier.use_even_offset = True
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    if bevel > 0:
        modifier = obj.modifiers.new("Finished edges", "BEVEL")
        modifier.width = bevel
        modifier.segments = 2
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    obj.select_set(False)
    return finish_skinned(obj, body, add_shape_keys=add_shape_keys)


def asymmetric_leg_shell(
    name: str,
    side: int,
    rings: list[tuple[float, float, float, float, float]],
    material: bpy.types.Material,
    armature: bpy.types.Object,
    body: bpy.types.Object,
    segments: int = 48,
) -> bpy.types.Object:
    """Create one leg with independent inner and outer widths.

    Ring tuple: z, inner_abs_x, outer_abs_x, front_depth, back_depth.
    """
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for z, inner, outer, front, back in rings:
        center_abs = (inner + outer) * 0.5
        radius_x = (outer - inner) * 0.5
        center_x = side * center_abs
        for index in range(segments):
            angle = math.tau * index / segments
            depth = front if math.sin(angle) < 0 else back
            x = center_x + side * radius_x * math.cos(angle)
            y = depth * math.sin(angle)
            vertices.append((x, y, z))
    for ring in range(len(rings) - 1):
        for index in range(segments):
            next_index = (index + 1) % segments
            a = ring * segments + index
            b = ring * segments + next_index
            c_index = (ring + 1) * segments + next_index
            d = (ring + 1) * segments + index
            faces.append((a, b, c_index, d))
    return mesh_object(name, vertices, faces, material, armature, body)


def flat_ellipse_band(
    name: str,
    center_x: float,
    radius_x: float,
    radius_y: float,
    z: float,
    width: float,
    material: bpy.types.Material,
    armature: bpy.types.Object,
    body: bpy.types.Object,
    *,
    segments: int = 64,
    slope: float = 0.0,
    phase: float = 0.0,
) -> bpy.types.Object:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for index in range(segments):
        angle = math.tau * index / segments
        local_z = z + slope * math.sin(angle + phase)
        x = center_x + radius_x * math.cos(angle)
        y = radius_y * math.sin(angle)
        vertices.extend(((x, y, local_z - width * 0.5), (x, y, local_z + width * 0.5)))
    for index in range(segments):
        next_index = (index + 1) % segments
        faces.append((index * 2, next_index * 2, next_index * 2 + 1, index * 2 + 1))
    return mesh_object(
        name,
        vertices,
        faces,
        material,
        armature,
        body,
        solidify=0.0022,
        bevel=0.0005,
    )


def flat_path_ribbon(
    name: str,
    points: Iterable[tuple[float, float, float]],
    width: float,
    material: bpy.types.Material,
    armature: bpy.types.Object,
    body: bpy.types.Object,
) -> bpy.types.Object:
    points = list(points)
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for x, y, z in points:
        vertices.extend(((x, y, z - width * 0.5), (x, y, z + width * 0.5)))
    for index in range(len(points) - 1):
        faces.append((index * 2, index * 2 + 2, index * 2 + 3, index * 2 + 1))
    return mesh_object(
        name,
        vertices,
        faces,
        material,
        armature,
        body,
        solidify=0.0018,
        bevel=0.00045,
    )


def rounded_box(
    name: str,
    location: tuple[float, float, float],
    scale: tuple[float, float, float],
    material: bpy.types.Material,
    armature: bpy.types.Object,
    body: bpy.types.Object,
    *,
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    bevel: float = 0.004,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(location=location, rotation=rotation)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(material)
    modifier = obj.modifiers.new("Rounded edges", "BEVEL")
    modifier.width = bevel
    modifier.segments = 3
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    obj.parent = armature
    armature_modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    armature_modifier.object = armature
    return finish_skinned(obj, body)


def buckle(
    name: str,
    center: tuple[float, float, float],
    width: float,
    height: float,
    material: bpy.types.Material,
    armature: bpy.types.Object,
    body: bpy.types.Object,
) -> bpy.types.Object:
    x, y, z = center
    obj = c.curve_tube(
        name,
        (
            (x - width, y, z - height),
            (x + width, y, z - height),
            (x + width, y, z + height),
            (x - width, y, z + height),
        ),
        0.0016,
        material,
        armature,
        "Hips",
        cyclic=True,
        resolution=2,
    )
    return finish_skinned(obj, body, add_shape_keys=False)


def create_outfit(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    fabric: bpy.types.Material,
    strap: bpy.types.Material,
    metal: bpy.types.Material,
) -> list[bpy.types.Object]:
    objects: list[bpy.types.Object] = []

    upper_rings = (
        (0.782, 0.018, 0.156, 0.108, 0.103),
        (0.715, 0.022, 0.176, 0.116, 0.110),
        (0.625, 0.026, 0.190, 0.120, 0.114),
        (0.525, 0.030, 0.202, 0.116, 0.112),
        (0.458, 0.034, 0.207, 0.109, 0.108),
    )
    lower_rings = (
        (0.392, 0.038, 0.203, 0.108, 0.107),
        (0.305, 0.035, 0.218, 0.114, 0.112),
        (0.205, 0.031, 0.238, 0.121, 0.118),
        (0.105, 0.029, 0.257, 0.130, 0.126),
        (0.032, 0.036, 0.270, 0.137, 0.132),
    )
    for side_name, side in (("L", -1), ("R", 1)):
        objects.append(
            asymmetric_leg_shell(
                f"Cargo_UpperLeg_{side_name}", side, list(upper_rings), fabric, armature, body
            )
        )
        objects.append(
            asymmetric_leg_shell(
                f"Cargo_LowerLeg_{side_name}", side, list(lower_rings), fabric, armature, body
            )
        )

        center_x = side * (0.038 + 0.203) * 0.5
        radius_x = (0.203 - 0.038) * 0.5
        for index, z in enumerate((0.438, 0.412), start=1):
            objects.append(
                flat_ellipse_band(
                    f"Knee_Strap_{side_name}_{index}",
                    center_x,
                    radius_x + 0.006,
                    0.112,
                    z,
                    0.011,
                    strap,
                    armature,
                    body,
                )
            )

        pocket_x = side * 0.196
        rotation = (0.0, math.radians(side * 4.0), math.radians(side * -3.0))
        objects.append(
            rounded_box(
                f"Cargo_Pocket_{side_name}",
                (pocket_x, -0.020, 0.575),
                (0.047, 0.022, 0.066),
                fabric,
                armature,
                body,
                rotation=rotation,
                bevel=0.006,
            )
        )
        objects.append(
            rounded_box(
                f"Cargo_Pocket_Flap_{side_name}",
                (pocket_x, -0.044, 0.627),
                (0.052, 0.007, 0.017),
                strap,
                armature,
                body,
                rotation=rotation,
                bevel=0.003,
            )
        )

        zipper_x = side * 0.192
        objects.append(
            flat_path_ribbon(
                f"Knee_Zipper_{side_name}",
                (
                    (zipper_x, -0.108, 0.486),
                    (zipper_x + side * 0.004, -0.111, 0.451),
                    (zipper_x + side * 0.007, -0.112, 0.420),
                ),
                0.0035,
                metal,
                armature,
                body,
            )
        )
        objects.append(
            buckle(
                f"Knee_Zip_Pull_{side_name}",
                (zipper_x + side * 0.007, -0.114, 0.408),
                0.005,
                0.008,
                metal,
                armature,
                body,
            )
        )

        for index, z in enumerate((0.756, 0.724), start=1):
            objects.append(
                flat_path_ribbon(
                    f"Hip_Cutout_Strap_{side_name}_{index}",
                    (
                        (side * 0.137, -0.075, z),
                        (side * 0.168, -0.010, z - 0.004),
                        (side * 0.138, 0.075, z - 0.001),
                    ),
                    0.008,
                    strap,
                    armature,
                    body,
                )
            )
        ring = c.torus(
            f"Hip_Ring_{side_name}",
            (side * 0.171, -0.011, 0.738),
            0.009,
            0.0017,
            metal,
            armature,
            "Hips",
        )
        ring.rotation_euler = (math.pi / 2.0, 0.0, 0.0)
        objects.append(finish_skinned(ring, body, add_shape_keys=False))

    objects.append(
        flat_ellipse_band(
            "Primary_Waist_Belt",
            0.0,
            0.161,
            0.113,
            0.792,
            0.016,
            strap,
            armature,
            body,
        )
    )
    objects.append(
        flat_ellipse_band(
            "Asymmetric_Waist_Belt",
            0.0,
            0.166,
            0.118,
            0.810,
            0.012,
            strap,
            armature,
            body,
            slope=0.018,
            phase=0.72,
        )
    )
    objects.append(
        buckle("Front_Belt_Buckle", (0.071, -0.116, 0.794), 0.015, 0.013, metal, armature, body)
    )
    objects.append(
        buckle("Side_Belt_Buckle", (-0.148, -0.045, 0.819), 0.012, 0.011, metal, armature, body)
    )

    objects.append(
        flat_path_ribbon(
            "Long_Center_Zipper",
            (
                (0.0, -0.116, 0.780),
                (0.0, -0.120, 0.725),
                (0.0, -0.122, 0.668),
                (0.0, -0.121, 0.626),
            ),
            0.0035,
            metal,
            armature,
            body,
        )
    )
    objects.append(
        buckle("Center_Zip_Pull", (0.0, -0.124, 0.614), 0.006, 0.010, metal, armature, body)
    )

    return objects


def studio_previews(
    camera: bpy.types.Object,
    armature: bpy.types.Object,
    paths: dict[str, Path],
) -> dict[str, Path]:
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 28
    scene.cycles.use_denoising = True
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = 0.045
    scene.render.resolution_x = 1200
    scene.render.resolution_y = 1200
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.look = "AgX - Medium High Contrast"
    c.reset_pose(armature)
    positions = {
        "front": (0.0, -2.45, 0.58),
        "back": (0.0, 2.45, 0.58),
        "left": (2.45, 0.0, 0.58),
        "right": (-2.45, 0.0, 0.58),
        "three-quarter": (1.62, -1.90, 0.64),
    }
    for name, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        c.point_camera(camera, positions[name], (0.0, 0.0, 0.42))
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
    return {"neutral": paths["three-quarter"]}


def contact_sheet(paths: dict[str, Path], output: Path, columns: int = 3) -> None:
    tile = 600
    rows = max(1, math.ceil(len(paths) / columns))
    canvas = Image.new("RGB", (tile * columns, tile * rows), (26, 29, 38))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 30)
    except OSError:
        font = ImageFont.load_default()
    for index, (name, path) in enumerate(paths.items()):
        image = Image.open(path).convert("RGB")
        image.thumbnail((tile, tile), Image.Resampling.LANCZOS)
        x = index % columns * tile
        y = index // columns * tile
        canvas.paste(image, (x + (tile - image.width) // 2, y))
        draw.rounded_rectangle((x + 18, y + 18, x + 260, y + 62), 14, fill=(15, 18, 25))
        draw.text((x + 30, y + 24), name.upper(), fill=(245, 245, 248), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, "WEBP", quality=94, method=6)


def per_object_metrics(objects: list[bpy.types.Object]) -> list[dict]:
    result = []
    for obj in objects:
        mesh = obj.data
        mesh.calc_loop_triangles()
        degenerates = 0
        for triangle in mesh.loop_triangles:
            a, b, c_vertex = (mesh.vertices[index].co for index in triangle.vertices)
            if (b - a).cross(c_vertex - a).length_squared <= 1e-20:
                degenerates += 1
        result.append(
            {
                "name": obj.name,
                "vertices": len(mesh.vertices),
                "triangles": len(mesh.loop_triangles),
                "degenerateTriangles": degenerates,
            }
        )
    return result


def main() -> int:
    _, job = c.load_job()
    c.clean_scene()
    source = repo_path(job["targetSourcePath"])
    blend_path = repo_path(job["blendPath"])
    fbx_path = repo_path(job["fbxAssetPath"])
    prefab_path = repo_path(job["prefabAssetPath"])
    artifact_dir = repo_path(job["artifactDir"])
    product_root = fbx_path.parents[1]
    texture_dir = product_root / "Textures"
    preview_dir = product_root / "Previews"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    fbx_path.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.import_scene.fbx(filepath=str(source), use_anim=False)
    body = next(
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.name.startswith("SiroinoSotai_PC")
    )
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    armature.name = "SiroinoSotai_Armature"
    c.set_skin_material(body)

    texture_maps = make_texture_maps(texture_dir)
    fabric = c.textured_material(
        "MAT_Black_Cargo_Fabric",
        texture_maps["fabric_albedo"],
        texture_maps["fabric_normal"],
        texture_maps["fabric_roughness"],
        normal_strength=0.34,
        sheen=0.08,
    )
    strap = c.textured_material(
        "MAT_Black_Cargo_Straps",
        texture_maps["strap_albedo"],
        texture_maps["strap_normal"],
        texture_maps["strap_roughness"],
        normal_strength=0.20,
        sheen=0.04,
    )
    metal = c.plain_material(
        "MAT_Brushed_Gunmetal",
        (0.26, 0.31, 0.39, 1.0),
        roughness=0.17,
        metallic=0.95,
    )
    garments = create_outfit(body, armature, fabric, strap, metal)

    blend_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)

    _, camera = c.studio_setup()
    camera.data.ortho_scale = 1.20
    preview_paths = {name: repo_path(value) for name, value in job["previewPaths"].items()}
    neutral_pose = studio_previews(camera, armature, preview_paths)
    contact_sheet(preview_paths, preview_dir / "siroino-wide-cargo-multiview.webp")
    contact_sheet(neutral_pose, preview_dir / "siroino-wide-cargo-pose-review.webp", columns=1)

    c.reset_pose(armature)
    body.hide_render = True
    c.export_fbx(fbx_path, armature, garments)
    sidecars = c.write_unity_sidecars(fbx_path, prefab_path, "SiroinoWideCargo")
    metrics = c.metrics(garments)
    object_metrics = per_object_metrics(garments)
    passed = (
        metrics["meshObjects"] >= 18
        and metrics["vertices"] >= 2500
        and metrics["triangles"] >= 4500
        and metrics["unweightedVertices"] == 0
        and metrics["weightSumErrors"] == 0
        and metrics["degenerateTriangles"] == 0
        and metrics["maxBoneInfluences"] <= 4
    )
    report = {
        "schemaVersion": 1,
        "passed": passed,
        "checkedAt": now(),
        "productId": PRODUCT_ID,
        "blenderVersion": bpy.app.version_string,
        "targetSource": str(source.relative_to(ROOT)).replace("\\", "/"),
        "targetSourceSha256": sha256(source),
        "metrics": metrics,
        "objects": object_metrics,
        "previews": {
            name: {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256(path),
                "width": Image.open(path).width,
                "height": Image.open(path).height,
            }
            for name, path in preview_paths.items()
        },
        "design": {
            "originalRedesign": True,
            "brandMarksIncluded": False,
            "separatedLegSilhouette": True,
            "kneeOpenings": True,
            "flatBelts": True,
        },
    }
    (artifact_dir / "blender-product.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    readme_path = product_root / "README.md"
    readme_path.write_text(
        "# Siroino Wide Cargo\n\n"
        "Original, logo-free wide cargo outfit for SiroinoSotai v1.0. "
        "The product uses separated wide legs, intentional knee openings, flat belts, "
        "asymmetric hardware, cargo pockets, and a long front zipper.\n\n"
        "Place `Prefabs/Outfit/SiroinoWideCargo.prefab` directly under the avatar root. "
        "Modular Avatar merges the garment armature during the NDMF build.\n\n"
        f"Static metrics: {metrics['vertices']} vertices, {metrics['triangles']} triangles, "
        f"{metrics['maxBoneInfluences']} maximum bone influences.\n",
        encoding="utf-8",
    )
    manifest_path = product_root / "ProductManifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if manifest_path.exists()
        else {}
    )
    manifest.update(
        {
            "schemaVersion": 1,
            "productId": PRODUCT_ID,
            "productName": "Siroino Wide Cargo",
            "status": "MODELED" if passed else "NO-GO",
            "targetAdapterId": "siroino-v1.0",
            "productRoot": "Assets/GenWorks/siroino-wide-cargo",
            "outfitPrefabPath": "Assets/GenWorks/siroino-wide-cargo/Prefab/SiroinoWideCargo.prefab",
            "integratedPrefabPath": "Assets/GenWorks/siroino-wide-cargo/Prefab/SiroinoSotai_WideCargo.prefab",
            "previewPath": "Assets/GenWorks/siroino-wide-cargo/Previews/front.png",
            "documentationPath": "Assets/GenWorks/siroino-wide-cargo/README.md",
            "sourceJobPath": "Assets/_Local/Jobs/siroino-wide-cargo/job.json",
            "generatedAt": report["checkedAt"],
            "blenderVersion": report["blenderVersion"],
            "metrics": metrics,
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    files = [
        blend_path,
        fbx_path,
        prefab_path,
        readme_path,
        manifest_path,
        *sidecars,
        *texture_maps.values(),
        *preview_paths.values(),
        preview_dir / "siroino-wide-cargo-multiview.webp",
        preview_dir / "siroino-wide-cargo-pose-review.webp",
    ]
    (product_root / "SOURCE_HASHES.txt").write_text(
        "\n".join(
            f"{sha256(path)}  {path.relative_to(product_root).as_posix()}"
            for path in sorted(files)
            if path.is_file()
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
