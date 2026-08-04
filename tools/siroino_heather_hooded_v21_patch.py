#!/usr/bin/env python3
"""Runtime geometry patch for the v21 Siroino bodysuit revision.

The patch is injected by the canonical product entrypoint so the repository's
maximum product import depth remains unchanged. It alters only the lower-body
selection, opening-boundary relaxation, shell clearance and folded-hood roll.
"""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType

import bpy
from mathutils import Vector

DESIGN_REVISION = "v21-pose-clear-underbody-five-opening-shell"
SHELL_CLEARANCE_M = 0.022

PolygonPredicate = Callable[[bpy.types.MeshPolygon, Vector], bool]


def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def _highcut_width(z: float) -> float:
    """Taper continuously from a narrow underbody bridge into the torso."""
    t = (z - 0.515) / (0.850 - 0.515)
    return 0.024 + 0.141 * _smoothstep(t)


def _body_shell_predicate(
    pattern: ModuleType, body: bpy.types.Object
) -> PolygonPredicate:
    v9 = pattern.v9
    arm_groups = {
        side: (
            v9._group_index(body, f"UpperArm_{side}"),
            v9._group_index(body, f"LowerArm_{side}"),
            v9._group_index(body, f"Hand_{side}"),
        )
        for side in ("L", "R")
    }

    def selected(
        polygon: bpy.types.MeshPolygon,
        center: Vector,
    ) -> bool:
        x = abs(center.x)
        torso = 0.815 <= center.z <= pattern._torso_top(
            center.x
        ) and x <= pattern._torso_width(center.z)
        underbody = 0.515 <= center.z <= 0.850 and x <= _highcut_width(center.z)
        if torso or underbody:
            return True

        for upper, lower, hand in arm_groups.values():
            upper_weight = v9._polygon_average_weight(body, polygon, (upper,))
            lower_weight = v9._polygon_average_weight(body, polygon, (lower,))
            hand_weight = v9._polygon_average_weight(body, polygon, (hand,))
            arm_weight = upper_weight + lower_weight
            if hand_weight <= 0.52 and arm_weight >= 0.008:
                return True
            if center.z >= 0.900 and upper_weight >= 0.002:
                return True
        return False

    return selected


def _smooth_and_project_boundaries(
    pattern: ModuleType,
    obj: bpy.types.Object,
    source: bpy.types.Object,
    offset: float,
) -> None:
    """Relax four boundary rings before reprojecting to the evaluated target."""
    weights = pattern._boundary_vertex_weights(obj.data)
    if not weights:
        return
    group = obj.vertex_groups.new(name="Temporary_Boundary_Smoothing")
    group_name = group.name
    for index, weight in weights.items():
        group.add([index], weight, "REPLACE")

    smooth = obj.modifiers.new("Opening boundary smoothing", "SMOOTH")
    smooth.vertex_group = group_name
    smooth.factor = 0.72
    smooth.iterations = 14
    pattern._move_modifier_before_armature(obj, smooth)
    bpy.ops.object.modifier_apply(modifier=smooth.name)

    shrinkwrap = obj.modifiers.new("Evaluated target reprojection", "SHRINKWRAP")
    shrinkwrap.target = source
    shrinkwrap.wrap_method = "NEAREST_SURFACEPOINT"
    shrinkwrap.offset = offset
    pattern._move_modifier_before_armature(obj, shrinkwrap)
    bpy.ops.object.modifier_apply(modifier=shrinkwrap.name)

    temporary_group = obj.vertex_groups.get(group_name)
    if temporary_group is not None:
        obj.vertex_groups.remove(temporary_group)


def _hood_folded_roll(
    pattern: ModuleType,
    sampler,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    """Create one slim, continuous upper-back cowl roll clear of the body."""
    points: list[tuple[float, float, float]] = []
    count = 41
    for index in range(count):
        lateral = 2.0 * index / (count - 1) - 1.0
        x = 0.128 * lateral
        center_weight = 1.0 - lateral * lateral
        z = 1.040 - 0.036 * center_weight
        offset = 0.074 + 0.012 * center_weight
        point = sampler.point(x, z, front=False, offset=offset)
        points.append((point.x, point.y, point.z))
    roll = pattern.v9.base.curve_tube(
        "Heather_Hood_Folded_Roll",
        points,
        0.0065,
        material,
        armature,
        "Chest",
        resolution=5,
    )
    pattern.v9.base.transfer_nearest_body_weights(roll, sampler.body)
    return roll


def install(pattern: ModuleType) -> None:
    """Install v21 behaviour into the already-imported canonical pattern module."""
    original_body_panel = pattern._body_panel

    def body_panel(
        name: str,
        body: bpy.types.Object,
        armature: bpy.types.Object,
        material: bpy.types.Material,
        predicate: PolygonPredicate,
        *,
        offset: float = SHELL_CLEARANCE_M,
        bevel_width: float = 0.0,
        preserve_volume: bool = False,
    ) -> bpy.types.Object:
        return original_body_panel(
            name,
            body,
            armature,
            material,
            predicate,
            offset=offset,
            bevel_width=bevel_width,
            preserve_volume=preserve_volume,
        )

    pattern.DESIGN_REVISION = DESIGN_REVISION
    pattern._smoothstep = _smoothstep
    pattern._highcut_width = _highcut_width
    pattern._body_shell_predicate = lambda body: _body_shell_predicate(pattern, body)
    pattern._smooth_and_project_boundaries = lambda obj, source, offset: (
        _smooth_and_project_boundaries(
            pattern,
            obj,
            source,
            offset,
        )
    )
    pattern._body_panel = body_panel
    pattern._hood_folded_roll = lambda sampler, armature, material: _hood_folded_roll(
        pattern,
        sampler,
        armature,
        material,
    )
