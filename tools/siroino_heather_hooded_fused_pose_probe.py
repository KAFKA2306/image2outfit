#!/usr/bin/env python3
"""Run the heather hooded pose audit with full-subject framing.

The product-specific sit pose uses the opposite X rotation from the legacy
Siroino pose helper.  Keep this correction at the product adapter boundary so
published evidence is not mirrored or repaired in the Pages layer.
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_heather_hooded_bodysuit_pose as pose
import siroino_heather_hooded_bodysuit_pose_probe as probe

_ORIGINAL_POINT_CAMERA = pose.common.point_camera
_ORIGINAL_APPLY_POSE = pose.apply_pose


def widened_point_camera(camera, location, target) -> None:
    camera.data.ortho_scale *= 1.24
    widened_target = (target[0], target[1], target[2] + 0.075)
    _ORIGINAL_POINT_CAMERA(camera, location, widened_target)


def corrected_apply_pose(armature, base_transform, name: str) -> None:
    if name != "sit":
        _ORIGINAL_APPLY_POSE(armature, base_transform, name)
        return

    pose.clear(armature, base_transform)
    pose.rotate(armature, "UpperLeg_L", (-78.0, 0.0, 4.0))
    pose.rotate(armature, "UpperLeg_R", (-78.0, 0.0, -4.0))
    pose.rotate(armature, "LowerLeg_L", (82.0, 0.0, 0.0))
    pose.rotate(armature, "LowerLeg_R", (82.0, 0.0, 0.0))
    pose.rotate(armature, "Spine", (-9.0, 0.0, 0.0))
    pose.rotate(armature, "Chest", (-7.0, 0.0, 0.0))
    pose.rotate(armature, "UpperArm_L", (-18.0, 0.0, -14.0))
    pose.rotate(armature, "UpperArm_R", (-18.0, 0.0, 14.0))
    hips = armature.pose.bones.get("Hips")
    if hips is not None:
        hips.location.z = -0.17
    pose.bpy.context.view_layer.update()


def main() -> int:
    pose.common.point_camera = widened_point_camera
    pose.apply_pose = corrected_apply_pose
    return probe.main()


if __name__ == "__main__":
    raise SystemExit(main())
