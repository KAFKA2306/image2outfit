#!/usr/bin/env python3
"""Release-candidate refit for Siroino Wide Cargo.

This deterministic layer fixes defects observed in the actual hosted renders:
floating belts, exposed inner thighs that read as chaps, cylindrical legs,
disconnected knee sections, rigid pose deformation, and excessive projection.
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
    assignments = {"Hips": [], f"UpperLeg_{side}": []}
    zs = [vertex.co.z for vertex in obj.data.vertices]
    low, high = min(zs, default=0.0), max(zs, default=1.0)
    span = max(high - low, 1e-6)
    for vertex in obj.data.vertices:
        t = base.clamp((vertex.co.z - low) / span, 0.0, 1.0)
        upper_weight = 0.94 - 0.48 * t
        assignments[f"UpperLeg_{side}"].append((vertex.index, upper_weight))
        assignments["Hips"].append((vertex.index, 1.0 - upper_weight))
    _replace(obj, assignments)


def _lower_leg_gradient(obj: bpy.types.Object, side: str) -> None:
    assignments = {f"UpperLeg_{side}": [], f"LowerLeg_{side}": []}
    zs = [vertex.co.z for vertex in obj.data.vertices]
    low, high = min(zs, default=0.0), max(zs, default=1.0)
    span = max(high - low, 1e-6)
    for vertex in obj.data.vertices:
        t = base.clamp((vertex.co.z - low) / span, 0.0, 1.0)
        upper_weight = 0.06 + 0.72 * t
        assignments[f"UpperLeg_{side}"].append((vertex.index, upper_weight))
        assignments[f"LowerLeg_{side}"].append((vertex.index, 1.0 - upper_weight))
    _replace(obj, assignments)


def refined_leg_shell(name, side, rings, material, armature, body, segments=48):
    obj = _current_leg_shell(name, side, rings, material, armature, body, segments=segments)
    coordinates = [vertex.co.copy() for vertex in obj.data.vertices]
    center_x = sum(value.x for value in coordinates) / max(1, len(coordinates))
    side_name = "L" if side < 0 else "R"

    if "UpperLeg" in name:
        for vertex in obj.data.vertices:
            # Preserve horizontal width while flattening the side profile.
            vertex.co.x = center_x + (vertex.co.x - center_x) * 1.08
            vertex.co.y *= 0.44
            if vertex.co.z < 0.50:
                vertex.co.z -= 0.040
        _upper_leg_gradient(obj, side_name)
    elif "LowerLeg" in name:
        zs = [vertex.co.z for vertex in obj.data.vertices]
        low, high = min(zs, default=0.0), max(zs, default=1.0)
        span = max(high - low, 1e-6)
        for vertex in obj.data.vertices:
            t = base.clamp((vertex.co.z - low) / span, 0.0, 1.0)
            width_scale = 1.04 + 0.08 * (1.0 - t)
            vertex.co.x = center_x + (vertex.co.x - center_x) * width_scale
            vertex.co.y *= 0.40
            if vertex.co.z > 0.34:
                vertex.co.z += 0.045
            if vertex.co.z < 0.14:
                vertex.co.z += 0.028
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
        for vertex in vertices:
            vertex.co.x *= 0.68
            vertex.co.y *= 0.40
            vertex.co.z -= 0.012
        _single_bone(obj, "Hips")
    elif name.startswith("Knee_Strap_"):
        side_name = "L" if "_L_" in name else "R"
        local_center = sum(vertex.co.x for vertex in vertices) / max(1, len(vertices))
        for vertex in vertices:
            vertex.co.x = local_center + (vertex.co.x - local_center) * 0.72
            vertex.co.y *= 0.34
            vertex.co.z -= 0.002
        _lower_leg_gradient(obj, side_name)
    obj.data.update(calc_edges=True)
    return obj


def _remove_object(obj: bpy.types.Object) -> None:
    if obj.name in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)


def refined_create_outfit(body, armature, fabric, strap, metal):
    objects = _current_create_outfit(body, armature, fabric, strap, metal)

    # Remove the narrow center panels from the earlier pass. They left the full
    # inner thighs exposed and made the product read as chaps rather than pants.
    retained: list[bpy.types.Object] = []
    for obj in objects:
        if obj.name in {"Cargo_Fitted_Front_Pelvis", "Cargo_Fitted_Back_Yoke"}:
            _remove_object(obj)
        else:
            retained.append(obj)

    front = build.c.extract_surface(
        body,
        armature,
        "Cargo_Fitted_Front_Pelvis",
        lambda point: (
            0.438 <= point.z <= 0.790
            and point.y < 0.020
            and abs(point.x) <= 0.102 + max(0.0, point.z - 0.438) * 0.08
        ),
        fabric,
        0.0052,
    )
    back = build.c.extract_surface(
        body,
        armature,
        "Cargo_Fitted_Back_Yoke",
        lambda point: (
            0.435 <= point.z <= 0.790
            and point.y >= -0.020
            and abs(point.x) <= 0.108 + max(0.0, point.z - 0.435) * 0.07
        ),
        fabric,
        0.0052,
    )
    build.finish_skinned(front, body)
    build.finish_skinned(back, body)

    for obj in retained:
        name = obj.name
        if name.startswith("Cargo_Pocket_"):
            center = obj.location.copy()
            for vertex in obj.data.vertices:
                vertex.co.x = center.x + (vertex.co.x - center.x) * 0.72
                vertex.co.y = center.y + (vertex.co.y - center.y) * 0.50
                vertex.co.z = center.z + (vertex.co.z - center.z) * 0.84
            _single_bone(obj, "UpperLeg_L" if name.endswith("_L") else "UpperLeg_R")
            obj.data.update(calc_edges=True)
        elif name.startswith("Hip_Cutout_Strap_"):
            for vertex in obj.data.vertices:
                vertex.co.x *= 0.82
                vertex.co.y *= 0.54
            _single_bone(obj, "Hips")
            obj.data.update(calc_edges=True)
        elif name.startswith("Hip_Ring_"):
            obj.scale *= 0.52
            _single_bone(obj, "Hips")
        elif name.startswith("Knee_Zipper_") or name.startswith("Knee_Zip_Pull_"):
            side_name = "L" if name.endswith("_L") else "R"
            _lower_leg_gradient(obj, side_name)

    return [front, back, *retained]


build.asymmetric_leg_shell = refined_leg_shell
build.flat_ellipse_band = refined_band
build.create_outfit = refined_create_outfit

if __name__ == "__main__":
    exit_code = build.main()
    if exit_code == 0:
        base.save_distribution_blend()
    raise SystemExit(exit_code)
