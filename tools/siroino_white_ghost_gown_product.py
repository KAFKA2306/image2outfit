#!/usr/bin/env python3
"""Stable product entrypoint for the Siroino white ghost gown.

The canonical build owns construction and evidence. This entrypoint strengthens the
final mesh cleanup using the exact loop-triangle criterion enforced by the build
gate, so zero-area polygons created by applied Blender modifiers cannot survive into
the FBX or review evidence.
"""
from __future__ import annotations

import bmesh

import siroino_white_ghost_gown_build as build

_DEGENERATE_CROSS_LENGTH_SQUARED = 1e-20


def _remove_metric_degenerate_polygons(obj) -> None:
    if obj.type != "MESH":
        return
    mesh = obj.data
    for _ in range(4):
        mesh.calc_loop_triangles()
        polygon_indices = {
            triangle.polygon_index
            for triangle in mesh.loop_triangles
            if (
                (
                    mesh.vertices[triangle.vertices[1]].co
                    - mesh.vertices[triangle.vertices[0]].co
                )
                .cross(
                    mesh.vertices[triangle.vertices[2]].co
                    - mesh.vertices[triangle.vertices[0]].co
                )
                .length_squared
                <= _DEGENERATE_CROSS_LENGTH_SQUARED
            )
        }
        if not polygon_indices:
            return

        cleanup = bmesh.new()
        cleanup.from_mesh(mesh)
        cleanup.faces.ensure_lookup_table()
        doomed = [
            cleanup.faces[index]
            for index in sorted(polygon_indices)
            if index < len(cleanup.faces)
        ]
        if doomed:
            bmesh.ops.delete(cleanup, geom=doomed, context="FACES")
        bmesh.ops.dissolve_degenerate(
            cleanup,
            dist=1e-7,
            edges=list(cleanup.edges),
        )
        loose = [vertex for vertex in cleanup.verts if not vertex.link_faces]
        if loose:
            bmesh.ops.delete(cleanup, geom=loose, context="VERTS")
        cleanup.to_mesh(mesh)
        cleanup.free()
        mesh.update(calc_edges=True)

    mesh.calc_loop_triangles()
    remaining = sum(
        1
        for triangle in mesh.loop_triangles
        if (
            (
                mesh.vertices[triangle.vertices[1]].co
                - mesh.vertices[triangle.vertices[0]].co
            )
            .cross(
                mesh.vertices[triangle.vertices[2]].co
                - mesh.vertices[triangle.vertices[0]].co
            )
            .length_squared
            <= _DEGENERATE_CROSS_LENGTH_SQUARED
        )
    )
    if remaining:
        raise RuntimeError(
            f"metric-degenerate triangles remain in {obj.name}: {remaining}"
        )


def clean_meshes(objects) -> None:
    build.clean_meshes(objects)
    for obj in objects:
        _remove_metric_degenerate_polygons(obj)


build.clean_meshes = clean_meshes


if __name__ == "__main__":
    raise SystemExit(build.main())
