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

_original_mesh_obj = build.mesh_obj


def mesh_obj_with_uv(*args, **kwargs):
    obj = _original_mesh_obj(*args, **kwargs)
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


build.mesh_obj = mesh_obj_with_uv

if __name__ == "__main__":
    exit_code = build.main()
    if exit_code == 0:
        save_distribution_blend()
    raise SystemExit(exit_code)
