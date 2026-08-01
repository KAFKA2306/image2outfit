#!/usr/bin/env python3
"""Final visual/deformation refit for the Siroino Wide Cargo candidate.

This layer is deliberately small and reproducible.  It imports the production
entry point, tightens the remaining rigid shell proportions, closes the visual
knee discontinuity, conforms belts/straps, and replaces transferred decorative
weights with deterministic garment-specific weights before running the normal
build and distribution-save path.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_entry as production

build = production.build
_current_leg_shell = build.asymmetric_leg_shell
_current_band = build.flat_ellipse_band
_current_create_outfit = build.create_outfit


def _single_bone(obj: bpy.types.Object, bone: str) -> None:
    production.replace_vertex_weights(
        obj,
        {bone: [(vertex.index, 1.0) for vertex in obj.data.vertices]},
    )


def _knee_blend(obj: bpy.types.Object, side: str) -> None:
    upper = f"UpperLeg_{side}"
    lower = f"LowerLeg_{side}"
    assignments = {upper: [], lower: []}
    z_values = [vertex.co.z for vertex in obj.data.vertices]
    minimum = min(z_values, default=0.0)
    maximum = max(z_values, default=1.0)
    span = max(maximum - minimum, 1e-6)
    for vertex in obj.data.vertices:
        t = production.clamp((vertex.co.z - minimum) / span, 0.0, 1.0)
        upper_weight = 0.18 + 0.42 * t
        assignments[upper].append((vertex.index, upper_weight))
        assignments[lower].append((vertex.index, 1.0 - upper_weight))
    production.replace_vertex_weights(obj, assignments)


def refined_leg_shell(name, side, rings, material, armature, body, segments=48):
    obj = _current_leg_shell(
        name, side, rings, material, armature, body, segments=segments
    )
    coordinates = [vertex.co.copy() for vertex in obj.data.vertices]
    center_x = sum(value.x for value in coordinates) / max(1, len(coordinates))

    if "UpperLeg" in name:
        # Keep the cargo silhouette broad from the front, but remove the rigid
        # barrel profile that inflated in crouch/sit views.
        for vertex in obj.data.vertices:
            vertex.co.x = center_x + (vertex.co.x - center_x) * 0.86
            vertex.co.y *= 0.70
            if vertex.co.z < 0.485:
                vertex.co.z -= 0.035
    elif "LowerLeg" in name:
        # A nearly parallel leg reads as wide cargo without the cone/tube look.
        for vertex in obj.data.vertices:
            vertex.co.x = center_x + (vertex.co.x - center_x) * 0.80
            vertex.co.y *= 0.62
            if vertex.co.z > 0.36:
                vertex.co.z += 0.035
            if vertex.co.z < 0.12:
                vertex.co.z += 0.025
        side_name = "L" if side < 0 else "R"
        _knee_blend(obj, side_name)

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
    vertices = list(obj.data.vertices)
    if name in {"Primary_Waist_Belt", "Asymmetric_Waist_Belt"}:
        # Conform to the actual low-rise body envelope rather than orbiting it.
        for vertex in vertices:
            vertex.co.x *= 0.90
            vertex.co.y *= 0.80
            vertex.co.z -= 0.006
        _single_bone(obj, "Hips")
    elif name.startswith("Knee_Strap_"):
        side_name = "L" if "_L_" in name else "R"
        local_center = sum(vertex.co.x for vertex in vertices) / max(1, len(vertices))
        for vertex in vertices:
            vertex.co.x = local_center + (vertex.co.x - local_center) * 0.84
            vertex.co.y *= 0.70
            vertex.co.z -= 0.002
        _knee_blend(obj, side_name)
    obj.data.update(calc_edges=True)
    return obj


def refined_create_outfit(body, armature, fabric, strap, metal):
    objects = _current_create_outfit(body, armature, fabric, strap, metal)
    for obj in objects:
        name = obj.name
        if name.startswith("Cargo_Pocket_"):
            _single_bone(obj, "UpperLeg_L" if name.endswith("_L") else "UpperLeg_R")
        elif name.startswith("Hip_Cutout_Strap_") or name.startswith("Hip_Ring_"):
            _single_bone(obj, "Hips")
        elif name.startswith("Knee_Zipper_") or name.startswith("Knee_Zip_Pull_"):
            side_name = "L" if name.endswith("_L") else "R"
            _knee_blend(obj, side_name)
    return objects


build.asymmetric_leg_shell = refined_leg_shell
build.flat_ellipse_band = refined_band
build.create_outfit = refined_create_outfit

if __name__ == "__main__":
    exit_code = build.main()
    if exit_code == 0:
        production.save_distribution_blend()
    raise SystemExit(exit_code)
