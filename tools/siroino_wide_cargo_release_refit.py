#!/usr/bin/env python3
"""Release-candidate refit for Siroino Wide Cargo.

This deterministic layer keeps the generated product reproducible while fixing
visual defects found in hosted multiview and pose evidence: floating waist and
knee rings, disconnected leg sections, rigid crouch/sit deformation, excessive
pocket projection, and cylindrical lower-leg volume.
"""
from __future__ import annotations

import sys
from pathlib import Path

import bpy

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_entry_v8 as production

build = production.build
base = production.v7
_current_leg_shell = build.asymmetric_leg_shell
_current_band = build.flat_ellipse_band
_current_create_outfit = build.create_outfit


def _replace(obj: bpy.types.Object, assignments: dict[str, list[tuple[int, float]]]) -> None:
    base.replace_vertex_weights(obj, assignments)


def _single_bone(obj: bpy.types.Object, bone: str) -> None:
    _replace(obj, {bone: [(vertex.index, 1.0) for vertex in obj.data.vertices]})


def _upper_leg_gradient(obj: bpy.types.Object, side: str) -> None:
    hips = "Hips"
    upper = f"UpperLeg_{side}"
    zs = [vertex.co.z for vertex in obj.data.vertices]
    low = min(zs, default=0.0)
    high = max(zs, default=1.0)
    span = max(high - low, 1e-6)
    assignments = {hips: [], upper: []}
    for vertex in obj.data.vertices:
        t = base.clamp((vertex.co.z - low) / span, 0.0, 1.0)
        # At the waist follow Hips; toward the knee follow UpperLeg.
        upper_weight = 0.92 - 0.46 * t
        assignments[upper].append((vertex.index, upper_weight))
        assignments[hips].append((vertex.index, 1.0 - upper_weight))
    _replace(obj, assignments)


def _lower_leg_gradient(obj: bpy.types.Object, side: str) -> None:
    upper = f"UpperLeg_{side}"
    lower = f"LowerLeg_{side}"
    zs = [vertex.co.z for vertex in obj.data.vertices]
    low = min(zs, default=0.0)
    high = max(zs, default=1.0)
    span = max(high - low, 1e-6)
    assignments = {upper: [], lower: []}
    for vertex in obj.data.vertices:
        t = base.clamp((vertex.co.z - low) / span, 0.0, 1.0)
        # Knee edge follows the thigh enough to close during flexion; the hem
        # remains dominated by LowerLeg for stable walking deformation.
        upper_weight = 0.08 + 0.68 * t
        assignments[upper].append((vertex.index, upper_weight))
        assignments[lower].append((vertex.index, 1.0 - upper_weight))
    _replace(obj, assignments)


def refined_leg_shell(name, side, rings, material, armature, body, segments=48):
    obj = _current_leg_shell(name, side, rings, material, armature, body, segments=segments)
    coordinates = [vertex.co.copy() for vertex in obj.data.vertices]
    center_x = sum(value.x for value in coordinates) / max(1, len(coordinates))
    side_name = "L" if side < 0 else "R"

    if "UpperLeg" in name:
        for vertex in obj.data.vertices:
            # Preserve a wide frontal silhouette without a box-shaped side view.
            vertex.co.x = center_x + (vertex.co.x - center_x) * 0.82
            vertex.co.y *= 0.58
            # Extend the shell into the knee zone to remove the disconnected gap.
            if vertex.co.z < 0.50:
                vertex.co.z -= 0.055
        _upper_leg_gradient(obj, side_name)
    elif "LowerLeg" in name:
        zs = [vertex.co.z for vertex in obj.data.vertices]
        low = min(zs, default=0.0)
        high = max(zs, default=1.0)
        span = max(high - low, 1e-6)
        for vertex in obj.data.vertices:
            t = base.clamp((vertex.co.z - low) / span, 0.0, 1.0)
            # Slightly wider at the knee and nearly parallel toward the hem.
            width_scale = 0.68 + 0.08 * t
            vertex.co.x = center_x + (vertex.co.x - center_x) * width_scale
            vertex.co.y *= 0.48
            if vertex.co.z > 0.34:
                vertex.co.z += 0.060
            if vertex.co.z < 0.14:
                vertex.co.z += 0.040
        _lower_leg_gradient(obj, side_name)

    obj.data.update(calc_edges=True)
    return obj


def refined_band(
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
    obj = _current_band(
        name, center_x, radius_x, radius_y, z, width,
        material, armature, body, **kwargs
    )
    vertices = list(obj.data.vertices)
    if name in {"Primary_Waist_Belt", "Asymmetric_Waist_Belt"}:
        # Previous evidence showed rigid hoops outside the torso. Conform them
        # tightly enough to read as flat belts rather than detached rings.
        for vertex in vertices:
            vertex.co.x *= 0.76
            vertex.co.y *= 0.48
            vertex.co.z -= 0.010
        _single_bone(obj, "Hips")
    elif name.startswith("Knee_Strap_"):
        side_name = "L" if "_L_" in name else "R"
        local_center = sum(vertex.co.x for vertex in vertices) / max(1, len(vertices))
        for vertex in vertices:
            vertex.co.x = local_center + (vertex.co.x - local_center) * 0.56
            vertex.co.y *= 0.38
            vertex.co.z -= 0.004
        _lower_leg_gradient(obj, side_name)
    obj.data.update(calc_edges=True)
    return obj


def refined_create_outfit(body, armature, fabric, strap, metal):
    objects = _current_create_outfit(body, armature, fabric, strap, metal)
    for obj in objects:
        name = obj.name
        if name.startswith("Cargo_Pocket_"):
            # Reduce projection so pockets remain readable without floating.
            center = obj.location.copy()
            for vertex in obj.data.vertices:
                vertex.co.x = center.x + (vertex.co.x - center.x) * 0.78
                vertex.co.y = center.y + (vertex.co.y - center.y) * 0.62
                vertex.co.z = center.z + (vertex.co.z - center.z) * 0.88
            _single_bone(obj, "UpperLeg_L" if name.endswith("_L") else "UpperLeg_R")
            obj.data.update(calc_edges=True)
        elif name.startswith("Hip_Cutout_Strap_"):
            for vertex in obj.data.vertices:
                vertex.co.x *= 0.88
                vertex.co.y *= 0.68
            _single_bone(obj, "Hips")
            obj.data.update(calc_edges=True)
        elif name.startswith("Hip_Ring_"):
            # Decorative hip rings were visually detached; shrink them to the
            # attachment point while retaining the asymmetric hardware cue.
            obj.scale *= 0.64
            _single_bone(obj, "Hips")
        elif name.startswith("Knee_Zipper_") or name.startswith("Knee_Zip_Pull_"):
            side_name = "L" if name.endswith("_L") else "R"
            _lower_leg_gradient(obj, side_name)
    return objects


build.asymmetric_leg_shell = refined_leg_shell
build.flat_ellipse_band = refined_band
build.create_outfit = refined_create_outfit

if __name__ == "__main__":
    exit_code = build.main()
    if exit_code == 0:
        base.save_distribution_blend()
    raise SystemExit(exit_code)
