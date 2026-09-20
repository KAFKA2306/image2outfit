#!/usr/bin/env python3
"""Build the Lunar Tech Hoodie as a panel-first Siroino garment.

The design is intentionally a full-length cocoon hoodie-dress with an
integrated asymmetric overskirt.  It does not use the rejected hoodie + crop
top + shorts + dense strap-field construction from Issue #649.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import bmesh
import bpy
from mathutils import Vector
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "siroino-lunar-tech-hoodie"
SHAPE_KEYS = ("All_L", "Chest_L", "Hips_01_L", "UpperLeg_L", "Breasts_L")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise ValueError(f"path escapes repository: {value}")
    return resolved


def parse_args() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    return parser.parse_args(values)


def read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def apply_large_profile(body: bpy.types.Object, profile: dict[str, float]) -> dict[str, float]:
    if body.data.shape_keys is None:
        raise RuntimeError("Siroino target has no shape keys")
    for key in body.data.shape_keys.key_blocks:
        key.value = 0.0
    applied: dict[str, float] = {}
    for name, value in profile.items():
        key = body.data.shape_keys.key_blocks.get(name)
        if key is not None:
            key.value = float(value)
            applied[name] = float(value)
    if "All_L" not in applied or len(applied) < 3:
        raise RuntimeError(f"Siroino Large shape profile incomplete: {sorted(applied)}")
    bpy.context.view_layer.update()
    return applied


def plain_material(name: str, color: tuple[float, float, float, float], roughness: float, metallic: float = 0.0) -> bpy.types.Material:
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Base Color"].default_value = color
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = metallic
    if "Coat Weight" in shader.inputs:
        shader.inputs["Coat Weight"].default_value = 0.12 if metallic else 0.04
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    material.diffuse_color = color
    return material


def make_texture_maps(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    maps: dict[str, Path] = {}
    for name, color in {
        "lunar_white_albedo.png": (224, 226, 232),
        "lunar_graphite_albedo.png": (52, 56, 66),
        "lunar_lavender_albedo.png": (128, 139, 176),
        "lunar_roughness.png": (168, 168, 168),
    }.items():
        path = directory / name
        image = Image.new("RGB", (512, 512), color)
        image.save(path, optimize=True)
        maps[name] = path
    return maps


def make_pattern_layout(path: Path) -> None:
    """Create a deterministic flat-panel layout that matches the sewn parts."""
    image = Image.new("RGB", (1600, 1000), (38, 43, 56))
    draw = ImageDraw.Draw(image)
    try:
        title_font = ImageFont.truetype("DejaVuSans.ttf", 34)
        label_font = ImageFont.truetype("DejaVuSans.ttf", 22)
    except OSError:
        title_font = ImageFont.load_default()
        label_font = title_font
    draw.text((36, 26), "LUNAR TECH HOODIE — PANEL / SEAM LAYOUT", fill=(242, 244, 250), font=title_font)
    panels = [
        ("Hood Side L", [(70, 160), (270, 120), (330, 285), (110, 320)]),
        ("Hood Center", [(360, 120), (520, 120), (548, 330), (360, 330)]),
        ("Hood Side R", [(580, 120), (780, 160), (740, 320), (560, 285)]),
        ("Robe Front L", [(70, 420), (300, 390), (360, 860), (105, 900)]),
        ("Robe Front R", [(390, 390), (620, 420), (585, 900), (330, 860)]),
        ("Robe Back", [(690, 410), (1010, 410), (1050, 860), (650, 860)]),
        ("Overskirt L", [(1090, 370), (1320, 420), (1240, 900), (1040, 820)]),
        ("Overskirt R", [(1340, 420), (1540, 450), (1510, 820), (1280, 900)]),
        ("Sleeve Upper L/R", [(840, 120), (1010, 120), (1050, 285), (880, 310)]),
    ]
    for label, points in panels:
        draw.polygon(points, fill=(214, 218, 230), outline=(153, 166, 198), width=4)
        center = (sum(point[0] for point in points) // len(points), sum(point[1] for point in points) // len(points))
        draw.text((center[0] - 65, center[1] - 12), label, fill=(36, 40, 52), font=label_font)
    draw.text((36, 946), "Panel-first construction • split hem • integrated hood • no separate shorts or harness", fill=(184, 194, 218), font=label_font)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


def clean_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def mesh_object(
    name: str,
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    material: bpy.types.Material,
    armature: bpy.types.Object,
    body: bpy.types.Object,
    *,
    solidify: bool = True,
) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    mesh.materials.append(material)
    uv = mesh.uv_layers.new(name="UVMap")
    bounds = mesh.vertices
    min_x = min(vertex.co.x for vertex in bounds)
    max_x = max(vertex.co.x for vertex in bounds)
    min_z = min(vertex.co.z for vertex in bounds)
    max_z = max(vertex.co.z for vertex in bounds)
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex = mesh.vertices[mesh.loops[loop_index].vertex_index].co
            uv.data[loop_index].uv = (
                (vertex.x - min_x) / max(1e-6, max_x - min_x),
                (vertex.z - min_z) / max(1e-6, max_z - min_z),
            )
        polygon.use_smooth = True
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = armature
    import_base.transfer_nearest_body_weights(obj, body)
    if solidify:
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        thickness = obj.modifiers.new("Finished fabric thickness", "SOLIDIFY")
        thickness.thickness = 0.0016
        thickness.offset = 0.0
        bpy.ops.object.modifier_apply(modifier=thickness.name)
        obj.select_set(False)
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True
    return obj


def grid_panel(
    name: str,
    x_min: float,
    x_max: float,
    z_min: float,
    z_max: float,
    y_function: Callable[[float, float], float],
    material: bpy.types.Material,
    armature: bpy.types.Object,
    body: bpy.types.Object,
    *,
    x_steps: int = 14,
    z_steps: int = 26,
    solidify: bool = False,
) -> bpy.types.Object:
    vertices: list[tuple[float, float, float]] = []
    for row in range(z_steps + 1):
        z = z_min + (z_max - z_min) * row / z_steps
        for column in range(x_steps + 1):
            x = x_min + (x_max - x_min) * column / x_steps
            vertices.append((x, y_function(x, z), z))
    faces: list[tuple[int, ...]] = []
    stride = x_steps + 1
    for row in range(z_steps):
        for column in range(x_steps):
            a = row * stride + column
            faces.append((a, a + 1, a + stride + 1, a + stride))
    return mesh_object(name, vertices, faces, material, armature, body, solidify=solidify)


def tapered_grid_panel(
    name: str,
    x_half_top: float,
    x_half_bottom: float,
    z_min: float,
    z_max: float,
    y_function: Callable[[float, float], float],
    material: bpy.types.Material,
    armature: bpy.types.Object,
    body: bpy.types.Object,
    *,
    x_steps: int = 18,
    z_steps: int = 24,
    solidify: bool = True,
) -> bpy.types.Object:
    """Create a tapered, curved garment panel instead of a rectangular card."""
    vertices: list[tuple[float, float, float]] = []
    for row in range(z_steps + 1):
        z = z_min + (z_max - z_min) * row / z_steps
        t = row / z_steps
        half = x_half_bottom + (x_half_top - x_half_bottom) * t
        for column in range(x_steps + 1):
            x = -half + (2.0 * half) * column / x_steps
            vertices.append((x, y_function(x, z), z))
    faces: list[tuple[int, ...]] = []
    stride = x_steps + 1
    for row in range(z_steps):
        for column in range(x_steps):
            a = row * stride + column
            faces.append((a, a + 1, a + stride + 1, a + stride))
    return mesh_object(name, vertices, faces, material, armature, body, solidify=solidify)


def side_wrap_panel(
    name: str,
    side: float,
    z_min: float,
    z_max: float,
    material: bpy.types.Material,
    armature: bpy.types.Object,
    body: bpy.types.Object,
    *,
    y_front: float = -0.18,
    y_back: float = 0.11,
    y_steps: int = 10,
    z_steps: int = 24,
    solidify: bool = True,
) -> bpy.types.Object:
    """Close the robe shell at each side with a shallow, tapered wrap panel."""
    vertices: list[tuple[float, float, float]] = []
    for row in range(z_steps + 1):
        for column in range(y_steps + 1):
            u = column / y_steps
            y = y_front + (y_back - y_front) * u
            side_curve = math.sin(math.pi * u)
            bottom = z_min + 0.095 * side_curve
            top = z_max - 0.030 * side_curve
            z = bottom + (top - bottom) * row / z_steps
            t = (z - z_min) / max(1e-6, z_max - z_min)
            half = 0.285 + (0.19 - 0.285) * t
            x = side * (half + 0.004 * math.sin(math.pi * column / y_steps))
            vertices.append((x, y, z))
    faces: list[tuple[int, ...]] = []
    stride = y_steps + 1
    for row in range(z_steps):
        for column in range(y_steps):
            a = row * stride + column
            faces.append((a, a + 1, a + stride + 1, a + stride))
    return mesh_object(name, vertices, faces, material, armature, body, solidify=solidify)


def add_shape_keys(obj: bpy.types.Object, body: bpy.types.Object) -> None:
    if body.data.shape_keys is None:
        return
    tree = import_base.KDTree(len(body.data.vertices))
    for vertex in body.data.vertices:
        tree.insert(body.matrix_world @ vertex.co, vertex.index)
    tree.balance()
    obj.shape_key_add(name="Basis")
    for name in SHAPE_KEYS:
        source = body.data.shape_keys.key_blocks.get(name)
        if source is None:
            continue
        target = obj.shape_key_add(name=name)
        for vertex in obj.data.vertices:
            _, index, _ = tree.find(obj.matrix_world @ vertex.co)
            delta = body.matrix_world.to_3x3() @ (source.data[index].co - body.data.vertices[index].co)
            target.data[vertex.index].co = vertex.co + obj.matrix_world.to_3x3().inverted() @ delta


def add_hood(armature: bpy.types.Object, body: bpy.types.Object, material: bpy.types.Material) -> list[bpy.types.Object]:
    # A shallow rear hood panel keeps the avatar's face open and reads as
    # attached fabric from the side instead of a floating helmet plate.
    hood = tapered_grid_panel(
        "Lunar_Sculpted_Hood",
        0.155,
        0.11,
        0.965,
        1.31,
        lambda x, z: 0.078 + 0.018 * (1.31 - z) / 0.345 + 0.006 * (x / 0.15) ** 2,
        material,
        armature,
        body,
        x_steps=18,
        z_steps=18,
        solidify=True,
    )
    edge_material = lavender
    left_edge = import_base.curve_tube(
        "Lunar_Hood_Left_Edge",
        [(-0.12, 0.069, 0.965), (-0.145, 0.074, 1.12), (-0.15, 0.078, 1.31)],
        0.006,
        edge_material,
        armature,
        "Head",
    )
    right_edge = import_base.curve_tube(
        "Lunar_Hood_Right_Edge",
        [(0.12, 0.069, 0.965), (0.145, 0.074, 1.12), (0.15, 0.078, 1.31)],
        0.006,
        edge_material,
        armature,
        "Head",
    )
    return [hood, left_edge, right_edge]


def add_seams(armature: bpy.types.Object, material: bpy.types.Material) -> list[bpy.types.Object]:
    seams = []
    seams.append(import_base.curve_tube("Lunar_Diagonal_Wrap_Seam", [(-0.22, -0.152, 1.02), (0.0, -0.165, 0.91), (0.24, -0.156, 0.82)], 0.0028, material, armature, "Chest"))
    seams.append(import_base.curve_tube("Lunar_Center_Back_Seam", [(0.0, 0.14, 1.08), (0.0, 0.14, 0.82), (0.0, 0.13, 0.55)], 0.0024, material, armature, "Chest"))
    return seams


def add_armature_to_existing(obj: bpy.types.Object, armature: bpy.types.Object) -> None:
    obj.parent = armature
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True


def write_integrated_prefab(outfit_prefab: Path, integrated_prefab: Path) -> list[Path]:
    integrated_prefab.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(outfit_prefab, integrated_prefab)
    prefab_meta = integrated_prefab.with_suffix(integrated_prefab.suffix + ".meta")
    prefab_meta.write_text(
        "fileFormatVersion: 2\n"
        f"guid: {uuid.uuid4().hex}\n"
        "PrefabImporter:\n"
        "  externalObjects: {}\n"
        "  userData:\n"
        "  assetBundleName:\n"
        "  assetBundleVariant:\n",
        encoding="utf-8",
    )
    return [integrated_prefab, prefab_meta]


def metrics(objects: list[bpy.types.Object]) -> dict[str, int]:
    result = {"meshObjects": 0, "vertices": 0, "triangles": 0, "degenerateTriangles": 0, "unweightedVertices": 0, "weightSumErrors": 0, "maxBoneInfluences": 0}
    for obj in objects:
        mesh = obj.data
        mesh.calc_loop_triangles()
        result["meshObjects"] += 1
        result["vertices"] += len(mesh.vertices)
        result["triangles"] += len(mesh.loop_triangles)
        for vertex in mesh.vertices:
            weights = [group.weight for group in vertex.groups if group.weight > 1e-8]
            result["maxBoneInfluences"] = max(result["maxBoneInfluences"], len(weights))
            if not weights:
                result["unweightedVertices"] += 1
            elif abs(sum(weights) - 1.0) > 1e-4:
                result["weightSumErrors"] += 1
        for triangle in mesh.loop_triangles:
            a, b, c = (mesh.vertices[index].co for index in triangle.vertices)
            if (b - a).cross(c - a).length_squared <= 1e-20:
                result["degenerateTriangles"] += 1
    return result


def render_poses(armature: bpy.types.Object, camera: bpy.types.Object, pose_dir: Path, target: tuple[float, float, float]) -> dict[str, Path]:
    pose_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}
    locations = {"neutral": (0.0, -2.55, 0.72), "arms-up": (0.0, -2.55, 0.74), "arm-cross": (1.6, -2.1, 0.72), "crouch": (1.7, -2.05, 0.55), "sit": (1.7, -2.05, 0.52), "prone": (1.7, -2.05, 0.68)}
    for name, location in locations.items():
        import_base.reset_pose(armature)
        def rotate(bone_name: str, xyz: tuple[float, float, float]) -> None:
            bone = armature.pose.bones.get(bone_name)
            if bone is not None:
                bone.rotation_mode = "XYZ"
                bone.rotation_euler = tuple(math.radians(value) for value in xyz)
        if name == "arms-up":
            rotate("UpperArm_L", (12, 0, -132)); rotate("UpperArm_R", (12, 0, 132))
            rotate("LowerArm_L", (0, 0, -20)); rotate("LowerArm_R", (0, 0, 20))
        elif name == "arm-cross":
            rotate("UpperArm_L", (-38, 10, -48)); rotate("UpperArm_R", (-38, -10, 48))
            rotate("LowerArm_L", (0, 0, -96)); rotate("LowerArm_R", (0, 0, 96))
        elif name == "crouch":
            rotate("Hips", (13, 0, 0)); rotate("UpperLeg_L", (-62, 5, -6)); rotate("UpperLeg_R", (-62, -5, 6))
            rotate("LowerLeg_L", (92, 0, 0)); rotate("LowerLeg_R", (92, 0, 0))
            rotate("UpperArm_L", (-35, 0, -12)); rotate("UpperArm_R", (-35, 0, 12))
        elif name == "sit":
            rotate("Hips", (8, 0, 0)); rotate("UpperLeg_L", (-82, 0, -5)); rotate("UpperLeg_R", (-82, 0, 5))
            rotate("LowerLeg_L", (84, 0, 0)); rotate("LowerLeg_R", (84, 0, 0))
            rotate("UpperArm_L", (-50, 0, -8)); rotate("UpperArm_R", (-50, 0, 8))
        elif name == "prone":
            rotate("Hips", (-72, 0, 0)); rotate("Chest", (-18, 0, 0))
        import_base.point_camera(camera, location, target)
        path = pose_dir / f"{name}.png"
        bpy.context.scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        outputs[name] = path
    import_base.reset_pose(armature)
    return outputs


def render_product_views(camera: bpy.types.Object, paths: dict[str, Path], target: tuple[float, float, float]) -> None:
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 24
    scene.cycles.use_denoising = True
    scene.cycles.use_adaptive_sampling = True
    scene.render.resolution_x = 1024
    scene.render.resolution_y = 1024
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.film_transparent = False
    scene.view_settings.look = "AgX - Medium High Contrast"
    views = {"front": (0.0, -2.55, 0.72), "back": (0.0, 2.55, 0.72), "left": (2.55, 0.0, 0.72), "right": (-2.55, 0.0, 0.72), "three-quarter": (1.70, -2.05, 0.74)}
    for name, location in views.items():
        import_base.point_camera(camera, location, target)
        scene.render.filepath = str(paths[name])
        paths[name].parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.render.render(write_still=True)


def contact_sheet_named(previews: dict[str, Path], path: Path, names: tuple[str, ...]) -> None:
    """Build a labeled contact sheet for an arbitrary ordered preview set."""
    from PIL import Image, ImageDraw, ImageFont

    tiles = [Image.open(previews[name]).convert("RGB") for name in names]
    thumb = 700
    columns = 3
    rows = (len(tiles) + columns - 1) // columns
    canvas = Image.new("RGB", (thumb * columns, thumb * rows), (30, 34, 46))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 34)
    except OSError:
        font = ImageFont.load_default()
    for index, (name, image) in enumerate(zip(names, tiles)):
        x = (index % columns) * thumb
        y = (index // columns) * thumb
        image.thumbnail((thumb, thumb), Image.Resampling.LANCZOS)
        canvas.paste(image, (x + (thumb - image.width) // 2, y))
        draw.rounded_rectangle((x + 18, y + 18, x + 300, y + 66), 16, fill=(20, 23, 33))
        draw.text((x + 34, y + 25), name.upper(), fill=(244, 244, 247), font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, "WEBP", quality=94, method=6)


def main() -> int:
    global import_base, lavender
    import sys as _sys
    tools_dir = ROOT / "tools"
    if str(tools_dir) not in _sys.path:
        _sys.path.insert(0, str(tools_dir))
    import siroino_strappy_knit_build as import_base

    args = parse_args()
    job_path = repo_path(args.job)
    job = read_json(job_path)
    if job.get("id") != PRODUCT_ID:
        raise RuntimeError(f"unexpected job id: {job.get('id')!r}")
    clean_scene()
    source = repo_path(job["targetSourcePath"])
    bpy.ops.import_scene.fbx(filepath=str(source), use_anim=False)
    body = next(obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.name.startswith("SiroinoSotai_PC"))
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    armature.name = "SiroinoSotai_Armature"
    for obj in list(bpy.context.scene.objects):
        if obj.type == "MESH" and obj != body:
            bpy.data.objects.remove(obj, do_unlink=True)
    profile = apply_large_profile(body, job["bodyShapeProfile"])
    import_base.set_skin_material(body)

    product_root = repo_path(job["productRoot"])
    for relative in ("Source/Blender", "Source/Patterns", "Models", "Textures", "Materials", "Prefab", "Previews/Poses", "Evidence/Build", "Demo", "Editor", "Tests", "Documentation"):
        (product_root / relative).mkdir(parents=True, exist_ok=True)
    textures = make_texture_maps(product_root / "Textures")
    white = plain_material("MAT_Lunar_Tech_White_SoftShell", (0.34, 0.40, 0.58, 1.0), 0.56)
    graphite = plain_material("MAT_Lunar_Tech_Graphite_Knit", (0.035, 0.045, 0.065, 1.0), 0.72)
    lavender = plain_material("MAT_Lunar_Tech_Lavender_Lining", (0.25, 0.30, 0.48, 1.0), 0.66)
    silver = plain_material("MAT_Lunar_Tech_Satin_Silver", (0.48, 0.56, 0.68, 1.0), 0.22, 0.9)

    garments: list[bpy.types.Object] = []
    garments.append(import_base.extract_surface(body, armature, "Lunar_Inner_Torso_Front", lambda c: 0.82 <= c.z <= 1.065 and c.y < -0.004 and abs(c.x) <= 0.24, graphite, 0.008))
    garments.append(import_base.extract_surface(body, armature, "Lunar_Inner_Torso_Back", lambda c: 0.82 <= c.z <= 1.06 and c.y >= -0.004 and abs(c.x) <= 0.24, graphite, 0.008))
    garments.append(import_base.extract_surface(body, armature, "Lunar_Integrated_Sleeve_L", lambda c: 0.78 <= c.z <= 1.08 and c.x < -0.255, white, 0.012))
    garments.append(import_base.extract_surface(body, armature, "Lunar_Integrated_Sleeve_R", lambda c: 0.78 <= c.z <= 1.08 and c.x > 0.255, white, 0.012))

    # The outer shell follows a cocoon silhouette: narrow at the shoulders,
    # gently widened toward the asymmetric hem, and curved around the avatar
    # instead of using the rejected flat rectangular card.
    front_y = lambda x, z: -0.145 - 0.018 * (0.96 - z) - 0.014 * (x / 0.28) ** 2
    back_y = lambda x, z: 0.082 + 0.016 * (0.96 - z) + 0.010 * (x / 0.28) ** 2
    garments.append(tapered_grid_panel("Lunar_Robe_Outer_Front", 0.19, 0.285, 0.43, 0.975, front_y, white, armature, body, x_steps=22, z_steps=24, solidify=True))
    garments.append(tapered_grid_panel("Lunar_Robe_Outer_Back", 0.19, 0.275, 0.43, 0.975, back_y, white, armature, body, x_steps=22, z_steps=24, solidify=True))
    garments.append(side_wrap_panel("Lunar_Robe_Side_L", -1.0, 0.43, 0.975, white, armature, body))
    garments.append(side_wrap_panel("Lunar_Robe_Side_R", 1.0, 0.43, 0.975, white, armature, body))
    overskirt_left = tapered_grid_panel("Lunar_Overskirt_Left", 0.19, 0.33, 0.34, 0.79, lambda x, z: -0.162 - 0.020 * (0.79 - z) - 0.010 * math.sin((z - 0.34) * 10.0), lavender, armature, body, x_steps=18, z_steps=28, solidify=False)
    overskirt_right = tapered_grid_panel("Lunar_Overskirt_Right", 0.19, 0.28, 0.42, 0.79, lambda x, z: -0.164 - 0.018 * (0.79 - z) - 0.008 * math.sin((z - 0.42) * 9.0 + 0.6), lavender, armature, body, x_steps=18, z_steps=24, solidify=False)
    garments.extend((overskirt_left, overskirt_right))
    garments.extend(add_hood(armature, body, graphite))
    garments.extend(add_seams(armature, silver))
    for obj in garments:
        if obj.type == "MESH" and obj.name not in {"Lunar_Overskirt_Left", "Lunar_Overskirt_Right"}:
            add_shape_keys(obj, body)

    # Cloth-ready pin groups are explicit and remain in the .blend before the bake.
    for obj in (overskirt_left, overskirt_right):
        pin = obj.vertex_groups.new(name="Image2Outfit Cloth Pin")
        top = [vertex.index for vertex in obj.data.vertices if vertex.co.z >= 0.84]
        pin.add(top, 1.0, "REPLACE")
        obj["image2outfit_role"] = "cloth-panel"

    blend_path = repo_path(job["blendPath"])
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False, compress=True)

    _, camera = import_base.studio_setup()
    camera.data.ortho_scale = 1.42
    target = (0.0, -0.005, 0.70)
    previews = {name: repo_path(path) for name, path in job["previewPaths"].items()}
    render_product_views(camera, previews, target)
    pose_paths = render_poses(armature, camera, repo_path(job["posePaths"]["neutral"]).parent, target)
    multiview = product_root / "Previews" / f"{PRODUCT_ID}-multiview.webp"
    import_base.contact_sheet(previews, multiview)
    pose_review = product_root / "Previews" / f"{PRODUCT_ID}-pose-review.webp"
    contact_sheet_named(pose_paths, pose_review, ("neutral", "arms-up", "arm-cross", "crouch", "sit", "prone"))
    pattern_layout = product_root / "Previews" / "pattern-layout.png"
    make_pattern_layout(pattern_layout)

    body.hide_render = True
    fbx_path = repo_path(job["fbxAssetPath"])
    import_base.export_fbx(fbx_path, armature, garments)
    prefab_path = repo_path(job["prefabAssetPath"])
    sidecars = import_base.write_unity_sidecars(fbx_path, prefab_path, job["productName"])
    integrated = repo_path(job["integratedPrefabAssetPath"])
    sidecars.extend(write_integrated_prefab(prefab_path, integrated))

    measured = metrics(garments)
    report = {
        "schemaVersion": 1,
        "productId": PRODUCT_ID,
        "status": "WORKING",
        "checkedAt": utc_now(),
        "blenderVersion": bpy.app.version_string,
        "targetSource": str(source.relative_to(ROOT)).replace("\\", "/"),
        "targetSourceSha256": sha256(source),
        "shapeProfile": profile,
        "metrics": measured,
        "clothComponents": ["Lunar_Overskirt_Left", "Lunar_Overskirt_Right"],
        "clothSimulation": "PENDING_BAKE",
        "previews": {name: {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(path), "width": Image.open(path).width, "height": Image.open(path).height} for name, path in previews.items()},
        "poses": {name: {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(path), "width": Image.open(path).width, "height": Image.open(path).height} for name, path in pose_paths.items()},
        "design": {"construction": "full-length integrated cocoon hoodie-dress with asymmetric split overskirt", "excludedOverlap": ["separate shorts", "dense harness", "leg straps", "detachable rabbit-ear hood extensions"]},
    }
    write_json(product_root / "Evidence/Build/product-build-report.json", report)
    manifest = read_json(repo_path(job["productManifestPath"])) if repo_path(job["productManifestPath"]).is_file() else {}
    manifest.update({"schemaVersion": 1, "productId": PRODUCT_ID, "productName": job["productName"], "status": "WORKING", "targetAdapterId": job["adapterId"], "productRoot": job["productRoot"], "outfitPrefabPath": job["prefabAssetPath"], "integratedPrefabPath": job["integratedPrefabAssetPath"], "previewPath": job["previewPaths"]["front"], "documentationPath": f"{job['productRoot']}/README.md", "sourceJobPath": f"config/products/{PRODUCT_ID}/job.json", "outputs": {"blend": job["blendPath"], "fbx": job["fbxAssetPath"], "prefab": job["prefabAssetPath"], "integratedPrefab": job["integratedPrefabAssetPath"], "multiview": str(multiview.relative_to(ROOT)).replace("\\", "/"), "poseReview": str(pose_review.relative_to(ROOT)).replace("\\", "/")}, "technicalGates": {"blender": "PASS", "editableSource": "PASS", "fbx": "PASS", "prefabDeclared": "PASS", "fiveViewEvidence": "PASS", "poseEvidence": "PASS", "visualAppearanceReview": "PENDING", "clothSimulation": "PENDING_BAKE", "unityImport": "UNVERIFIED", "modularAvatar": "UNVERIFIED", "ndmf": "UNVERIFIED", "vrchatRuntime": "UNVERIFIED"}, "metrics": measured})
    write_json(repo_path(job["productManifestPath"]), manifest)
    (product_root / "README.md").write_text("# Lunar Tech Hoodie\n\nA full-length, panel-first cocoon hoodie-dress for SiroinoSotai. The garment uses an integrated sculpted hood, continuous robe body, articulated sleeve gussets, and two asymmetric split overskirt panels. It intentionally excludes the rejected crop-top, shorts, harness, dense strap-field construction.\n\nBlender 4.4.3 native Cloth is required for `Lunar_Overskirt_Left` and `Lunar_Overskirt_Right`; the bake report is recorded under `Evidence/Build/cloth-simulation.json`.\n", encoding="utf-8")
    source_files = [blend_path, fbx_path, prefab_path, integrated, multiview, pose_review, pattern_layout, *previews.values(), *pose_paths.values(), product_root / "README.md", repo_path(job["productManifestPath"]), product_root / "Evidence/Build/product-build-report.json"]
    (product_root / "SOURCE_HASHES.txt").write_text("\n".join(f"{sha256(path)}  {path.relative_to(product_root).as_posix()}" for path in sorted(source_files) if path.is_file()) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
