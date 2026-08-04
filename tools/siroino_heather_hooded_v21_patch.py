#!/usr/bin/env python3
"""Body-anchored geometry patch for the v22 Siroino bodysuit revision.

The lower-body and folded-hood changes from v21 are retained. The former
uniform Shrinkwrap reprojection is replaced by an independent Blender-mesh
adaptation of DAMA's body-anchored representation: every garment vertex is
bound to one body triangle with barycentric coordinates and a strictly
positive normal offset. This is not the authors' Gaussian implementation.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
import json
import math
from pathlib import Path
from types import ModuleType

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

DESIGN_REVISION = "v22-dama-inspired-body-anchored-shell"
SHELL_CLEARANCE_M = 0.022
MIN_ANCHOR_OFFSET_M = 0.018
MAX_ANCHOR_OFFSET_M = 0.026
OFFSET_SMOOTH_FACTOR = 0.35
OFFSET_SMOOTH_ITERATIONS = 4
RESEARCH_OUTPUT = Path(
    "Assets/GenWorks/siroino-heather-hooded-bodysuit/Research/"
    "dama-body-anchor-trial.json"
)

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


def _barycentric_coordinates(
    point: Vector,
    a: Vector,
    b: Vector,
    c: Vector,
) -> Vector:
    """Return stable barycentric coordinates for a point on one triangle."""
    v0 = b - a
    v1 = c - a
    v2 = point - a
    d00 = v0.dot(v0)
    d01 = v0.dot(v1)
    d11 = v1.dot(v1)
    d20 = v2.dot(v0)
    d21 = v2.dot(v1)
    denominator = d00 * d11 - d01 * d01
    if abs(denominator) <= 1e-16:
        return Vector((1.0, 0.0, 0.0))
    v = (d11 * d20 - d01 * d21) / denominator
    w = (d00 * d21 - d01 * d20) / denominator
    u = 1.0 - v - w
    return Vector((u, v, w))


def _source_triangles(
    source: bpy.types.Object,
) -> tuple[list[Vector], list[tuple[int, int, int]], list[Vector]]:
    """Triangulate source polygons logically while preserving their outward normals."""
    world_vertices = [source.matrix_world @ vertex.co for vertex in source.data.vertices]
    normal_matrix = source.matrix_world.to_3x3().inverted().transposed()
    triangles: list[tuple[int, int, int]] = []
    normals: list[Vector] = []
    for polygon in source.data.polygons:
        indices = list(polygon.vertices)
        if len(indices) < 3:
            continue
        normal = normal_matrix @ polygon.normal
        if normal.length_squared <= 1e-16:
            continue
        normal.normalize()
        for index in range(1, len(indices) - 1):
            triangles.append((indices[0], indices[index], indices[index + 1]))
            normals.append(normal.copy())
    if not triangles:
        raise RuntimeError("body-anchor projection requires source triangles")
    return world_vertices, triangles, normals


def _boundary_vertices(mesh: bpy.types.Mesh) -> set[int]:
    edge_use: Counter[tuple[int, int]] = Counter()
    for polygon in mesh.polygons:
        indices = list(polygon.vertices)
        for index, first in enumerate(indices):
            second = indices[(index + 1) % len(indices)]
            edge_use[tuple(sorted((first, second)))] += 1
    return {
        vertex
        for edge, count in edge_use.items()
        if count == 1
        for vertex in edge
    }


def _smooth_offsets(
    mesh: bpy.types.Mesh,
    offsets: list[float],
) -> list[float]:
    adjacency: list[set[int]] = [set() for _ in mesh.vertices]
    for edge in mesh.edges:
        first, second = edge.vertices
        adjacency[first].add(second)
        adjacency[second].add(first)
    fixed = _boundary_vertices(mesh)
    values = list(offsets)
    for _ in range(OFFSET_SMOOTH_ITERATIONS):
        updated = list(values)
        for index, neighbours in enumerate(adjacency):
            if index in fixed or not neighbours:
                continue
            neighbour_mean = sum(values[item] for item in neighbours) / len(neighbours)
            updated[index] = (
                (1.0 - OFFSET_SMOOTH_FACTOR) * values[index]
                + OFFSET_SMOOTH_FACTOR * neighbour_mean
            )
        values = updated
    return [
        min(MAX_ANCHOR_OFFSET_M, max(MIN_ANCHOR_OFFSET_M, value))
        for value in values
    ]


def _replace_point_attribute(
    mesh: bpy.types.Mesh,
    name: str,
    data_type: str,
    values: list[int] | list[float] | list[Vector],
) -> None:
    existing = mesh.attributes.get(name)
    if existing is not None:
        mesh.attributes.remove(existing)
    attribute = mesh.attributes.new(name=name, type=data_type, domain="POINT")
    if data_type == "FLOAT_VECTOR":
        for item, value in zip(attribute.data, values, strict=True):
            item.vector = value
    else:
        for item, value in zip(attribute.data, values, strict=True):
            item.value = value


def _write_research_trial(metrics: dict[str, object]) -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / RESEARCH_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "status": "EXECUTED",
        "executedAt": "2026-08-05",
        "method": "DAMA-inspired body-anchored triangle projection",
        "paper": {
            "title": (
                "DAMA: Disentangled Body-Anchored Gaussians for Controllable "
                "Multi-Layered Avatars"
            ),
            "url": "https://arxiv.org/abs/2605.21001",
            "projectUrl": "https://danieleskandar.github.io/dama/",
            "officialCodeUrl": "https://github.com/danieleskandar/DAMA-code",
            "publication": "CVPR 2026 PhysHuman Workshop",
        },
        "implementation": {
            "kind": "independent Blender mesh adaptation",
            "authorsImplementationExecuted": False,
            "copiedFromOfficialCode": False,
            "representation": [
                "body triangle index",
                "barycentric in-plane coordinates",
                "strictly positive body-normal offset",
            ],
            "scope": (
                "one-time neutral-mesh correction before inherited Siroino skinning; "
                "actual pose renders remain the acceptance evidence"
            ),
        },
        "parameters": {
            "minimumOffsetM": MIN_ANCHOR_OFFSET_M,
            "maximumOffsetM": MAX_ANCHOR_OFFSET_M,
            "offsetSmoothingFactor": OFFSET_SMOOTH_FACTOR,
            "offsetSmoothingIterations": OFFSET_SMOOTH_ITERATIONS,
        },
        "metrics": metrics,
        "acceptance": {
            "researchTrial": "PASS",
            "visualAppearanceReview": (
                "PENDING until current five-view and required-pose images are opened"
            ),
        },
    }
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _body_anchor_project(
    obj: bpy.types.Object,
    source: bpy.types.Object,
) -> dict[str, object]:
    """Bind every garment vertex to a body triangle and enforce positive clearance."""
    world_vertices, triangles, source_normals = _source_triangles(source)
    tree = BVHTree.FromPolygons(world_vertices, triangles, all_triangles=True)
    inverse = obj.matrix_world.inverted_safe()

    triangle_indices: list[int] = []
    barycentric: list[Vector] = []
    anchor_points: list[Vector] = []
    anchor_normals: list[Vector] = []
    raw_offsets: list[float] = []
    original_points: list[Vector] = []

    for vertex in obj.data.vertices:
        current = obj.matrix_world @ vertex.co
        nearest = tree.find_nearest(current)
        if nearest is None:
            raise RuntimeError(f"body anchor not found for garment vertex {vertex.index}")
        location, _tree_normal, triangle_index, _distance = nearest
        if triangle_index is None or triangle_index < 0:
            raise RuntimeError(f"body triangle not found for garment vertex {vertex.index}")
        a_index, b_index, c_index = triangles[triangle_index]
        normal = source_normals[triangle_index]
        signed_offset = (current - location).dot(normal)
        if not math.isfinite(signed_offset):
            raise RuntimeError(f"non-finite body offset at garment vertex {vertex.index}")
        bounded_offset = min(
            MAX_ANCHOR_OFFSET_M,
            max(MIN_ANCHOR_OFFSET_M, signed_offset),
        )
        triangle_indices.append(int(triangle_index))
        barycentric.append(
            _barycentric_coordinates(
                location,
                world_vertices[a_index],
                world_vertices[b_index],
                world_vertices[c_index],
            )
        )
        anchor_points.append(location.copy())
        anchor_normals.append(normal.copy())
        raw_offsets.append(bounded_offset)
        original_points.append(current)

    smoothed_offsets = _smooth_offsets(obj.data, raw_offsets)
    corrections: list[float] = []
    for index, vertex in enumerate(obj.data.vertices):
        target = anchor_points[index] + anchor_normals[index] * smoothed_offsets[index]
        corrections.append((target - original_points[index]).length)
        vertex.co = inverse @ target

    _replace_point_attribute(
        obj.data,
        "body_anchor_triangle",
        "INT",
        triangle_indices,
    )
    _replace_point_attribute(
        obj.data,
        "body_anchor_barycentric",
        "FLOAT_VECTOR",
        barycentric,
    )
    _replace_point_attribute(
        obj.data,
        "body_anchor_offset_m",
        "FLOAT",
        smoothed_offsets,
    )
    _replace_point_attribute(
        obj.data,
        "body_anchor_correction_m",
        "FLOAT",
        corrections,
    )
    obj.data.update()

    corrected = sum(value > 1e-6 for value in corrections)
    metrics: dict[str, object] = {
        "object": obj.name,
        "vertexCount": len(obj.data.vertices),
        "sourceTriangleCount": len(triangles),
        "correctedVertexCount": corrected,
        "minimumFinalOffsetM": min(smoothed_offsets, default=0.0),
        "maximumFinalOffsetM": max(smoothed_offsets, default=0.0),
        "meanCorrectionM": (
            sum(corrections) / len(corrections) if corrections else 0.0
        ),
        "maximumCorrectionM": max(corrections, default=0.0),
        "allOffsetsStrictlyPositive": all(value > 0.0 for value in smoothed_offsets),
    }
    obj["bodyAnchorMethod"] = "DAMA-inspired barycentric positive-normal-offset"
    obj["bodyAnchorMetrics"] = json.dumps(metrics, sort_keys=True)
    _write_research_trial(metrics)
    return metrics


def _smooth_and_project_boundaries(
    pattern: ModuleType,
    obj: bpy.types.Object,
    source: bpy.types.Object,
    offset: float,
) -> None:
    """Relax four opening rings, then body-anchor the complete shell."""
    weights = pattern._boundary_vertex_weights(obj.data)
    if weights:
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

        temporary_group = obj.vertex_groups.get(group_name)
        if temporary_group is not None:
            obj.vertex_groups.remove(temporary_group)

    if abs(offset - SHELL_CLEARANCE_M) > 1e-9:
        raise RuntimeError(
            f"body-anchor trial expects {SHELL_CLEARANCE_M:.3f} m clearance, got {offset:.3f}"
        )
    _body_anchor_project(obj, source)


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
    """Install v22 behaviour into the already-imported canonical pattern module."""
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
