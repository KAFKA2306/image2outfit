#!/usr/bin/env python3
"""Second-pass production refit for Siroino Wide Cargo.

This overlay builds on the v7 entry point but removes the remaining rigid
waist-to-knee tube behavior. The loose upper-leg shell now begins below the hip
joint; body-derived pelvis and side panels carry the waist and hip deformation.
That separation reduces ballooning in crouch/sit poses while preserving the
intentional outer-hip cutouts and detached knee opening.
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


def reweight_v8(obj: bpy.types.Object, side_name: str, upper: bool) -> None:
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
            # The loose thigh starts below the hip joint. Keep the hips share
            # low so the shell does not inflate when both legs flex forward.
            hips_weight = 0.36 * v7.clamp((z - 0.585) / 0.115, 0.0, 1.0)
            weights["Hips"].append((vertex.index, hips_weight))
            weights[upper_bone].append((vertex.index, 1.0 - hips_weight))
        else:
            upper_weight = 0.25 * v7.clamp((z - 0.300) / 0.100, 0.0, 1.0)
            weights[upper_bone].append((vertex.index, upper_weight))
            weights[lower_bone].append((vertex.index, 1.0 - upper_weight))
    v7.replace_vertex_weights(obj, weights)


def fitted_leg_shell_v8(name, side, rings, material, armature, body, segments=48):
    side_name = "L" if side < 0 else "R"
    if "UpperLeg" in name:
        rings = [
            (0.704, 0.014, 0.151, 0.084, 0.081),
            (0.642, 0.016, 0.157, 0.087, 0.084),
            (0.579, 0.019, 0.164, 0.090, 0.087),
            (0.516, 0.023, 0.171, 0.093, 0.090),
            (0.458, 0.028, 0.176, 0.095, 0.093),
        ]
        upper = True
    elif "LowerLeg" in name:
        rings = [
            (0.394, 0.036, 0.176, 0.089, 0.087),
            (0.315, 0.035, 0.185, 0.092, 0.090),
            (0.226, 0.034, 0.197, 0.096, 0.094),
            (0.137, 0.033, 0.210, 0.100, 0.098),
            (0.068, 0.036, 0.223, 0.104, 0.102),
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
    reweight_v8(obj, side_name, upper)
    return obj


def create_outfit_v8(body, armature, fabric, strap, metal):
    v7.tune_material(fabric, base=(0.010, 0.012, 0.018), roughness=0.61)
    v7.tune_material(strap, base=(0.004, 0.005, 0.008), roughness=0.40)
    v7.tune_material(metal, base=(0.24, 0.27, 0.32), roughness=0.22, metallic=0.90)

    objects = v7._original_create_outfit(body, armature, fabric, strap, metal)

    front = build.c.extract_surface(
        body,
        armature,
        "Cargo_Fitted_Front_Pelvis",
        lambda point: (
            0.505 <= point.z <= 0.790
            and point.y < 0.006
            and abs(point.x)
            <= 0.027 + max(0.0, point.z - 0.505) * 0.36
        ),
        fabric,
        0.0045,
    )
    back = build.c.extract_surface(
        body,
        armature,
        "Cargo_Fitted_Back_Yoke",
        lambda point: (
            0.500 <= point.z <= 0.790
            and point.y >= -0.008
            and abs(point.x)
            <= 0.033 + max(0.0, point.z - 0.500) * 0.33
        ),
        fabric,
        0.0045,
    )
    build.finish_skinned(front, body)
    build.finish_skinned(back, body)

    fitted_panels: list[bpy.types.Object] = [front, back]
    for side_name, sign in (("L", -1.0), ("R", 1.0)):
        panel = build.c.extract_surface(
            body,
            armature,
            f"Cargo_Fitted_Hip_{side_name}",
            lambda point, sign=sign: (
                0.545 <= point.z <= 0.790
                and 0.032 <= sign * point.x <= 0.146
                and not (
                    point.z >= 0.704
                    and sign * point.x >= 0.104
                    and abs(point.y) <= 0.090
                )
            ),
            fabric,
            0.0048,
        )
        build.finish_skinned(panel, body)
        fitted_panels.append(panel)

    return [*fitted_panels, *objects]


# Importing v7 has already installed its UV, belt, pocket, buckle, material and
# distribution-safety overrides. Replace only the two remaining deformation
# decisions for this iteration.
build.asymmetric_leg_shell = fitted_leg_shell_v8
build.create_outfit = create_outfit_v8

if __name__ == "__main__":
    exit_code = build.main()
    if exit_code == 0:
        v7.save_distribution_blend()
    raise SystemExit(exit_code)
