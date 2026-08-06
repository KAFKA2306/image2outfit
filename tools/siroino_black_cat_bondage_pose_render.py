#!/usr/bin/env python3
"""Render the six required deformation poses for siroino-black-cat-bondage."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import bpy
from mathutils import Euler, Vector
from PIL import Image, ImageDraw, ImageFont

PRODUCT_ID = "siroino-black-cat-bondage"
ROOT = Path.cwd().resolve()


def parse_args() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    return parser.parse_args(values)


def repo_path(value: str) -> Path:
    return (ROOT / value).resolve()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_armature() -> bpy.types.Object:
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if not armatures:
        raise RuntimeError("No armature exists in the generated blend")
    return next((obj for obj in armatures if "Siroino" in obj.name), armatures[0])


def reset_pose(armature: bpy.types.Object, base: tuple[Vector, Euler, Vector]) -> None:
    location, rotation, scale = base
    armature.location = location.copy()
    armature.rotation_mode = "XYZ"
    armature.rotation_euler = rotation.copy()
    armature.scale = scale.copy()
    for bone in armature.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0.0, 0.0, 0.0)
        bone.location = (0.0, 0.0, 0.0)
        bone.scale = (1.0, 1.0, 1.0)


def rotate(armature: bpy.types.Object, name: str, degrees: tuple[float, float, float]) -> None:
    bone = armature.pose.bones.get(name)
    if bone is None:
        return
    bone.rotation_mode = "XYZ"
    bone.rotation_euler = tuple(math.radians(value) for value in degrees)


def apply_pose(armature: bpy.types.Object, base: tuple[Vector, Euler, Vector], name: str) -> None:
    reset_pose(armature, base)
    if name == "arms-up":
        rotate(armature, "UpperArm_L", (-100.0, 0.0, -8.0))
        rotate(armature, "UpperArm_R", (-100.0, 0.0, 8.0))
        rotate(armature, "LowerArm_L", (-12.0, 0.0, 0.0))
        rotate(armature, "LowerArm_R", (-12.0, 0.0, 0.0))
    elif name == "arm-cross":
        rotate(armature, "UpperArm_L", (-38.0, 18.0, -54.0))
        rotate(armature, "UpperArm_R", (-38.0, -18.0, 54.0))
        rotate(armature, "LowerArm_L", (-86.0, 0.0, 20.0))
        rotate(armature, "LowerArm_R", (-86.0, 0.0, -20.0))
    elif name == "crouch":
        rotate(armature, "UpperLeg_L", (48.0, 0.0, 6.0))
        rotate(armature, "UpperLeg_R", (48.0, 0.0, -6.0))
        rotate(armature, "LowerLeg_L", (-72.0, 0.0, 0.0))
        rotate(armature, "LowerLeg_R", (-72.0, 0.0, 0.0))
        hips = armature.pose.bones.get("Hips")
        if hips is not None:
            hips.location.z = -0.10
    elif name == "sit":
        rotate(armature, "UpperLeg_L", (65.0, 0.0, 2.0))
        rotate(armature, "UpperLeg_R", (65.0, 0.0, -2.0))
        rotate(armature, "LowerLeg_L", (-65.0, 0.0, 0.0))
        rotate(armature, "LowerLeg_R", (-65.0, 0.0, 0.0))
        hips = armature.pose.bones.get("Hips")
        if hips is not None:
            hips.location.z = -0.16
    elif name == "prone":
        armature.rotation_euler.rotate_axis("X", math.radians(90.0))
        armature.location.y += 0.10
        armature.location.z += 0.16
        rotate(armature, "UpperLeg_L", (-10.0, 0.0, 3.0))
        rotate(armature, "UpperLeg_R", (-10.0, 0.0, -3.0))
        rotate(armature, "LowerLeg_L", (20.0, 0.0, 0.0))
        rotate(armature, "LowerLeg_R", (20.0, 0.0, 0.0))
        rotate(armature, "UpperArm_L", (-34.0, 0.0, -18.0))
        rotate(armature, "UpperArm_R", (-34.0, 0.0, 18.0))
        rotate(armature, "LowerArm_L", (-48.0, 0.0, 0.0))
        rotate(armature, "LowerArm_R", (-48.0, 0.0, 0.0))
    bpy.context.view_layer.update()


def point_camera(camera: bpy.types.Object, location: tuple[float, float, float], target: tuple[float, float, float]) -> None:
    camera.location = location
    camera.rotation_euler = (Vector(target) - camera.location).to_track_quat("-Z", "Y").to_euler()


def resolve_camera() -> bpy.types.Object:
    cameras = [obj for obj in bpy.context.scene.objects if obj.type == "CAMERA"]
    camera = next((obj for obj in cameras if obj.name == "BCB_Render_Camera"), None)
    if camera is None:
        bpy.ops.object.camera_add()
        camera = bpy.context.object
    camera.data.type = "ORTHO"
    bpy.context.scene.camera = camera
    return camera


def contact_sheet(paths: dict[str, Path], output: Path) -> None:
    tile = 512
    canvas = Image.new("RGB", (tile * 3, tile * 2), (20, 22, 30))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 24)
    except OSError:
        font = ImageFont.load_default()
    for index, (name, image_path) in enumerate(paths.items()):
        image = Image.open(image_path).convert("RGB")
        image.thumbnail((tile, tile), Image.Resampling.LANCZOS)
        x = index % 3 * tile
        y = index // 3 * tile
        canvas.paste(image, (x + (tile - image.width) // 2, y))
        draw.rounded_rectangle((x + 16, y + 16, x + 220, y + 52), 10, fill=(8, 10, 16))
        draw.text((x + 26, y + 20), name.upper(), fill=(245, 245, 248), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, "WEBP", quality=92, method=6)


def main() -> int:
    job = json.loads(repo_path(parse_args().job).read_text(encoding="utf-8-sig"))
    if job.get("id") != PRODUCT_ID:
        raise RuntimeError(f"job id must be {PRODUCT_ID}")
    armature = resolve_armature()
    camera = resolve_camera()
    base = (armature.location.copy(), armature.rotation_euler.copy(), armature.scale.copy())
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 768
    scene.render.resolution_y = 768
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.view_settings.look = "AgX - Medium High Contrast"
    settings = {
        "neutral": ((2.15, -2.15, 1.02), (0.0, 0.0, 0.82), 1.62),
        "arms-up": ((2.15, -2.15, 1.10), (0.0, 0.0, 0.88), 1.78),
        "arm-cross": ((2.15, -2.15, 1.02), (0.0, 0.0, 0.82), 1.62),
        "crouch": ((2.20, -2.20, 0.74), (0.0, 0.0, 0.62), 1.45),
        "sit": ((2.20, -2.20, 0.70), (0.0, 0.0, 0.58), 1.45),
        "prone": ((2.30, -0.65, 0.85), (0.0, -0.32, 0.30), 1.55),
    }
    generated: dict[str, Path] = {}
    for name in ("neutral", "arms-up", "arm-cross", "crouch", "sit", "prone"):
        apply_pose(armature, base, name)
        location, target, scale = settings[name]
        camera.data.ortho_scale = scale
        point_camera(camera, location, target)
        output = repo_path(job["posePaths"][name])
        output.parent.mkdir(parents=True, exist_ok=True)
        scene.render.filepath = str(output)
        bpy.ops.render.render(write_still=True)
        generated[name] = output
    apply_pose(armature, base, "neutral")
    sheet = repo_path(job["productRoot"]) / "Previews" / "siroino-black-cat-bondage-pose-review.webp"
    contact_sheet(generated, sheet)
    bpy.ops.wm.save_as_mainfile(filepath=str(repo_path(job["blendPath"])))
    garment_meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.get("productId") == PRODUCT_ID]
    missing_modifiers = [obj.name for obj in garment_meshes if not any(mod.type == "ARMATURE" for mod in obj.modifiers)]
    missing_weights = [obj.name for obj in garment_meshes if not obj.vertex_groups]
    report = {
        "schemaVersion": 1,
        "productId": PRODUCT_ID,
        "passed": not missing_modifiers and not missing_weights and len(generated) == 6,
        "technicalOnly": True,
        "armature": armature.name,
        "garmentMeshCount": len(garment_meshes),
        "missingArmatureModifier": missing_modifiers,
        "missingVertexGroups": missing_weights,
        "poses": {name: str(path.relative_to(ROOT)) for name, path in generated.items()},
        "contactSheet": str(sheet.relative_to(ROOT)),
        "directImageReviewRequired": True,
    }
    write_json(repo_path(job["productRoot"]) / "Evidence" / "Build" / "pose-audit.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
