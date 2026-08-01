#!/usr/bin/env python3
"""Third-pass Siroino Wide Cargo refit focused on pose stability.

The prior second pass proved that body-derived outer-hip panels created visible
surface holes without reducing crouch inflation enough. This revision removes
those panels, keeps only the continuous fitted front/back pelvis pieces, and
uses a much smaller loose thigh shell with a deliberate inner-leg gap. The wide
visual mass is concentrated below the knee, where it can follow the lower-leg
bones without collapsing the hip silhouette during crouch and sit poses.
"""
from __future__ import annotations

import sys
from pathlib import Path

import bpy

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_build as build
import siroino_wide_cargo_entry as v7


def reweight_v9(obj: bpy.types.Object, side_name: str, upper: bool) -> None:
    upper_bone = f"UpperLeg_{side_name}"
    lower_bone = f"LowerLeg_{side_name}"
    weights: dict[str, list[tuple[int, float]]] = {
        "Hips": [],
        upper_bone: [],
        lower_bone: [],
    }
    for vertex in obj.data.vertices:
        z = vertex.co.z
        if upper:
            hips_weight = 0.22 * v7.clamp((z - 0.610) / 0.095, 0.0, 1.0)
            weights["Hips"].append((vertex.index, hips_weight))
            weights[upper_bone].append((vertex.index, 1.0 - hips_weight))
        else:
            upper_weight = 0.22 * v7.clamp((z - 0.305) / 0.090, 0.0, 1.0)
            weights[upper_bone].append((vertex.index, upper_weight))
            weights[lower_bone].append((vertex.index, 1.0 - upper_weight))
    v7.replace_vertex_weights(obj, weights)


def fitted_leg_shell_v9(name, side, rings, material, armature, body, segments=48):
    side_name = "L" if side < 0 else "R"
    if "UpperLeg" in name:
        rings = [
            (0.704, 0.025, 0.139, 0.071, 0.069),
            (0.642, 0.027, 0.143, 0.073, 0.071),
            (0.579, 0.029, 0.148, 0.076, 0.074),
            (0.516, 0.031, 0.153, 0.080, 0.078),
            (0.458, 0.034, 0.158, 0.084, 0.082),
        ]
        upper = True
    elif "LowerLeg" in name:
        rings = [
            (0.394, 0.038, 0.172, 0.086, 0.084),
            (0.315, 0.037, 0.182, 0.090, 0.088),
            (0.226, 0.036, 0.195, 0.094, 0.092),
            (0.137, 0.035, 0.208, 0.098, 0.096),
            (0.070, 0.038, 0.221, 0.102, 0.100),
        ]
        upper = False
    else:
        upper = False

    obj = v7._original_asymmetric_leg_shell(
        name,
        side,
        rings,
        material,
        armature,
        body,
        segments=segments,
    )
    reweight_v9(obj, side_name, upper)
    return obj


def create_outfit_v9(body, armature, fabric, strap, metal):
    v7.tune_material(fabric, base=(0.009, 0.011, 0.017), roughness=0.60)
    v7.tune_material(strap, base=(0.003, 0.004, 0.007), roughness=0.39)
    v7.tune_material(metal, base=(0.25, 0.28, 0.34), roughness=0.21, metallic=0.91)

    objects = v7._original_create_outfit(body, armature, fabric, strap, metal)

    front = build.c.extract_surface(
        body,
        armature,
        "Cargo_Fitted_Front_Pelvis",
        lambda point: (
            0.500 <= point.z <= 0.790
            and point.y < 0.007
            and abs(point.x)
            <= 0.029 + max(0.0, point.z - 0.500) * 0.39
        ),
        fabric,
        0.0046,
    )
    back = build.c.extract_surface(
        body,
        armature,
        "Cargo_Fitted_Back_Yoke",
        lambda point: (
            0.495 <= point.z <= 0.790
            and point.y >= -0.009
            and abs(point.x)
            <= 0.035 + max(0.0, point.z - 0.495) * 0.35
        ),
        fabric,
        0.0046,
    )
    build.finish_skinned(front, body)
    build.finish_skinned(back, body)
    return [front, back, *objects]


build.asymmetric_leg_shell = fitted_leg_shell_v9
build.create_outfit = create_outfit_v9

if __name__ == "__main__":
    exit_code = build.main()
    if exit_code == 0:
        v7.save_distribution_blend()
    raise SystemExit(exit_code)
