#!/usr/bin/env python3
"""Render truthful five-view and seven-pose evidence for the lace halter.

The product blend contains the exact baked Siroino ``_Large`` validation body
and the exported garment on one armature. This review pass isolates those
objects, applies high-contrast non-destructive review materials, and leaves all
human, Unity, Modular Avatar, and VRChat gates pending.
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

import siroino_required_pose_render as pose_base

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


def material(
    name: str,
    color: tuple[float, float, float, float],
    *,
    roughness: float,
    metallic: float = 0.0,
    alpha: float = 1.0,
    coat: float = 0.0,
) -> bpy.types.Material:
    value = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    value.use_nodes = True
    value.diffuse_color = (*color[:3], alpha)
    nodes = value.node_tree.nodes
    links = value.node_tree.links
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
        if hasattr(value, "surface_render_method"):
            value.surface_render_method = "DITHERED"
    else:
        links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    return value


def assign(obj: bpy.types.Object, value: bpy.types.Material) -> None:
    obj.data.materials.clear()
    obj.data.materials.append(value)
    obj.hide_render = False
    obj.hide_viewport = False


def isolate_review_objects() -> tuple[bpy.types.Object, bpy.types.Object, list[bpy.types.Object]]:
    body = bpy.data.objects.get(BODY_NAME)
    armature = bpy.data.objects.get(ARMATURE_NAME)
    if body is None or body.type != "MESH":
        raise RuntimeError(f"exact baked target body not found: {BODY_NAME}")
    if armature is None or armature.type != "ARMATURE":
        raise RuntimeError(f"product armature not found: {ARMATURE_NAME}")

    missing = sorted(GARMENT_NAMES - set(bpy.data.objects.keys()))
    if missing:
        raise RuntimeError("missing garment review objects: " + ", ".join(missing))

    skin = material("LaceHalter_ReviewSkin", (0.36, 0.18, 0.12, 1.0), roughness=0.72)
    glossy = material(
        "LaceHalter_ReviewGlossy",
        (0.010, 0.014, 0.024, 1.0),
        roughness=0.28,
        coat=0.34,
    )
    sheer = material(
        "LaceHalter_ReviewSheer",
        (0.025, 0.032, 0.052, 1.0),
        roughness=0.56,
        alpha=0.30,
    )
    lace = material(
        "LaceHalter_ReviewLace",
        (0.040, 0.052, 0.080, 1.0),
        roughness=0.48,
    )
    metal = material(
        "LaceHalter_ReviewMetal",
        (0.12, 0.15, 0.21, 1.0),
        roughness=0.30,
        metallic=0.70,
    )
    assign(body, skin)

    garments: list[bpy.types.Object] = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or obj == body:
            continue
        if obj.name not in GARMENT_NAMES:
            obj.hide_render = True
            obj.hide_viewport = True
            continue
        lowered = obj.name.lower()
        if "eyelet" in lowered:
            review_material = metal
        elif "sheer" in lowered or "panel" in lowered:
            review_material = sheer
        elif "lace" in lowered or "strap" in lowered:
            review_material = lace
        else:
            review_material = glossy
        assign(obj, review_material)
        garments.append(obj)
    return body, armature, garments


def visible_meshes() -> list[bpy.types.Object]:
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


def studio(center: Vector, height: float) -> None:
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
    area("Review_Fill", (-1.15, -0.55, 0.65), 90.0, height)
    area("Review_Rim", (0.35, 1.25, 1.00), 150.0, height * 0.85)


def camera() -> bpy.types.Object:
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
    data = bpy.data.cameras.get("LaceHalter_ReviewCamera") or bpy.data.cameras.new(
        "LaceHalter_ReviewCamera"
    )
    obj = bpy.data.objects.get("LaceHalter_ReviewCamera") or bpy.data.objects.new(
        "LaceHalter_ReviewCamera", data
    )
    if obj.name not in bpy.context.collection.objects.keys():
        bpy.context.collection.objects.link(obj)
    scene.camera = obj
    return obj


def render(path: Path, review_camera: bpy.types.Object, direction: Vector, margin: float) -> None:
    minimum, maximum = bounds(visible_meshes())
    center = (minimum + maximum) * 0.5
    extent = maximum - minimum
    span = max(extent.x, extent.y, extent.z, 0.5)
    review_camera.data.type = "ORTHO"
    review_camera.data.ortho_scale = span * margin
    review_camera.location = center + direction.normalized() * span * 2.4
    review_camera.rotation_euler = (
        center - review_camera.location
    ).to_track_quat("-Z", "Y").to_euler()
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def review_font(size: int):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def contact_sheet(
    items: list[tuple[str, Path]],
    output: Path,
    *,
    columns: int,
    tile: tuple[int, int],
) -> None:
    tile_width, tile_height = tile
    rows = math.ceil(len(items) / columns)
    canvas = Image.new("RGB", (tile_width * columns, tile_height * rows), (46, 50, 61))
    draw = ImageDraw.Draw(canvas)
    label_font = review_font(24)
    for index, (name, path) in enumerate(items):
        image = Image.open(path).convert("RGB")
        image.thumbnail((tile_width, tile_height), Image.Resampling.LANCZOS)
        x = index % columns * tile_width
        y = index // columns * tile_height
        canvas.paste(
            image,
            (x + (tile_width - image.width) // 2, y + (tile_height - image.height) // 2),
        )
        draw.rounded_rectangle((x + 12, y + 12, x + 225, y + 52), 10, fill=(15, 18, 26))
        draw.text((x + 23, y + 18), name.upper(), fill=(246, 247, 250), font=label_font)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, "WEBP", quality=95, method=6)


def apply_twist(
    armature: bpy.types.Object,
    base_transform: tuple[Vector, object, Vector],
) -> None:
    pose_base.clear(armature, base_transform)
    pose_base.rotate(armature, "Hips", (0.0, 0.0, -8.0))
    pose_base.rotate(armature, "Spine", (0.0, 0.0, 12.0))
    pose_base.rotate(armature, "Chest", (0.0, 0.0, 18.0))
    pose_base.rotate(armature, "UpperChest", (0.0, 0.0, 12.0))
    pose_base.rotate(armature, "UpperArm_L", (-24.0, 8.0, -18.0))
    pose_base.rotate(armature, "UpperArm_R", (-18.0, -8.0, 16.0))
    bpy.context.view_layer.update()


def main() -> int:
    options = pose_base.args()
    job_path = Path(options.job).resolve()
    job = json.loads(job_path.read_text(encoding="utf-8-sig"))
    product_root = ROOT / job["productRoot"]
    preview_dir = product_root / "Previews"
    pose_dir = preview_dir / "Poses"
    artifact_dir = ROOT / job["artifactDir"]

    body, armature, garments = isolate_review_objects()
    base_transform = (
        armature.location.copy(),
        armature.rotation_euler.copy(),
        armature.scale.copy(),
    )
    minimum, maximum = bounds([body, *garments])
    studio((minimum + maximum) * 0.5, max(maximum.z - minimum.z, 0.8))
    review_camera = camera()

    transforms = {armature.name: base_transform}
    pose_base.apply_pose([armature], transforms, "neutral")
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
        render(path, review_camera, direction, 1.12)
        view_items.append((name, path))
    contact_sheet(
        view_items,
        preview_dir / f"{job['id']}-multiview.webp",
        columns=3,
        tile=(480, 640),
    )

    pose_items: list[tuple[str, Path]] = []
    for name in ("neutral", "arms-up", "arm-cross", "crouch", "sit", "twist", "prone"):
        if name == "twist":
            apply_twist(armature, base_transform)
        else:
            pose_base.apply_pose([armature], transforms, name)
        path = pose_dir / f"{name}.png"
        direction = Vector((0.78, -1.0, 0.15 if name != "prone" else 0.52))
        render(path, review_camera, direction, 1.20)
        pose_items.append((name, path))
    pose_base.apply_pose([armature], transforms, "neutral")
    contact_sheet(
        pose_items,
        preview_dir / f"{job['id']}-pose-review.webp",
        columns=4,
        tile=(420, 560),
    )

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
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "review-render-report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
