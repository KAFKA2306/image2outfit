#!/usr/bin/env python3
"""Render the required SiroinoSotai_PC fit-pose suite for the hooded bodysuit."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Euler, Vector

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_required_pose_render as generic
import siroino_strappy_knit_build as common

ROOT = Path(__file__).resolve().parents[1]
POSES = ("neutral", "arms-up", "forward-bend", "legs-apart", "walk", "crouch")


def args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    return parser.parse_args(raw)


def rotate(armature: bpy.types.Object, name: str, degrees: tuple[float, float, float]) -> None:
    bone = armature.pose.bones.get(name)
    if bone is None:
        raise RuntimeError(f"Required Siroino pose bone missing: {name}")
    bone.rotation_mode = "XYZ"
    bone.rotation_euler = tuple(math.radians(value) for value in degrees)


def clear(
    armature: bpy.types.Object,
    base_transform: tuple[Vector, Euler, Vector],
) -> None:
    location, rotation, scale = base_transform
    armature.location = location.copy()
    armature.rotation_mode = "XYZ"
    armature.rotation_euler = rotation.copy()
    armature.scale = scale.copy()
    for bone in armature.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0.0, 0.0, 0.0)
        bone.location = (0.0, 0.0, 0.0)
        bone.scale = (1.0, 1.0, 1.0)


def apply_pose(
    armature: bpy.types.Object,
    base_transform: tuple[Vector, Euler, Vector],
    name: str,
) -> None:
    clear(armature, base_transform)
    if name == "arms-up":
        rotate(armature, "UpperArm_L", (-112.0, 0.0, -8.0))
        rotate(armature, "UpperArm_R", (-112.0, 0.0, 8.0))
        rotate(armature, "LowerArm_L", (-7.0, 0.0, 0.0))
        rotate(armature, "LowerArm_R", (-7.0, 0.0, 0.0))
    elif name == "forward-bend":
        rotate(armature, "Spine", (28.0, 0.0, 0.0))
        rotate(armature, "Chest", (24.0, 0.0, 0.0))
        rotate(armature, "UpperLeg_L", (-8.0, 0.0, 0.0))
        rotate(armature, "UpperLeg_R", (-8.0, 0.0, 0.0))
        rotate(armature, "UpperArm_L", (-18.0, 0.0, -10.0))
        rotate(armature, "UpperArm_R", (-18.0, 0.0, 10.0))
    elif name == "legs-apart":
        rotate(armature, "UpperLeg_L", (0.0, 0.0, 25.0))
        rotate(armature, "UpperLeg_R", (0.0, 0.0, -25.0))
        rotate(armature, "LowerLeg_L", (-8.0, 0.0, 0.0))
        rotate(armature, "LowerLeg_R", (-8.0, 0.0, 0.0))
        rotate(armature, "UpperArm_L", (-18.0, 0.0, -14.0))
        rotate(armature, "UpperArm_R", (-18.0, 0.0, 14.0))
    elif name == "walk":
        rotate(armature, "UpperLeg_L", (30.0, 0.0, 1.0))
        rotate(armature, "LowerLeg_L", (-42.0, 0.0, 0.0))
        rotate(armature, "UpperLeg_R", (-24.0, 0.0, -1.0))
        rotate(armature, "LowerLeg_R", (12.0, 0.0, 0.0))
        rotate(armature, "UpperArm_L", (-30.0, 0.0, -5.0))
        rotate(armature, "UpperArm_R", (25.0, 0.0, 5.0))
        rotate(armature, "LowerArm_L", (-18.0, 0.0, 0.0))
        rotate(armature, "LowerArm_R", (-28.0, 0.0, 0.0))
    elif name == "crouch":
        rotate(armature, "UpperLeg_L", (48.0, 0.0, 7.0))
        rotate(armature, "UpperLeg_R", (48.0, 0.0, -7.0))
        rotate(armature, "LowerLeg_L", (-72.0, 0.0, 0.0))
        rotate(armature, "LowerLeg_R", (-72.0, 0.0, 0.0))
        rotate(armature, "Spine", (12.0, 0.0, 0.0))
        hips = armature.pose.bones.get("Hips")
        if hips is not None:
            hips.location.z = -0.10
    bpy.context.view_layer.update()


def main() -> int:
    options = args()
    job = json.loads(Path(options.job).read_text(encoding="utf-8-sig"))
    root = ROOT / job["productRoot"]
    pose_dir = root / "Previews" / "Poses"
    pose_dir.mkdir(parents=True, exist_ok=True)

    body = next(
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.name.startswith("SiroinoSotai_PC")
    )
    armature = next(
        obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"
    )
    body.hide_render = False
    common.set_skin_material(body)
    base_transform = (
        armature.location.copy(),
        armature.rotation_euler.copy(),
        armature.scale.copy(),
    )

    _, camera = common.studio_setup()
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

    camera_settings = {
        "neutral": ((1.62, -1.90, 0.64), (0.0, 0.0, 0.40), 1.23),
        "arms-up": ((1.62, -1.90, 0.68), (0.0, 0.0, 0.44), 1.30),
        "forward-bend": ((1.65, -1.96, 0.62), (0.0, 0.0, 0.39), 1.30),
        "legs-apart": ((1.68, -1.98, 0.55), (0.0, 0.0, 0.34), 1.34),
        "walk": ((1.66, -1.98, 0.57), (0.0, 0.0, 0.35), 1.31),
        "crouch": ((1.72, -2.05, 0.46), (0.0, 0.0, 0.31), 1.28),
    }

    paths: dict[str, Path] = {}
    for name in POSES:
        apply_pose(armature, base_transform, name)
        path = pose_dir / f"{name}.png"
        location, target, ortho_scale = camera_settings[name]
        camera.data.ortho_scale = ortho_scale
        common.point_camera(camera, location, target)
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        paths[name] = path
    apply_pose(armature, base_transform, "neutral")
    output = root / "Previews" / f"{job['id']}-pose-review.webp"
    generic.sheet(paths, output)
    print(
        json.dumps(
            {
                "passed": all(path.is_file() for path in paths.values()),
                "targetSource": job["targetSourcePath"],
                "targetBody": body.name,
                "poses": {name: str(path) for name, path in paths.items()},
                "sheet": str(output),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
