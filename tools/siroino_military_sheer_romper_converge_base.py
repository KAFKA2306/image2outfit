#!/usr/bin/env python3
"""Military Romper convergence entry using base-mesh clearance projection.

The canonical static fit audit intentionally disables non-armature modifiers.
This entry makes the correction step measure the same base vertices instead of
assuming Solidify/Bevel evaluated-mesh vertex ordering preserves the source
indices.
"""
from __future__ import annotations

import sys
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_military_sheer_romper_converge as converge  # noqa: E402


def project_base_to_clearance(
    body: bpy.types.Object,
    obj: bpy.types.Object,
    target: float,
    *,
    iterations: int = 3,
) -> dict[str, float | int]:
    moved_total = 0
    largest_move = 0.0
    for _ in range(iterations):
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        body_tree = BVHTree.FromObject(body, depsgraph)
        if body_tree is None:
            raise RuntimeError("cannot build Siroino body BVH for fit convergence")

        body_inverse = body.matrix_world.inverted()
        object_inverse = obj.matrix_world.inverted()
        corrections: list[tuple[int, Vector]] = []
        for vertex in obj.data.vertices:
            world = obj.matrix_world @ vertex.co
            body_local = body_inverse @ world
            nearest = body_tree.find_nearest(body_local)
            point, normal = nearest[0], nearest[1]
            if point is None or normal is None or normal.length_squared <= 1e-12:
                continue
            normal = normal.normalized()
            desired_body = point + normal * target
            desired_world = body.matrix_world @ desired_body
            desired_local = object_inverse @ desired_world
            delta = desired_local - vertex.co
            if delta.length > 0.060:
                raise RuntimeError(
                    f"non-local base correction {obj.name}[{vertex.index}] "
                    f"requires {delta.length:.6f} m"
                )
            if delta.length > 0.00025:
                corrections.append((vertex.index, delta))

        if not corrections:
            break
        for index, delta in corrections:
            obj.data.vertices[index].co += delta
            largest_move = max(largest_move, float(delta.length))
        moved_total += len(corrections)
        obj.data.update()

    bpy.context.view_layer.update()
    obj["image2outfit_clearance_target_m"] = float(target)
    return {
        "targetClearanceMeters": float(target),
        "movedVerticesAcrossIterations": moved_total,
        "largestSingleCorrectionMeters": largest_move,
        "projectionDomain": "base-mesh-with-non-armature-modifiers-excluded",
    }


def main() -> int:
    converge.project_to_clearance = project_base_to_clearance
    return converge.main()


if __name__ == "__main__":
    raise SystemExit(main())
