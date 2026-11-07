#!/usr/bin/env python3
"""Stable product entrypoint for the Siroino white ghost gown.

The canonical build owns construction and evidence. This entrypoint contains only
measured corrections from hosted Blender review: exact degenerate-face cleanup,
a lower-force near-closed sewn skirt seam, and a compact wrist drape whose
skinning and collision envelope remain local to the forearm/hand chain.
"""
from __future__ import annotations

from dataclasses import replace

import bmesh

import siroino_white_ghost_gown_build as build
import siroino_white_ghost_gown_geometry as geometry

_DEGENERATE_CROSS_LENGTH_SQUARED = 1e-20
_ORIGINAL_BUILD_GARMENT = geometry.build_garment
_ORIGINAL_WRIST_DRAPE = geometry.wrist_drape
_ORIGINAL_CLEAN_MESHES = build.clean_meshes


# The previous 8-degree opening was being pulled shut with force 12, producing a
# folded/spiky center-back seam in direct back-view evidence. Start almost closed
# and use a gentler sewing spring; sewing remains physical and auditable.
_REVISED_SKIRT = replace(
    geometry.DEFAULT_SPEC.skirt,
    seam_gap_degrees=2.0,
    sewing_force_max=4.0,
    frame_end=42,
)

# Hosted Blender pose review showed that the original 0.30 m-tall panel, widening
# to 0.205 m half-width, behaves like a broad rigid wing even after the rejected
# Hips influence is removed. Keep the design cue but reduce the swept collision
# envelope around the forearm. These are geometry changes, not a relaxed visual
# gate: fresh multi-view and pose evidence still decides acceptance.
_REVISED_WRIST_DRAPE = replace(
    geometry.DEFAULT_SPEC.wrist_drape,
    width_top=0.060,
    width_bottom=0.115,
    height=0.180,
    lateral_drop=0.008,
    fold_amplitude=0.006,
    hem_wave_amplitude=0.008,
)
_REVISED_SPEC = replace(
    geometry.DEFAULT_SPEC,
    skirt=_REVISED_SKIRT,
    wrist_drape=_REVISED_WRIST_DRAPE,
)
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
    _ORIGINAL_CLEAN_MESHES(objects)
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
    hand = obj.vertex_groups.new(name=f"Hand_{side}")

    for vertex in mesh.vertices:
        height = max(0.0, min(1.0, (float(vertex.co.z) - z_min) / span))
        # Keep every influence on the local arm chain. The wrist edge follows the
        # hand while the free edge follows the lower arm more strongly, avoiding
        # both torso-spanning skinning constraints and rigid hand-only rotation.
        hand_weight = 0.15 + 0.70 * (height * height)
        lower_arm_weight = 1.0 - hand_weight
        hand.add([vertex.index], hand_weight, "REPLACE")
        lower_arm.add([vertex.index], lower_arm_weight, "REPLACE")
    return obj


def _build_garment(body, armature, spec=_REVISED_SPEC):
    assembly = _ORIGINAL_BUILD_GARMENT(body, armature, spec)
    return geometry.GarmentAssembly(
        objects=assembly.objects,
        skirt=assembly.skirt,
        sewing_edge_count=assembly.sewing_edge_count,
        # Drape weights are deliberately non-rigid across the local arm chain.
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
