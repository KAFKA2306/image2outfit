#!/usr/bin/env python3
"""Converge the Military Sheer Romper against the actual Siroino body.

This product-only manufacturing wrapper keeps the existing garment generator but
projects every wearable panel into a bounded body-clearance envelope before the
canonical target-fit audit runs. It fixes both failure modes exposed by the v12
hosted evidence: local penetration and globally inflated fit.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_military_sheer_romper_fit_product as product  # noqa: E402

ORIGINAL_EXTRACT = product.extract
ORIGINAL_BUILD = product.build
ORIGINAL_AUDIT = product.target_fit_audit
ORIGINAL_SCENE = product.ORIGINAL_SCENE

TARGET_CLEARANCE = {
    "Military_Opaque_Bodice": 0.012,
    "Military_Sheer_Back": 0.007,
    "Military_Fitted_Shorts": 0.014,
    "Military_Asymmetric_Front_Flap": 0.018,
    "Military_Standing_Collar": 0.010,
    "Military_Sleeve_L": 0.010,
    "Military_Sleeve_R": 0.010,
    "Military_Waist_Belt": 0.014,
}


def extract(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    name: str,
    predicate,
    material: bpy.types.Material,
    values: dict[str, float],
    *,
    offset: float,
    thickness: float,
    fit_audit: bool = True,
) -> bpy.types.Object:
    target = TARGET_CLEARANCE.get(name, offset)
    audited = fit_audit or name in {
        "Military_Asymmetric_Front_Flap",
        "Military_Waist_Belt",
    }
    return ORIGINAL_EXTRACT(
        body,
        armature,
        name,
        predicate,
        material,
        values,
        offset=target,
        thickness=thickness,
        fit_audit=audited,
    )


def _apply_vertex_delta(obj: bpy.types.Object, index: int, delta: Vector) -> None:
    keys = getattr(obj.data, "shape_keys", None)
    if keys is None:
        obj.data.vertices[index].co += delta
        return
    for block in keys.key_blocks:
        block.data[index].co += delta


def project_to_clearance(
    body: bpy.types.Object,
    obj: bpy.types.Object,
    target: float,
    *,
    iterations: int = 3,
) -> dict[str, float | int]:
    """Project the evaluated base surface to one measured body-clearance shell."""
    moved_total = 0
    largest_move = 0.0
    for _ in range(iterations):
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        body_tree = BVHTree.FromObject(body, depsgraph)
        if body_tree is None:
            raise RuntimeError("cannot build Siroino body BVH for fit convergence")
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        count = min(
            int(obj.get("image2outfit_base_vertex_count", len(mesh.vertices))),
            len(mesh.vertices),
            len(obj.data.vertices),
        )
        body_inverse = body.matrix_world.inverted()
        object_inverse = obj.matrix_world.inverted()
        corrections: list[tuple[int, Vector]] = []
        try:
            for index, vertex in enumerate(mesh.vertices[:count]):
                world = evaluated.matrix_world @ vertex.co
                body_local = body_inverse @ world
                nearest = body_tree.find_nearest(body_local)
                point, normal = nearest[0], nearest[1]
                if point is None or normal is None or normal.length_squared <= 1e-12:
                    continue
                normal = normal.normalized()
                desired_body = point + normal * target
                desired_world = body.matrix_world @ desired_body
                desired_local = object_inverse @ desired_world
                current_local = object_inverse @ world
                delta = desired_local - current_local
                if delta.length > 0.060:
                    raise RuntimeError(
                        f"non-local clearance correction {obj.name}[{index}] "
                        f"requires {delta.length:.6f} m"
                    )
                if delta.length > 0.00025:
                    corrections.append((index, delta))
        finally:
            evaluated.to_mesh_clear()

        if not corrections:
            break
        for index, delta in corrections:
            _apply_vertex_delta(obj, index, delta)
            largest_move = max(largest_move, float(delta.length))
        moved_total += len(corrections)
        obj.data.update()

    bpy.context.view_layer.update()
    obj["image2outfit_clearance_target_m"] = float(target)
    return {
        "targetClearanceMeters": float(target),
        "movedVerticesAcrossIterations": moved_total,
        "largestSingleCorrectionMeters": largest_move,
    }


def build(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    cloth: bpy.types.Material,
    sheer: bpy.types.Material,
    gold: bpy.types.Material,
    values: dict[str, float],
) -> list[bpy.types.Object]:
    garments = ORIGINAL_BUILD(body, armature, cloth, sheer, gold, values)
    convergence: dict[str, dict[str, float | int]] = {}
    for obj in garments:
        target = TARGET_CLEARANCE.get(obj.name)
        if target is None:
            continue
        obj["image2outfit_fit_audit"] = True
        convergence[obj.name] = project_to_clearance(body, obj, target)
    bpy.context.scene["militaryRomperClearanceConvergence"] = json.dumps(
        convergence,
        sort_keys=True,
    )
    return garments


def target_fit_audit(
    body: bpy.types.Object,
    garments: list[bpy.types.Object],
) -> dict[str, object]:
    result = ORIGINAL_AUDIT(body, garments)
    median = result.get("medianClearanceMeters")
    maximum = result.get("maximumClearanceMeters")
    object_medians = {
        name: values.get("medianClearanceMeters")
        for name, values in result.get("objects", {}).items()
        if isinstance(values, dict)
    }
    excessive = {
        name: value
        for name, value in object_medians.items()
        if isinstance(value, (int, float))
        and value > TARGET_CLEARANCE.get(name, 0.018) + 0.006
    }
    envelope_passed = (
        isinstance(median, (int, float))
        and median <= 0.020
        and isinstance(maximum, (int, float))
        and maximum <= 0.045
        and not excessive
    )
    result["clearanceEnvelope"] = {
        "medianMaximumMeters": 0.020,
        "absoluteMaximumMeters": 0.045,
        "excessiveMedianObjects": excessive,
        "passed": envelope_passed,
    }
    result["passed"] = bool(result.get("passed")) and envelope_passed
    return result


def scene(body: bpy.types.Object) -> bpy.types.Object:
    # Canonical studio, without the old product-specific 70% light reduction.
    # Keep 512px for bounded iteration; final evidence is raised after geometry converges.
    camera = ORIGINAL_SCENE(body)
    render = bpy.context.scene.render
    render.resolution_x = 512
    render.resolution_y = 512
    render.resolution_percentage = 100
    return camera


def main() -> int:
    product.extract = extract
    product.build = build
    product.target_fit_audit = target_fit_audit
    product.scene = scene
    return product.main()


if __name__ == "__main__":
    raise SystemExit(main())
