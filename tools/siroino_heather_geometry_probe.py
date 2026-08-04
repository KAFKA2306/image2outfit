#!/usr/bin/env python3
"""Geometry diagnostics for hosted Siroino Blender audits.

The probe records where evaluated garment/body overlap pairs occur and which
skin-weight regions own those garment polygons. It also records primary-shell
boundary loops so lower-body and sleeve selection can be revised from measured
geometry rather than guessed world-coordinate thresholds.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from statistics import median

import bpy
from mathutils import Vector

VOXEL_M = 0.05


def _vector(value: Vector, digits: int = 6) -> list[float]:
    return [round(float(axis), digits) for axis in value]


def _bounds(points: Iterable[Vector]) -> dict[str, list[float]] | None:
    values = list(points)
    if not values:
        return None
    minimum = Vector(
        (
            min(point.x for point in values),
            min(point.y for point in values),
            min(point.z for point in values),
        )
    )
    maximum = Vector(
        (
            max(point.x for point in values),
            max(point.y for point in values),
            max(point.z for point in values),
        )
    )
    return {"min": _vector(minimum), "max": _vector(maximum)}


def _quantiles(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)

    def percentile(fraction: float) -> float:
        index = fraction * (len(ordered) - 1)
        lower = int(index)
        upper = min(lower + 1, len(ordered) - 1)
        weight = index - lower
        return ordered[lower] * (1.0 - weight) + ordered[upper] * weight

    return {
        "min": round(ordered[0], 6),
        "p10": round(percentile(0.10), 6),
        "median": round(float(median(ordered)), 6),
        "p90": round(percentile(0.90), 6),
        "max": round(ordered[-1], 6),
    }


def _weight_summary(
    obj: bpy.types.Object,
    vertex_indices: Iterable[int],
    *,
    limit: int = 10,
) -> list[dict[str, float | str]]:
    totals: Counter[str] = Counter()
    count = 0
    for vertex_index in set(vertex_indices):
        if vertex_index >= len(obj.data.vertices):
            continue
        count += 1
        for assignment in obj.data.vertices[vertex_index].groups:
            if assignment.group >= len(obj.vertex_groups):
                continue
            totals[obj.vertex_groups[assignment.group].name] += float(assignment.weight)
    if count == 0:
        return []
    return [
        {"group": group, "meanWeight": round(total / count, 6)}
        for group, total in totals.most_common(limit)
    ]


def _dominant_group(obj: bpy.types.Object, polygon_index: int) -> str:
    if polygon_index >= len(obj.data.polygons):
        return "out-of-range"
    polygon = obj.data.polygons[polygon_index]
    summary = _weight_summary(obj, polygon.vertices, limit=1)
    return str(summary[0]["group"]) if summary else "unweighted"


def _evaluated_polygon_centers(
    obj: bpy.types.Object,
    depsgraph: bpy.types.Depsgraph,
) -> tuple[bpy.types.Object, bpy.types.Mesh, list[Vector]]:
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
    matrix = evaluated.matrix_world
    centers = [matrix @ polygon.center for polygon in mesh.polygons]
    return evaluated, mesh, centers


def overlap_diagnostics(
    garment: bpy.types.Object,
    overlaps: list[tuple[int, int]],
    armature: bpy.types.Object,
    depsgraph: bpy.types.Depsgraph,
) -> dict:
    """Summarize exact overlap pairs in root-local 5 cm spatial voxels."""
    evaluated, mesh, centers = _evaluated_polygon_centers(garment, depsgraph)
    try:
        inverse_root = armature.matrix_world.inverted_safe()
        pair_centers: list[Vector] = []
        polygon_indices: list[int] = []
        invalid_indices = 0
        voxel_pairs: Counter[tuple[int, int, int]] = Counter()
        voxel_polygons: defaultdict[tuple[int, int, int], set[int]] = defaultdict(set)
        group_pairs: Counter[str] = Counter()

        for _, garment_polygon_index in overlaps:
            if garment_polygon_index >= len(centers):
                invalid_indices += 1
                continue
            local = inverse_root @ centers[garment_polygon_index]
            pair_centers.append(local)
            polygon_indices.append(garment_polygon_index)
            voxel = tuple(round(axis / VOXEL_M) for axis in local)
            voxel_pairs[voxel] += 1
            voxel_polygons[voxel].add(garment_polygon_index)
            group_pairs[_dominant_group(garment, garment_polygon_index)] += 1

        top_voxels = []
        for voxel, pair_count in voxel_pairs.most_common(20):
            indices = voxel_polygons[voxel]
            points = [
                inverse_root @ centers[index]
                for index in indices
                if index < len(centers)
            ]
            top_voxels.append(
                {
                    "voxelCenter": [round(axis * VOXEL_M, 4) for axis in voxel],
                    "overlapPairs": pair_count,
                    "uniqueGarmentPolygons": len(indices),
                    "bounds": _bounds(points),
                    "topWeights": _weight_summary(
                        garment,
                        (
                            vertex
                            for index in indices
                            if index < len(garment.data.polygons)
                            for vertex in garment.data.polygons[index].vertices
                        ),
                    ),
                }
            )

        unique_indices = set(polygon_indices)
        return {
            "overlapPairs": len(overlaps),
            "mappedPairs": len(pair_centers),
            "invalidPolygonIndices": invalid_indices,
            "uniqueGarmentPolygons": len(unique_indices),
            "rootLocalBounds": _bounds(pair_centers),
            "rootLocalQuantiles": {
                "x": _quantiles([point.x for point in pair_centers]),
                "y": _quantiles([point.y for point in pair_centers]),
                "z": _quantiles([point.z for point in pair_centers]),
            },
            "dominantGroupPairs": [
                {"group": group, "overlapPairs": count}
                for group, count in group_pairs.most_common(15)
            ],
            "topVoxels": top_voxels,
        }
    finally:
        evaluated.to_mesh_clear()


def _boundary_loops(obj: bpy.types.Object, armature: bpy.types.Object) -> list[dict]:
    edge_use: Counter[tuple[int, int]] = Counter()
    for polygon in obj.data.polygons:
        vertices = list(polygon.vertices)
        for index, left in enumerate(vertices):
            right = vertices[(index + 1) % len(vertices)]
            edge_use[tuple(sorted((left, right)))] += 1
    boundary_edges = [edge for edge, count in edge_use.items() if count == 1]
    adjacency: defaultdict[int, set[int]] = defaultdict(set)
    for left, right in boundary_edges:
        adjacency[left].add(right)
        adjacency[right].add(left)

    inverse_root = armature.matrix_world.inverted_safe()
    remaining = set(adjacency)
    loops: list[dict] = []
    while remaining:
        start = remaining.pop()
        component = {start}
        stack = [start]
        while stack:
            current = stack.pop()
            neighbours = adjacency[current] & remaining
            remaining.difference_update(neighbours)
            component.update(neighbours)
            stack.extend(neighbours)

        local_points = [
            inverse_root @ (obj.matrix_world @ obj.data.vertices[index].co)
            for index in component
        ]
        edge_length = sum(
            (
                obj.matrix_world @ obj.data.vertices[left].co
                - obj.matrix_world @ obj.data.vertices[right].co
            ).length
            for left, right in boundary_edges
            if left in component and right in component
        )
        center = sum(local_points, Vector((0.0, 0.0, 0.0))) / max(
            len(local_points), 1
        )
        loops.append(
            {
                "vertexCount": len(component),
                "edgeCount": sum(
                    1
                    for left, right in boundary_edges
                    if left in component and right in component
                ),
                "lengthM": round(float(edge_length), 6),
                "rootLocalCenter": _vector(center),
                "rootLocalBounds": _bounds(local_points),
                "topWeights": _weight_summary(obj, component),
            }
        )
    return sorted(loops, key=lambda item: item["rootLocalCenter"][2], reverse=True)


def static_geometry_diagnostics(
    body: bpy.types.Object,
    garments: list[bpy.types.Object],
    armature: bpy.types.Object,
) -> dict:
    shell = next(
        (garment for garment in garments if garment.name == "Heather_Body_Shell"),
        None,
    )
    if shell is None:
        raise RuntimeError("Geometry probe could not find Heather_Body_Shell")
    inverse_root = armature.matrix_world.inverted_safe()

    def object_bounds(obj: bpy.types.Object) -> dict[str, list[float]] | None:
        return _bounds(
            inverse_root @ (obj.matrix_world @ vertex.co)
            for vertex in obj.data.vertices
        )

    return {
        "body": {
            "object": body.name,
            "vertices": len(body.data.vertices),
            "polygons": len(body.data.polygons),
            "rootLocalBounds": object_bounds(body),
            "vertexGroups": [group.name for group in body.vertex_groups],
        },
        "shell": {
            "object": shell.name,
            "vertices": len(shell.data.vertices),
            "polygons": len(shell.data.polygons),
            "rootLocalBounds": object_bounds(shell),
            "boundaryLoops": _boundary_loops(shell, armature),
            "allVertexTopWeights": _weight_summary(
                shell,
                range(len(shell.data.vertices)),
                limit=20,
            ),
        },
    }
