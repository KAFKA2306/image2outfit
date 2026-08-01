#!/usr/bin/env python3
"""UV-aware and distribution-safe entry point for Siroino Wide Cargo."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_build as build

_original_mesh_object = build.mesh_object
_original_create_outfit = build.create_outfit
_original_asymmetric_leg_shell = build.asymmetric_leg_shell
_original_flat_ellipse_band = build.flat_ellipse_band
_original_flat_path_ribbon = build.flat_path_ribbon


def mesh_object_with_uv(*args, **kwargs):
    obj = _original_mesh_object(*args, **kwargs)
    mesh = obj.data
    if mesh.uv_layers.active is None:
        uv_layer = mesh.uv_layers.new(name="UVMap")
        coordinates = [vertex.co for vertex in mesh.vertices]
        center_x = sum(co.x for co in coordinates) / max(1, len(coordinates))
        center_y = sum(co.y for co in coordinates) / max(1, len(coordinates))
        minimum_z = min((co.z for co in coordinates), default=0.0)
        maximum_z = max((co.z for co in coordinates), default=1.0)
        span_z = max(maximum_z - minimum_z, 1e-6)
        for polygon in mesh.polygons:
            for loop_index in polygon.loop_indices:
                vertex_index = mesh.loops[loop_index].vertex_index
                coordinate = mesh.vertices[vertex_index].co
                angle = math.atan2(coordinate.y - center_y, coordinate.x - center_x)
                u = (angle / math.tau) % 1.0
                v = (coordinate.z - minimum_z) / span_z
                uv_layer.data[loop_index].uv = (u, v)
    mesh.update()
    return obj


def fitted_leg_shell(name, side, rings, material, armature, body, segments=48):
    if "UpperLeg" in name:
        adjusted = []
        for index, (z, _inner, outer, front, back) in enumerate(rings):
            inner = 0.006 + index * 0.002
            adjusted.append((z, inner, outer, front, back))
        rings = adjusted
    return _original_asymmetric_leg_shell(
        name,
        side,
        rings,
        material,
        armature,
        body,
        segments=segments,
    )


def fitted_waist_band(
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
    if name == "Primary_Waist_Belt":
        radius_x, radius_y, z, width = 0.157, 0.108, 0.787, 0.014
    elif name == "Asymmetric_Waist_Belt":
        radius_x, radius_y, z, width = 0.161, 0.112, 0.798, 0.011
        kwargs["slope"] = 0.012
    return _original_flat_ellipse_band(
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


def trimmed_path_ribbon(name, points, width, material, armature, body):
    if name.startswith("Hip_Cutout_Strap_"):
        points = [
            (
                math.copysign(min(abs(x), 0.158), x),
                y,
                z,
            )
            for x, y, z in points
        ]
    return _original_flat_path_ribbon(
        name,
        points,
        width,
        material,
        armature,
        body,
    )


def create_outfit_with_fitted_pelvis(body, armature, fabric, strap, metal):
    """Create a conventional crotch and inner-thigh seam with open outer hips."""
    objects = _original_create_outfit(body, armature, fabric, strap, metal)

    front = build.c.extract_surface(
        body,
        armature,
        "Cargo_Fitted_Front_Pelvis",
        lambda point: (
            0.520 <= point.z <= 0.792
            and point.y < 0.006
            and abs(point.x)
            <= 0.028 + max(0.0, point.z - 0.520) * 0.39
        ),
        fabric,
        0.0055,
    )
    back = build.c.extract_surface(
        body,
        armature,
        "Cargo_Fitted_Back_Yoke",
        lambda point: (
            0.515 <= point.z <= 0.792
            and point.y >= -0.008
            and abs(point.x)
            <= 0.034 + max(0.0, point.z - 0.515) * 0.36
        ),
        fabric,
        0.0055,
    )
    build.finish_skinned(front, body)
    build.finish_skinned(back, body)
    return [front, back, *objects]


def save_distribution_blend() -> None:
    _, job = build.c.load_job()
    blend_path = build.c.repo_path(job["blendPath"])
    for obj in list(bpy.data.objects):
        preview_only = (
            obj.name.startswith("SiroinoSotai_PC")
            or obj.name == "Studio_Floor"
            or obj.name == "Product_Camera"
            or obj.type in {"LIGHT", "CAMERA"}
        )
        if preview_only:
            bpy.data.objects.remove(obj, do_unlink=True)
    for collection in (bpy.data.meshes, bpy.data.materials, bpy.data.images):
        for datablock in list(collection):
            if datablock.users == 0:
                collection.remove(datablock)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)


build.mesh_object = mesh_object_with_uv
build.asymmetric_leg_shell = fitted_leg_shell
build.flat_ellipse_band = fitted_waist_band
build.flat_path_ribbon = trimmed_path_ribbon
build.create_outfit = create_outfit_with_fitted_pelvis

if __name__ == "__main__":
    exit_code = build.main()
    if exit_code == 0:
        save_distribution_blend()
    raise SystemExit(exit_code)
