#!/usr/bin/env python3
"""Semantic five-opening refinement for the Siroino hooded bodysuit.

This revision keeps the v19 evaluated-source shell pipeline, but replaces the
area-only complement ranking with anatomical opening classification. The lower
high-cut strip is extended through the crotch so the lower complement splits
into independent left and right leg openings. Any remaining complement
component is restored from source topology. Rendering is blocked unless the
result is one connected shell with exactly five boundary loops.
"""

from __future__ import annotations

from collections.abc import Callable

import bpy
from mathutils import Vector

import siroino_heather_hooded_pattern_v13 as v13

DESIGN_REVISION = "v20-semantic-five-opening-highcut-shell"
clean_meshes = v13.clean_meshes
bone_segment = v13.bone_segment

PolygonPredicate = Callable[[bpy.types.MeshPolygon, Vector], bool]

_ORIGINAL_BODY_PANEL = v13._body_panel
_ORIGINAL_VALIDATE_GEOMETRY = v13._validate_geometry


def _component_center(
    body: bpy.types.Object,
    component: set[int],
) -> Vector:
    weighted = Vector((0.0, 0.0, 0.0))
    total_area = 0.0
    for index in component:
        polygon = body.data.polygons[index]
        area = max(float(polygon.area), 1e-12)
        weighted += (body.matrix_world @ polygon.center) * area
        total_area += area
    return weighted / max(total_area, 1e-12)


def _opening_components(
    body: bpy.types.Object,
    selected_indices: set[int],
) -> list[dict[str, object]]:
    adjacency = v13._polygon_adjacency(body.data)
    remaining = set(adjacency) - selected_indices
    components: list[dict[str, object]] = []

    while remaining:
        component = {remaining.pop()}
        stack = list(component)
        while stack:
            current = stack.pop()
            neighbours = adjacency[current] & remaining
            remaining.difference_update(neighbours)
            component.update(neighbours)
            stack.extend(neighbours)

        boundary_links = sum(
            len(adjacency[index] & selected_indices) for index in component
        )
        if boundary_links == 0:
            continue
        components.append(
            {
                "faces": component,
                "area": sum(body.data.polygons[index].area for index in component),
                "boundaryLinks": boundary_links,
                "center": _component_center(body, component),
            }
        )
    return components


def _pick_side_component(
    components: list[dict[str, object]],
    excluded: set[int],
    *,
    sign: float,
    role: str,
) -> int:
    candidates: list[tuple[float, int]] = []
    for index, component in enumerate(components):
        if index in excluded:
            continue
        center = component["center"]
        assert isinstance(center, Vector)
        signed_x = sign * center.x
        if role == "wrist" and signed_x >= 0.18:
            candidates.append((signed_x, index))
        elif role == "leg" and signed_x >= 0.015 and center.z <= 0.72:
            candidates.append((-center.z, index))
    if not candidates:
        raise RuntimeError(
            f"Semantic opening classification could not find {role} on x-sign {sign:+.0f}"
        )
    candidates.sort(reverse=True)
    return candidates[0][1]


def _close_unintended_openings(
    body: bpy.types.Object,
    selected: list[bpy.types.MeshPolygon],
    intended_openings: int = 5,
) -> list[bpy.types.MeshPolygon]:
    """Retain neck, two wrists and two legs; restore every other complement."""
    if intended_openings != 5:
        raise ValueError("The bodysuit contract requires exactly five openings")

    selected_indices = {polygon.index for polygon in selected}
    components = _opening_components(body, selected_indices)
    if len(components) < intended_openings:
        raise RuntimeError(
            "Semantic opening classification requires at least five adjacent "
            f"complement components, found {len(components)}"
        )

    neck_candidates = [
        (component["center"].z, index)
        for index, component in enumerate(components)
        if isinstance(component["center"], Vector)
        and component["center"].z >= 0.95
    ]
    if not neck_candidates:
        raise RuntimeError("Semantic opening classification could not find the neck")
    neck_index = max(neck_candidates)[1]

    retained = {neck_index}
    retained.add(
        _pick_side_component(components, retained, sign=-1.0, role="wrist")
    )
    retained.add(
        _pick_side_component(components, retained, sign=1.0, role="wrist")
    )
    retained.add(_pick_side_component(components, retained, sign=-1.0, role="leg"))
    retained.add(_pick_side_component(components, retained, sign=1.0, role="leg"))

    if len(retained) != intended_openings:
        raise RuntimeError(
            "Semantic opening classification did not produce five unique components"
        )

    restored_indices = {
        face
        for index, component in enumerate(components)
        if index not in retained
        for face in component["faces"]
    }
    selected_indices.update(restored_indices)

    summary = []
    for index, component in enumerate(components):
        center = component["center"]
        assert isinstance(center, Vector)
        summary.append(
            f"{index}:x={center.x:.3f},z={center.z:.3f},"
            f"area={float(component['area']):.4f},"
            f"links={int(component['boundaryLinks'])},"
            f"retained={index in retained}"
        )
    print(
        "Healed unintended garment openings semantically: "
        f"retained={len(retained)}, closed={len(components) - len(retained)}, "
        f"restoredFaces={len(restored_indices)}; " + " | ".join(summary)
    )
    return [body.data.polygons[index] for index in sorted(selected_indices)]


def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def _highcut_width(z: float) -> float:
    """Join a narrow crotch bridge continuously into the lower torso shell."""
    t = (z - 0.600) / (0.850 - 0.600)
    return 0.032 + 0.133 * _smoothstep(t)


def _body_shell_predicate(body: bpy.types.Object) -> PolygonPredicate:
    arm_groups = {
        side: (
            v13.v9._group_index(body, f"UpperArm_{side}"),
            v13.v9._group_index(body, f"LowerArm_{side}"),
            v13.v9._group_index(body, f"Hand_{side}"),
        )
        for side in ("L", "R")
    }

    def selected(
        polygon: bpy.types.MeshPolygon,
        center: Vector,
    ) -> bool:
        x = abs(center.x)
        torso = 0.815 <= center.z <= v13._torso_top(center.x) and x <= v13._torso_width(
            center.z
        )
        highcut = 0.600 <= center.z <= 0.850 and x <= _highcut_width(center.z)
        if torso or highcut:
            return True

        for upper, lower, hand in arm_groups.values():
            upper_weight = v13.v9._polygon_average_weight(body, polygon, (upper,))
            lower_weight = v13.v9._polygon_average_weight(body, polygon, (lower,))
            hand_weight = v13.v9._polygon_average_weight(body, polygon, (hand,))
            arm_weight = upper_weight + lower_weight
            if hand_weight <= 0.52 and arm_weight >= 0.008:
                return True
            if center.z >= 0.900 and upper_weight >= 0.002:
                return True
        return False

    return selected


def _body_panel(
    name: str,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    predicate: PolygonPredicate,
    *,
    offset: float = 0.012,
    bevel_width: float = 0.0,
    preserve_volume: bool = False,
) -> bpy.types.Object:
    return _ORIGINAL_BODY_PANEL(
        name,
        body,
        armature,
        material,
        predicate,
        offset=offset,
        bevel_width=bevel_width,
        preserve_volume=preserve_volume,
    )


def _hood_folded_roll(
    sampler: v13.v9.SurfaceSampler,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    points: list[tuple[float, float, float]] = []
    count = 33
    for index in range(count):
        lateral = 2.0 * index / (count - 1) - 1.0
        x = 0.095 * lateral
        center_weight = 1.0 - lateral * lateral
        z = 1.022 - 0.030 * center_weight
        offset = 0.046 + 0.010 * center_weight
        point = sampler.point(x, z, front=False, offset=offset)
        points.append((point.x, point.y, point.z))
    roll = v13.v9.base.curve_tube(
        "Heather_Hood_Folded_Roll",
        points,
        0.0095,
        material,
        armature,
        "Chest",
        resolution=5,
    )
    v13.v9.base.transfer_nearest_body_weights(roll, sampler.body)
    return roll


def _validate_geometry(objects: list[bpy.types.Object]) -> None:
    _ORIGINAL_VALIDATE_GEOMETRY(objects)
    shell = next(
        (obj for obj in objects if obj.name == "Heather_Body_Shell"),
        None,
    )
    if shell is None:
        raise RuntimeError("Garment geometry sanity gate found no primary shell")
    boundary_loops, boundary_edges = v13._boundary_metrics(shell)
    if boundary_loops != 5:
        raise RuntimeError(
            "Garment geometry sanity gate failed: Heather_Body_Shell must have "
            f"exactly five anatomical openings, found {boundary_loops} "
            f"boundary loops ({boundary_edges} edges)"
        )


v13._close_unintended_openings = _close_unintended_openings
v13._body_shell_predicate = _body_shell_predicate
v13._body_panel = _body_panel
v13._hood_folded_roll = _hood_folded_roll
v13._validate_geometry = _validate_geometry

create_outfit = v13.create_outfit
