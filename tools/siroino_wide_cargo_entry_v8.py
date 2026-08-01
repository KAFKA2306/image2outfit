#!/usr/bin/env python3
"""Third-pass production refit for Siroino Wide Cargo.

The fitted pelvis carries hip deformation. Loose shells begin below the hip and
use deterministic single-leg weights so crouch and sit poses cannot balloon or
cross-couple. Lower legs retain a wide silhouette without a cone profile, and
all hems remain clear of the floor in the exact Siroino reference pose.
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


_original_band = v7._original_flat_ellipse_band


def reweight_v9(obj: bpy.types.Object, side_name: str, upper: bool) -> None:
    """Bind each detached shell to its anatomical leg only.

    Detached wide shells do not need a Hips blend. A hips share caused the
    previous crouch/sit inflation because the shell was transformed by both the
    pelvis and flexed leg. The knee gap is intentional, so a hard anatomical
    handoff is visually safer and deterministic.
    """
    upper_bone = f"UpperLeg_{side_name}"
    lower_bone = f"LowerLeg_{side_name}"
    target = upper_bone if upper else lower_bone
    v7.replace_vertex_weights(
        obj,
        {
            "Hips": [],
            upper_bone: [(vertex.index, 1.0) for vertex in obj.data.vertices]
            if upper
            else [],
            lower_bone: [(vertex.index, 1.0) for vertex in obj.data.vertices]
            if not upper
            else [],
        },
    )


def fitted_leg_shell_v9(name, side, rings, material, armature, body, segments=48):
    side_name = "L" if side < 0 else "R"
    if "UpperLeg" in name:
        # Compact thigh shell: fitted pelvis above, loose cargo volume below.
        rings = [
            (0.665, 0.018, 0.142, 0.073, 0.071),
            (0.610, 0.020, 0.146, 0.075, 0.073),
            (0.555, 0.022, 0.151, 0.077, 0.075),
            (0.505, 0.025, 0.155, 0.079, 0.077),
            (0.460, 0.029, 0.158, 0.080, 0.079),
        ]
        upper = True
    elif "LowerLeg" in name:
        # Near-parallel wide leg, not a flared cone. The 95 mm hem height
        # leaves visible shoe and floor clearance in the source coordinate set.
        rings = [
            (0.392, 0.038, 0.171, 0.082, 0.080),
            (0.318, 0.038, 0.174, 0.083, 0.081),
            (0.242, 0.038, 0.178, 0.084, 0.082),
            (0.168, 0.039, 0.182, 0.085, 0.083),
            (0.095, 0.041, 0.185, 0.086, 0.084),
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


def fitted_waist_band_v9(
    name,
    center_x,
    radius_x,
    radius_y,
    z,
    width,
    material,
    armature,
    body,
    **kwargs,
):
    # Keep both belts close to the exact body instead of reading as floating
    # hoops from side and rear views.
    if name == "Primary_Waist_Belt":
        radius_x, radius_y, z, width = 0.149, 0.099, 0.786, 0.013
    elif name == "Asymmetric_Waist_Belt":
        radius_x, radius_y, z, width = 0.153, 0.103, 0.798, 0.010
        kwargs["slope"] = 0.010
    elif name.startswith("Knee_Strap_"):
        radius_x *= 0.94
        radius_y *= 0.82
    return _original_band(
        name,
        center_x,
        radius_x,
        radius_y,
        z,
        width,
        material,
        armature,
        body,
        **kwargs,
    )


def create_outfit_v9(body, armature, fabric, strap, metal):
    v7.tune_material(fabric, base=(0.014, 0.017, 0.024), roughness=0.66)
    v7.tune_material(strap, base=(0.004, 0.005, 0.008), roughness=0.36)
    v7.tune_material(metal, base=(0.31, 0.35, 0.42), roughness=0.18, metallic=0.94)

    objects = v7._original_create_outfit(body, armature, fabric, strap, metal)

    front = build.c.extract_surface(
        body,
        armature,
        "Cargo_Fitted_Front_Pelvis",
        lambda point: (
            0.500 <= point.z <= 0.790
            and point.y < 0.010
            and abs(point.x)
            <= 0.030 + max(0.0, point.z - 0.500) * 0.35
        ),
        fabric,
        0.0040,
    )
    back = build.c.extract_surface(
        body,
        armature,
        "Cargo_Fitted_Back_Yoke",
        lambda point: (
            0.495 <= point.z <= 0.790
            and point.y >= -0.012
            and abs(point.x)
            <= 0.036 + max(0.0, point.z - 0.495) * 0.32
        ),
        fabric,
        0.0040,
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
                0.535 <= point.z <= 0.790
                and 0.030 <= sign * point.x <= 0.142
                and not (
                    point.z >= 0.710
                    and sign * point.x >= 0.108
                    and abs(point.y) <= 0.078
                )
            ),
            fabric,
            0.0042,
        )
        build.finish_skinned(panel, body)
        fitted_panels.append(panel)

    return [*fitted_panels, *objects]


# Importing v7 installs UV, pocket, buckle, material and distribution-safety
# overrides. Replace only silhouette, belt fit and deformation decisions.
build.asymmetric_leg_shell = fitted_leg_shell_v9
build.flat_ellipse_band = fitted_waist_band_v9
build.create_outfit = create_outfit_v9

if __name__ == "__main__":
    exit_code = build.main()
    if exit_code == 0:
        v7.save_distribution_blend()
    raise SystemExit(exit_code)
