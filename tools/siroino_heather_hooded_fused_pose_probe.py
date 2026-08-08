#!/usr/bin/env python3
"""Run the v28 pose audit with full-subject camera framing."""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_heather_hooded_bodysuit_pose as pose
import siroino_heather_hooded_bodysuit_pose_probe as probe

_ORIGINAL_POINT_CAMERA = pose.common.point_camera


def widened_point_camera(camera, location, target) -> None:
    camera.data.ortho_scale *= 1.24
    widened_target = (target[0], target[1], target[2] + 0.075)
    _ORIGINAL_POINT_CAMERA(camera, location, widened_target)


def main() -> int:
    pose.common.point_camera = widened_point_camera
    return probe.main()


if __name__ == "__main__":
    raise SystemExit(main())
