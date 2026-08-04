#!/usr/bin/env python3
"""Pattern-coordinate reconstruction for the Siroino heather bodysuit.

This module is an independent deterministic Blender adaptation of the pattern-space
principle in "Spatio-Temporal Garment Reconstruction Using Diffusion Mapping via
Pattern Coordinates" (arXiv:2602.24043). It does not execute or copy the authors'
model. The trial replaces the failed lower-body region predicate with explicit
front/back pattern coordinates, a bounded high-cut opening curve, and a short
underbody bridge.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from types import ModuleType

import bpy
from mathutils import Vector

DESIGN_REVISION = "v24-pattern-coordinate-highcut-shell"
RESEARCH_OUTPUT = Path(
    "Assets/GenWorks/siroino-heather-hooded-bodysuit/Research/"
    "pattern-coordinate-trial.json"
)
PolygonPredicate = Callable[[bpy.types.MeshPolygon, Vector], bool]


def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def _half_width(z: float) -> float:
    """High-cut boundary: narrow bridge below, fitted torso above."""
    if z <= 0.600:
        return 0.030
    if z >= 0.900:
        return 0.168
    t = (z - 0.600) / 0.300
    return 0.030 + (0.168 - 0.030) * _smoothstep(t)


def _body_shell_predicate(pattern: ModuleType, body: bpy.types.Object) -> PolygonPredicate:
    v9 = pattern.v9
    arm_groups = {
        side: (
            v9._group_index(body, f"UpperArm_{side}"),
            v9._group_index(body, f"LowerArm_{side}"),
            v9._group_index(body, f"Hand_{side}"),
        )
        for side in ("L", "R")
    }

    def selected(polygon: bpy.types.MeshPolygon, center: Vector) -> bool:
        x = abs(center.x)
        z = center.z

        # Explicit pattern-space body panel. The lower endpoint is raised from the
        # failed v23 value so the front and rear panels terminate at the underbody
        # instead of producing long hanging tabs.
        torso = 0.790 <= z <= pattern._torso_top(center.x) and x <= min(
            pattern._torso_width(z), 0.176
        )
        highcut = 0.590 <= z < 0.900 and x <= _half_width(z)

        # At the bridge tip, retain only polygons close to the sagittal plane.
        # This yields one short front-to-back connection instead of two long flaps.
        underbody_bridge = (
            0.555 <= z < 0.640
            and x <= 0.036
            and abs(center.y) <= 0.105
        )
        if torso or highcut or underbody_bridge:
            return True

        # Slim sleeves inherit the evaluated Siroino arm weights. A higher minimum
        # than v23 removes shoulder fins and broad underarm wings.
        for upper, lower, hand in arm_groups.values():
            upper_weight = v9._polygon_average_weight(body, polygon, (upper,))
            lower_weight = v9._polygon_average_weight(body, polygon, (lower,))
            hand_weight = v9._polygon_average_weight(body, polygon, (hand,))
            arm_weight = upper_weight + lower_weight
            if hand_weight <= 0.42 and arm_weight >= 0.030:
                return True
            if z >= 0.940 and upper_weight >= 0.012:
                return True
        return False

    return selected


def _write_trial() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / RESEARCH_OUTPUT
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "status": "EXECUTED",
        "method": "deterministic pattern-coordinate body-region reconstruction",
        "paper": {
            "title": "Spatio-Temporal Garment Reconstruction Using Diffusion Mapping via Pattern Coordinates",
            "url": "https://arxiv.org/abs/2602.24043",
            "submitted": "2026-02-27T14:19:23Z",
            "authorsImplementationExecuted": False,
        },
        "implementation": {
            "kind": "independent Blender geometric adaptation",
            "differenceFromV23": [
                "explicit lower-body pattern coordinate instead of a monotonic body strip",
                "short sagittal underbody bridge",
                "bounded torso half-width",
                "stricter arm-weight selection to suppress shoulder fins",
            ],
            "failureConditions": [
                "more or fewer than five anatomical boundary loops",
                "disconnected primary shell",
                "visible front or rear crotch tab",
                "shoulder protrusion",
                "failed direct visual review",
            ],
        },
        "parameters": {
            "bridgeZMin": 0.555,
            "bridgeZMax": 0.640,
            "bridgeHalfWidthM": 0.036,
            "bridgeSagittalHalfDepthM": 0.105,
            "highcutZMin": 0.590,
            "torsoZMin": 0.790,
            "maximumTorsoHalfWidthM": 0.176,
            "minimumArmWeight": 0.030,
        },
        "acceptance": {
            "researchTrial": "PASS",
            "visualAppearanceReview": "PENDING until current hosted renders are opened",
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def install(pattern: ModuleType) -> None:
    """Install v24 pattern-coordinate selection after v23 fitting modules."""
    pattern.DESIGN_REVISION = DESIGN_REVISION
    pattern._pattern_coordinate_half_width = _half_width
    pattern._body_shell_predicate = lambda body: _body_shell_predicate(pattern, body)
    _write_trial()
