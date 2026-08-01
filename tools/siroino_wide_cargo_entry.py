#!/usr/bin/env python3
"""UV-aware entry point for the Siroino Wide Cargo generator."""
from __future__ import annotations

import math

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


build.mesh_obj = mesh_obj_with_uv

if __name__ == "__main__":
    raise SystemExit(build.main())
