#!/usr/bin/env python3
"""Render deterministic verification poses from the generated military romper Blend."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "siroino-military-sheer-romper-large"
POSES = ("neutral", "arms-up", "arm-cross", "crouch", "sit", "twist", "prone")


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    return parser.parse_args(raw)


def repo_path(value: str) -> Path:
    path = (ROOT / value).resolve()
    if path != ROOT and ROOT not in path.parents:
        raise ValueError(f"path escapes repository: {value}")
    return path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def look_at(obj: bpy.types.Object, target=(0, 0, 0.79)) -> None:
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def reset_pose(armature: bpy.types.Object) -> None:
    for bone in armature.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0, 0, 0)
        bone.location = (0, 0, 0)
        bone.scale = (1, 1, 1)


def rotate(armature: bpy.types.Object, name: str, values) -> None:
    bone = armature.pose.bones.get(name)
    if bone is None:
        raise KeyError(f"pose bone missing: {name}")
    bone.rotation_mode = "XYZ"
    bone.rotation_euler = values


def apply_pose(armature: bpy.types.Object, name: str) -> None:
    reset_pose(armature)
    if name == "arms-up":
        rotate(armature, "UpperArm_L.1", (0.0, -0.15, 1.36))
        rotate(armature, "UpperArm_R.1", (0.0, 0.15, -1.36))
    elif name == "arm-cross":
        rotate(armature, "UpperArm_L.1", (-0.15, 0.58, 0.48))
        rotate(armature, "UpperArm_R.1", (-0.15, -0.58, -0.48))
        rotate(armature, "LowerArm_L.1", (0.0, -0.85, -0.32))
        rotate(armature, "LowerArm_R.1", (0.0, 0.85, 0.32))
    elif name == "crouch":
        rotate(armature, "Hips.1", (0.20, 0.0, 0.0))
        rotate(armature, "UpperLeg_L.1", (0.92, 0.0, 0.04))
        rotate(armature, "UpperLeg_R.1", (0.92, 0.0, -0.04))
        rotate(armature, "LowerLeg_L.1", (-1.28, 0.0, 0.0))
        rotate(armature, "LowerLeg_R.1", (-1.28, 0.0, 0.0))
    elif name == "sit":
        rotate(armature, "Hips.1", (0.10, 0.0, 0.0))
        rotate(armature, "UpperLeg_L.1", (1.38, 0.0, 0.02))
        rotate(armature, "UpperLeg_R.1", (1.38, 0.0, -0.02))
        rotate(armature, "LowerLeg_L.1", (-1.34, 0.0, 0.0))
        rotate(armature, "LowerLeg_R.1", (-1.34, 0.0, 0.0))
    elif name == "twist":
        rotate(armature, "Spine.1", (0.0, 0.0, 0.26))
        rotate(armature, "Chest.1", (0.0, 0.0, 0.36))
        rotate(armature, "UpperArm_L.1", (0.0, 0.0, 0.35))
        rotate(armature, "UpperArm_R.1", (0.0, 0.0, -0.28))
    elif name == "prone":
        rotate(armature, "Hips.1", (0.0, math.pi / 2.0, 0.0))
        rotate(armature, "UpperArm_L.1", (0.0, -0.20, 0.72))
        rotate(armature, "UpperArm_R.1", (0.0, 0.20, -0.72))
        rotate(armature, "UpperLeg_L.1", (-0.12, 0.0, 0.03))
        rotate(armature, "UpperLeg_R.1", (-0.12, 0.0, -0.03))
    bpy.context.view_layer.update()


def compose(paths: dict[str, Path], output: Path) -> None:
    cell = (350, 350)
    canvas = Image.new("RGB", (cell[0] * 4, cell[1] * 2), (238, 239, 242))
    draw = ImageDraw.Draw(canvas)
    for index, name in enumerate(POSES):
        image = Image.open(paths[name]).convert("RGB")
        image.thumbnail(cell, Image.Resampling.LANCZOS)
        x0 = (index % 4) * cell[0]
        y0 = (index // 4) * cell[1]
        canvas.paste(image, (x0 + (cell[0] - image.width) // 2, y0 + (cell[1] - image.height) // 2))
        draw.text((x0 + 10, y0 + 10), name, fill=(34, 36, 42))
    canvas.save(output, "WEBP", quality=92, method=6)


def update_hashes(product_root: Path) -> None:
    lines = []
    for path in sorted(product_root.rglob("*")):
        if path.is_file() and path.name != "SOURCE_HASHES.txt":
            lines.append(f"{sha256(path)}  {path.relative_to(product_root).as_posix()}")
    (product_root / "SOURCE_HASHES.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parsed = parse_args()
    job = json.loads(Path(parsed.job).read_text(encoding="utf-8-sig"))
    if job.get("id") != PRODUCT_ID:
        raise ValueError(f"unexpected product job: {job.get('id')!r}")
    armature = bpy.data.objects.get("Armature.1")
    camera = bpy.data.objects.get("ReviewCamera")
    if armature is None or armature.type != "ARMATURE":
        raise RuntimeError("generated garment armature not found")
    if camera is None or camera.type != "CAMERA":
        raise RuntimeError("review camera not found")
    product_root = repo_path(job["productRoot"])
    pose_dir = product_root / "Previews" / "Poses"
    pose_dir.mkdir(parents=True, exist_ok=True)
    camera.location = (2.15, -2.25, 0.88)
    look_at(camera)
    paths = {}
    for name in POSES:
        apply_pose(armature, name)
        path = pose_dir / f"{name}.png"
        bpy.context.scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        paths[name] = path
    reset_pose(armature)
    bpy.context.view_layer.update()
    output = product_root / "Previews" / f"{PRODUCT_ID}-pose-review.webp"
    compose(paths, output)
    bpy.ops.wm.save_as_mainfile(filepath=str(repo_path(job["blendPath"])), compress=True)
    update_hashes(product_root)
    print(json.dumps({"productId": PRODUCT_ID, "poses": list(POSES), "poseReview": output.relative_to(ROOT).as_posix()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
