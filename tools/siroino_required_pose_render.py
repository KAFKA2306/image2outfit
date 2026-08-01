#!/usr/bin/env python3
"""Render the six release-policy poses from the generated cargo blend."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from PIL import Image, ImageDraw, ImageFont

import siroino_strappy_knit_build as common

ROOT = Path(__file__).resolve().parents[1]


def args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    return parser.parse_args(raw)


def clear(armature: bpy.types.Object) -> None:
    for bone in armature.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0.0, 0.0, 0.0)
        bone.location = (0.0, 0.0, 0.0)
        bone.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()


def rotate(armature: bpy.types.Object, name: str, degrees: tuple[float, float, float]) -> None:
    bone = armature.pose.bones.get(name)
    if bone is not None:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = tuple(math.radians(value) for value in degrees)


def apply_pose(armature: bpy.types.Object, name: str) -> None:
    clear(armature)
    if name == "arms-up":
        rotate(armature, "UpperArm_L", (-105.0, 0.0, -8.0))
        rotate(armature, "UpperArm_R", (-105.0, 0.0, 8.0))
        rotate(armature, "LowerArm_L", (-8.0, 0.0, 0.0))
        rotate(armature, "LowerArm_R", (-8.0, 0.0, 0.0))
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
        if armature.pose.bones.get("Hips"):
            armature.pose.bones["Hips"].location.z = -0.10
    elif name == "sit":
        rotate(armature, "UpperLeg_L", (65.0, 0.0, 2.0))
        rotate(armature, "UpperLeg_R", (65.0, 0.0, -2.0))
        rotate(armature, "LowerLeg_L", (-65.0, 0.0, 0.0))
        rotate(armature, "LowerLeg_R", (-65.0, 0.0, 0.0))
        if armature.pose.bones.get("Hips"):
            armature.pose.bones["Hips"].location.z = -0.16
    elif name == "prone":
        rotate(armature, "UpperLeg_L", (-18.0, 0.0, 3.0))
        rotate(armature, "UpperLeg_R", (-18.0, 0.0, -3.0))
        rotate(armature, "LowerLeg_L", (24.0, 0.0, 0.0))
        rotate(armature, "LowerLeg_R", (24.0, 0.0, 0.0))
    bpy.context.view_layer.update()


def sheet(paths: dict[str, Path], output: Path) -> None:
    tile = 600
    canvas = Image.new("RGB", (tile * 3, tile * 2), (26, 29, 38))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 30)
    except OSError:
        font = ImageFont.load_default()
    for index, (name, path) in enumerate(paths.items()):
        image = Image.open(path).convert("RGB")
        image.thumbnail((tile, tile), Image.Resampling.LANCZOS)
        x = index % 3 * tile
        y = index // 3 * tile
        canvas.paste(image, (x + (tile - image.width) // 2, y))
        draw.rounded_rectangle((x + 18, y + 18, x + 260, y + 62), 14, fill=(15, 18, 25))
        draw.text((x + 30, y + 24), name.upper(), fill=(245, 245, 248), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, "WEBP", quality=94, method=6)


def main() -> int:
    options = args()
    job = json.loads(Path(options.job).read_text(encoding="utf-8-sig"))
    root = ROOT / job["productRoot"]
    pose_dir = root / "Previews" / "Poses"
    pose_dir.mkdir(parents=True, exist_ok=True)
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    _, camera = common.studio_setup()
    camera.data.ortho_scale = 1.23
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 28
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 1200
    scene.render.resolution_y = 1200
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.look = "AgX - Medium High Contrast"

    paths: dict[str, Path] = {}
    for name in ("neutral", "arms-up", "arm-cross", "crouch", "sit", "prone"):
        apply_pose(armature, name)
        path = pose_dir / f"{name}.png"
        location = (1.72, -2.05, 0.46) if name in ("sit", "crouch") else (1.62, -1.90, 0.64)
        common.point_camera(camera, location, (0.0, 0.0, 0.40))
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        paths[name] = path
    clear(armature)
    sheet(paths, root / "Previews" / "siroino-wide-cargo-pose-review.webp")
    print(json.dumps({"passed": True, "poses": {name: str(path) for name, path in paths.items()}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
