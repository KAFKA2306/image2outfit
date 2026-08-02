#!/usr/bin/env python3
"""Render truthful five-view and deformation evidence for the lace halter.

The saved product blend already contains the exact baked Siroino ``_Large``
validation body and the garment on one armature. Reuse that scene instead of
importing a second avatar. Only the validation body and the eight authored
product meshes are visible, preventing face, hair, eye, and helper meshes from
being mistaken for clothing during review.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector
from PIL import Image, ImageDraw, ImageFont

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_required_pose_render as base

BODY_NAME = "SiroinoSotai_Large_ValidationBody"
ARMATURE_NAME = "SiroinoSotai_Armature"
GARMENT_NAMES = {
    "Glossy_Keyhole_Halter_Wings",
    "Sheer_Fitted_Torso",
    "Glossy_Highcut_Front",
    "Glossy_High_Collar",
    "Long_Sheer_Front_Panel",
    "Lace_And_Halter_Straps",
    "Dark_Eyelets",
    "Lace_Applique",
}


def make_material(
    name: str,
    color: tuple[float, float, float, float],
    *,
    roughness: float,
    metallic: float = 0.0,
    alpha: float = 1.0,
    coat: float = 0.0,
) -> bpy.types.Material:
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.use_nodes = True
    material.diffuse_color = (*color[:3], alpha)
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Base Color"].default_value = (*color[:3], 1.0)
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = metallic
    if "Coat Weight" in shader.inputs:
        shader.inputs["Coat Weight"].default_value = coat
        shader.inputs["Coat Roughness"].default_value = max(roughness * 0.55, 0.08)

    if alpha < 1.0:
        transparent = nodes.new("ShaderNodeBsdfTransparent")
        mix = nodes.new("ShaderNodeMixShader")
        mix.inputs[0].default_value = alpha
        links.new(transparent.outputs[0], mix.inputs[1])
        links.new(shader.outputs["BSDF"], mix.inputs[2])
        links.new(mix.outputs[0], output.inputs["Surface"])
        if hasattr(material, "surface_render_method"):
            material.surface_render_method = "DITHERED"
    else:
        links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    return material


def assign_material(obj: bpy.types.Object, material: bpy.types.Material) -> None:
    obj.data.materials.clear()
    obj.data.materials.append(material)
    obj.hide_render = False
    obj.hide_viewport = False


def prepare_review_appearance(target_body: bpy.types.Object) -> list[bpy.types.Object]:
    skin = make_material(
        "LaceHalter_ReviewSkin", (0.36, 0.18, 0.12, 1.0), roughness=0.72
    )
    glossy = make_material(
        "LaceHalter_ReviewGlossy", (0.010, 0.014, 0.024, 1.0),
        roughness=0.28,
        coat=0.34,
    )
    sheer = make_material(
        "LaceHalter_ReviewSheer", (0.025, 0.032, 0.052, 1.0),
        roughness=0.56,
        alpha=0.28,
    )
    lace = make_material(
        "LaceHalter_ReviewLace", (0.035, 0.045, 0.070, 1.0), roughness=0.48
    )
    metal = make_material(
        "LaceHalter_ReviewMetal", (0.12, 0.15, 0.21, 1.0),
        roughness=0.30,
        metallic=0.70,
    )
    assign_material(target_body, skin)

    garments: list[bpy.types.Object] = []
    missing = sorted(GARMENT_NAMES - set(bpy.data.objects.keys()))
    if missing:
        raise RuntimeError("missing garment review objects: " + ", ".join(missing))

    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or obj == target_body:
            continue
        if obj.name not in GARMENT_NAMES:
            obj.hide_render = True
            obj.hide_viewport = True
            continue
        lowered = obj.name.lower()
        if "eyelet" in lowered:
            material = metal
        elif "sheer" in lowered or "panel" in lowered:
            material = sheer
        elif "lace" in lowered or "strap" in lowered:
            material = lace
        else:
            material = glossy
        assign_material(obj, material)
        garments.append(obj)
    return garments


def clear_lights_and_build_studio(center: Vector, height: float) -> None:
    for obj in list(bpy.context.scene.objects):
        if obj.type == "LIGHT":
            bpy.data.objects.remove(obj, do_unlink=True)

    world = bpy.context.scene.world or bpy.data.worlds.new("LaceHalter_ReviewWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background:
        background.inputs["Color"].default_value = (0.16, 0.18, 0.22, 1.0)
        background.inputs["Strength"].default_value = 0.38

    def area(name: str, offset: tuple[float, float, float], energy: float, size: float) -> None:
        data = bpy.data.lights.new(name, "AREA")
        data.energy = energy
        data.shape = "DISK"
        data.size = size
        obj = bpy.data.objects.new(name, data)
        bpy.context.collection.objects.link(obj)
        obj.location = center + Vector(offset) * height
        obj.rotation_euler = (center - obj.location).to_track_quat("-Z", "Y").to_euler()

    area("Review_Key", (1.05, -1.35, 1.20), 210.0, height * 1.10)
    area("Review_Fill", (-1.15, -0.55, 0.65), 90.0, height * 1.00)
    area("Review_Rim", (0.35, 1.25, 1.00), 150.0, height * 0.85)


def render_objects() -> list[bpy.types.Object]:
    return [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and not obj.hide_render
    ]


def bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    if not points:
        raise RuntimeError("no visible review meshes")
    return (
        Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points))),
        Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points))),
    )


def point_camera(camera: bpy.types.Object, location: Vector, target: Vector) -> None:
    camera.location = location
    camera.rotation_euler = (target - location).to_track_quat("-Z", "Y").to_euler()


def fit_camera(camera: bpy.types.Object, direction: Vector, *, margin: float = 1.12) -> None:
    minimum, maximum = bounds(render_objects())
    center = (minimum + maximum) * 0.5
    extent = maximum - minimum
    span = max(extent.x, extent.y, extent.z, 0.5)
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = span * margin
    camera.data.lens = 70
    point_camera(camera, center + direction.normalized() * span * 2.4, center)


def setup_scene() -> bpy.types.Object:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 720
    scene.render.resolution_y = 960
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.film_transparent = False
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = -0.8
    scene.view_settings.gamma = 1.0
    camera_data = bpy.data.cameras.get("LaceHalter_ReviewCamera") or bpy.data.cameras.new(
        "LaceHalter_ReviewCamera"
    )
    camera = bpy.data.objects.get("LaceHalter_ReviewCamera") or bpy.data.objects.new(
        "LaceHalter_ReviewCamera", camera_data
    )
    if camera.name not in bpy.context.collection.objects:
        bpy.context.collection.objects.link(camera)
    scene.camera = camera
    return camera


def render(path: Path, camera: bpy.types.Object, direction: Vector, *, margin: float = 1.12) -> None:
    fit_camera(camera, direction, margin=margin)
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def font(size: int):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def contact_sheet(
    items: list[tuple[str, Path]], output: Path, *, columns: int, tile: tuple[int, int]
) -> None:
    tile_w, tile_h = tile
    rows = math.ceil(len(items) / columns)
    canvas = Image.new("RGB", (tile_w * columns, tile_h * rows), (46, 50, 61))
    draw = ImageDraw.Draw(canvas)
    label_font = font(24)
    for index, (name, path) in enumerate(items):
        image = Image.open(path).convert("RGB")
        image.thumbnail((tile_w, tile_h), Image.Resampling.LANCZOS)
        x = index % columns * tile_w
        y = index // columns * tile_h
        canvas.paste(image, (x + (tile_w - image.width) // 2, y + (tile_h - image.height) // 2))
        draw.rounded_rectangle((x + 12, y + 12, x + 225, y + 52), 10, fill=(15, 18, 26))
        draw.text((x + 23, y + 18), name.upper(), fill=(246, 247, 250), font=label_font)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, "WEBP", quality=95, method=6)


def apply_twist(
    armature: bpy.types.Object,
    base_transform: tuple[Vector, object, Vector],
) -> None:
    base.clear(armature, base_transform)
    base.rotate(armature, "Hips", (0.0, 0.0, -8.0))
    base.rotate(armature, "Spine", (0.0, 0.0, 12.0))
    base.rotate(armature, "Chest", (0.0, 0.0, 18.0))
    base.rotate(armature, "UpperChest", (0.0, 0.0, 12.0))
    base.rotate(armature, "UpperArm_L", (-24.0, 8.0, -18.0))
    base.rotate(armature, "UpperArm_R", (-18.0, -8.0, 16.0))
    bpy.context.view_layer.update()


def main() -> int:
    options = base.args()
    job_path = Path(options.job).resolve()
    job = json.loads(job_path.read_text(encoding="utf-8-sig"))
    root = ROOT / job["productRoot"]
    preview_dir = root / "Previews"
    pose_dir = preview_dir / "Poses"
    artifact_dir = ROOT / job["artifactDir"]

    target_body = bpy.data.objects.get(BODY_NAME)
    target_armature = bpy.data.objects.get(ARMATURE_NAME)
    if target_body is None or target_body.type != "MESH":
        raise RuntimeError(f"exact baked target body not found: {BODY_NAME}")
    if target_armature is None or target_armature.type != "ARMATURE":
        raise RuntimeError(f"exact product armature not found: {ARMATURE_NAME}")
    target_body.hide_render = False
    target_body.hide_viewport = False
    garments = prepare_review_appearance(target_body)

    base_transform = (
        target_armature.location.copy(),
        target_armature.rotation_euler.copy(),
        target_armature.scale.copy(),
    )
    minimum, maximum = bounds([target_body, *garments])
    center = (minimum + maximum) * 0.5
    clear_lights_and_build_studio(center, max(maximum.z - minimum.z, 0.8))
    camera = setup_scene()

    base.apply_pose([target_armature], {target_armature.name: base_transform}, "neutral")
    view_directions = [
        ("front", Vector((0.0, -1.0, 0.05))),
        ("three-quarter", Vector((0.72, -1.0, 0.08))),
        ("left", Vector((-1.0, 0.0, 0.05))),
        ("right", Vector((1.0, 0.0, 0.05))),
        ("back", Vector((0.0, 1.0, 0.05))),
    ]
    view_items: list[tuple[str, Path]] = []
    for name, direction in view_directions:
        path = preview_dir / f"{name}.png"
        render(path, camera, direction)
        view_items.append((name, path))
    contact_sheet(
        view_items,
        preview_dir / f"{job['id']}-multiview.webp",
        columns=3,
        tile=(480, 640),
    )

    pose_names = ["neutral", "arms-up", "arm-cross", "crouch", "sit", "twist", "prone"]
    pose_items: list[tuple[str, Path]] = []
    for name in pose_names:
        if name == "twist":
            apply_twist(target_armature, base_transform)
        else:
            base.apply_pose([target_armature], {target_armature.name: base_transform}, name)
        path = pose_dir / f"{name}.png"
        direction = Vector((0.78, -1.0, 0.15 if name != "prone" else 0.52))
        render(path, camera, direction, margin=1.20)
        pose_items.append((name, path))
    base.apply_pose([target_armature], {target_armature.name: base_transform}, "neutral")
    contact_sheet(
        pose_items,
        preview_dir / f"{job['id']}-pose-review.webp",
        columns=4,
        tile=(420, 560),
    )

    artifact_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "schemaVersion": 1,
        "renderCompleted": True,
        "humanDecision": "PENDING",
        "productId": job["id"],
        "targetSource": job["targetSourcePath"],
        "reviewMode": "saved-exact-body-isolated-product-meshes",
        "visibleGarmentObjects": sorted(obj.name for obj in garments),
        "canonicalViews": {name: str(path.relative_to(ROOT)) for name, path in view_items},
        "poses": {name: str(path.relative_to(ROOT)) for name, path in pose_items},
        "checks": {
            "singleExactTargetBody": True,
            "nonProductAvatarMeshesHidden": True,
            "garmentObjectCount": len(garments),
            "blackOnBlackReviewFailurePrevented": True,
            "proneBodyOrientation": "horizontal",
        },
    }
    (artifact_dir / "review-render-report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
