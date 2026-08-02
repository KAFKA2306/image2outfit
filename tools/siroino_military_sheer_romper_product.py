#!/usr/bin/env python3
"""Stable SiroinoSotai_PC fit entrypoint for the military romper."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import bpy
from mathutils import Vector

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_military_sheer_romper_target_fit as fit  # noqa: E402

ORIGINAL_EXTRACT = fit.extract_surface
ORIGINAL_FINISH_SKINNED = fit.finish_skinned
ORIGINAL_CONFIGURE_SCENE = fit.configure_scene


def _world_bounds(body: bpy.types.Object) -> tuple[Vector, Vector]:
    points = [body.matrix_world @ vertex.co for vertex in body.data.vertices]
    return (
        Vector((
            min(point.x for point in points),
            min(point.y for point in points),
            min(point.z for point in points),
        )),
        Vector((
            max(point.x for point in points),
            max(point.y for point in points),
            max(point.z for point in points),
        )),
    )


def _neck_predicate(
    body: bpy.types.Object,
    armature: bpy.types.Object,
) -> Callable[[Vector], bool]:
    candidates = [
        bone
        for bone in armature.data.bones
        if "neck" in bone.name.lower()
    ]
    if candidates:
        bone = candidates[0]
        head = armature.matrix_world @ bone.head_local
        tail = armature.matrix_world @ bone.tail_local
        center = (head + tail) * 0.5
        low = min(head.z, tail.z) - 0.035
        high = max(head.z, tail.z) + 0.055
        radius_x = max(0.11, abs(tail.z - head.z) * 1.8)
        radius_y = max(0.09, radius_x * 0.78)
        return lambda co: (
            low <= co.z <= high
            and abs(co.x - center.x) <= radius_x
            and abs(co.y - center.y) <= radius_y
        )

    minimum, maximum = _world_bounds(body)
    height = maximum.z - minimum.z
    center_x = (minimum.x + maximum.x) * 0.5
    center_y = (minimum.y + maximum.y) * 0.5
    low = minimum.z + height * 0.72
    high = minimum.z + height * 0.88
    width = max(0.14, (maximum.x - minimum.x) * 0.22)
    depth = max(0.11, (maximum.y - minimum.y) * 0.22)
    return lambda co: (
        low <= co.z <= high
        and abs(co.x - center_x) <= width
        and abs(co.y - center_y) <= depth
    )


def mirror_body_parent_finish_skinned(
    obj: bpy.types.Object,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    values: dict[str, float],
    *,
    fit_audit: bool,
) -> bpy.types.Object:
    """Skin the garment, then mirror the target body's parent-space contract.

    Imported FBX bodies can carry a non-identity parent transform. Parenting a
    new mesh directly to the armature without copying the body's parent inverse
    applies that transform twice. The garment must use the same parent,
    parent-inverse, and world transform as the source body.
    """
    world = obj.matrix_world.copy()
    result = ORIGINAL_FINISH_SKINNED(
        obj,
        body,
        armature,
        values,
        fit_audit=fit_audit,
    )
    result.parent = body.parent
    result.parent_type = body.parent_type
    result.parent_bone = body.parent_bone
    if body.parent is not None:
        result.matrix_parent_inverse = body.matrix_parent_inverse.copy()
    result.matrix_world = world
    bpy.context.view_layer.update()
    return result


def robust_extract(
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
):
    try:
        return ORIGINAL_EXTRACT(
            body,
            armature,
            name,
            predicate,
            material,
            values,
            offset=offset,
            thickness=thickness,
            fit_audit=fit_audit,
        )
    except RuntimeError as error:
        if "produced no faces" not in str(error) or name != "Military_Standing_Collar":
            raise
        return ORIGINAL_EXTRACT(
            body,
            armature,
            name,
            _neck_predicate(body, armature),
            material,
            values,
            offset=max(offset, 0.0085),
            thickness=thickness,
            fit_audit=fit_audit,
        )


def configure_review_scene(body: bpy.types.Object) -> bpy.types.Object:
    camera = ORIGINAL_CONFIGURE_SCENE(body)
    scene = bpy.context.scene
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    return camera


def main() -> int:
    fit.finish_skinned = mirror_body_parent_finish_skinned
    fit.extract_surface = robust_extract
    fit.configure_scene = configure_review_scene
    fit.REVISION = "siroino-pc-surface-fit-v8.3"
    return fit.main()


if __name__ == "__main__":
    raise SystemExit(main())
