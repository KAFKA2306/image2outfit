#!/usr/bin/env python3
"""Stable product entrypoint for the Siroino white ghost gown.

The canonical build owns construction and evidence. This entrypoint contains only
measured corrections from the latest hosted Blender review: exact degenerate-face
cleanup, a lower-force near-closed sewn skirt seam, and pose-stable wrist-drape
weights that keep the free edge hanging instead of rotating rigidly with the hand.
"""
from __future__ import annotations

from dataclasses import replace

import bmesh

import siroino_white_ghost_gown_build as build
import siroino_white_ghost_gown_geometry as geometry

_DEGENERATE_CROSS_LENGTH_SQUARED = 1e-20
_ORIGINAL_BUILD_GARMENT = geometry.build_garment
_ORIGINAL_WRIST_DRAPE = geometry.wrist_drape


# The previous 8-degree opening was being pulled shut with force 12, producing a
# folded/spiky center-back seam in direct back-view evidence. Start almost closed
# and use a gentler sewing spring; sewing remains physical and auditable.
_REVISED_SKIRT = replace(
    geometry.DEFAULT_SPEC.skirt,
    seam_gap_degrees=2.0,
    sewing_force_max=4.0,
    frame_end=42,
)
_REVISED_SPEC = replace(geometry.DEFAULT_SPEC, skirt=_REVISED_SKIRT)
geometry.DEFAULT_SPEC = _REVISED_SPEC


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


def _pose_stable_wrist_drape(side, armature, material, spec):
    obj = _ORIGINAL_WRIST_DRAPE(side, armature, material, spec)
    mesh = obj.data
    if not mesh.vertices:
        return obj

    z_values = [float(vertex.co.z) for vertex in mesh.vertices]
    z_min = min(z_values)
    z_max = max(z_values)
    span = max(z_max - z_min, 1e-8)
    obj.vertex_groups.clear()
    lower_arm = obj.vertex_groups.new(name=f"LowerArm_{side}")
    hips = obj.vertex_groups.new(name="Hips")

    for vertex in mesh.vertices:
        height = max(0.0, min(1.0, (float(vertex.co.z) - z_min) / span))
        # Keep the wrist edge attached to the forearm while progressively
        # anchoring the hanging free edge to the body frame. This approximates
        # gravity in pose review without making the whole panel rigid to Hand.
        arm_weight = 0.18 + 0.82 * (height * height)
        hip_weight = 1.0 - arm_weight
        lower_arm.add([vertex.index], arm_weight, "REPLACE")
        if hip_weight > 1e-8:
            hips.add([vertex.index], hip_weight, "REPLACE")
    return obj


def _build_garment(body, armature, spec=_REVISED_SPEC):
    assembly = _ORIGINAL_BUILD_GARMENT(body, armature, spec)
    return geometry.GarmentAssembly(
        objects=assembly.objects,
        skirt=assembly.skirt,
        sewing_edge_count=assembly.sewing_edge_count,
        # Drape weights are deliberately non-rigid so the free edge remains
        # hanging through arms-up / arm-cross review poses.
        rigid_groups={
            name: bone
            for name, bone in assembly.rigid_groups.items()
            if not name.startswith("Ghost_Wrist_Drape_")
        },
    )


build.clean_meshes = clean_meshes
geometry.wrist_drape = _pose_stable_wrist_drape
geometry.build_garment = _build_garment


if __name__ == "__main__":
    raise SystemExit(build.main())
