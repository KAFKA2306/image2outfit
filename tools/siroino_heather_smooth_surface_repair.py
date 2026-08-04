#!/usr/bin/env python3
"""Repair micro holes, faceting and high-cut silhouette after LoBoFit.

The repair operates on the actual generated Blender meshes. It closes only
micro boundary loops, reprojects the primary shell through barycentrically
interpolated body normals, raises the central underbody into a bounded high-cut
profile, and narrows the folded hood roll. Measured results are written for
render review; this module does not declare visual completion.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

DESIGN_REVISION = "v24-smooth-normal-highcut-repair"
CLEARANCE_M = 0.022
REPAIR_MAX_WORLD_STEP_M = 0.095
REPAIR_DEFAULT_WORLD_STEP_M = 0.030
HIGHCUT_CENTER_FLOOR_M = 0.600
HIGHCUT_SIDE_FLOOR_M = 0.760
HIGHCUT_CENTER_HALF_WIDTH_M = 0.022
HIGHCUT_OUTER_HALF_WIDTH_M = 0.165
HIGHCUT_MAX_LIFT_M = 0.090
HIGHCUT_SMOOTH_ITERATIONS = 5
HIGHCUT_SMOOTH_FACTOR = 0.35
HOOD_LATERAL_SCALE = 0.72
MICRO_HOLE_MAX_EDGES = 8
MICRO_HOLE_MAX_PERIMETER_M = 0.010

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = (
    ROOT
    / "Assets"
    / "GenWorks"
    / "siroino-heather-hooded-bodysuit"
    / "Research"
    / "smooth-normal-highcut-repair-trial.json"
)


def _statistics(values: list[float]) -> dict[str, float]:
    if not values:
        return {"minimum": 0.0, "mean": 0.0, "maximum": 0.0}
    return {
        "minimum": min(values),
        "mean": sum(values) / len(values),
        "maximum": max(values),
    }


def _adjacency(mesh: bpy.types.Mesh) -> dict[int, set[int]]:
    result = {vertex.index: set() for vertex in mesh.vertices}
    for edge in mesh.edges:
        left, right = edge.vertices
        result[left].add(right)
        result[right].add(left)
    return result


def _boundary_vertices(mesh: bpy.types.Mesh) -> set[int]:
    usage: Counter[tuple[int, int]] = Counter()
    for polygon in mesh.polygons:
        vertices = list(polygon.vertices)
        for index, left in enumerate(vertices):
            right = vertices[(index + 1) % len(vertices)]
            usage[tuple(sorted((left, right)))] += 1
    return {vertex for edge, count in usage.items() if count == 1 for vertex in edge}


def _topology_metrics(mesh: bpy.types.Mesh) -> dict[str, int]:
    adjacency = _adjacency(mesh)
    remaining = set(adjacency)
    components = 0
    while remaining:
        components += 1
        stack = [remaining.pop()]
        while stack:
            neighbours = adjacency[stack.pop()] & remaining
            remaining.difference_update(neighbours)
            stack.extend(neighbours)

    edge_use: Counter[tuple[int, int]] = Counter()
    for polygon in mesh.polygons:
        vertices = list(polygon.vertices)
        for index, left in enumerate(vertices):
            right = vertices[(index + 1) % len(vertices)]
            edge_use[tuple(sorted((left, right)))] += 1
    boundary_edges = [edge for edge, count in edge_use.items() if count == 1]
    boundary_adjacency: dict[int, set[int]] = {}
    for left, right in boundary_edges:
        boundary_adjacency.setdefault(left, set()).add(right)
        boundary_adjacency.setdefault(right, set()).add(left)
    boundary_remaining = set(boundary_adjacency)
    loops = 0
    while boundary_remaining:
        loops += 1
        stack = [boundary_remaining.pop()]
        while stack:
            neighbours = boundary_adjacency[stack.pop()] & boundary_remaining
            boundary_remaining.difference_update(neighbours)
            stack.extend(neighbours)
    return {
        "connectedComponents": components,
        "boundaryLoops": loops,
        "boundaryEdges": len(boundary_edges),
    }


def _fill_tiny_boundary_holes(obj: bpy.types.Object) -> dict[str, Any]:
    """Close only non-anatomical micro holes using existing boundary vertices."""
    mesh = obj.data
    before = _topology_metrics(mesh)
    bm = bmesh.new()
    filled: list[dict[str, Any]] = []
    try:
        bm.from_mesh(mesh)
        boundary_edges = [edge for edge in bm.edges if edge.is_boundary]
        remaining = set(boundary_edges)
        components: list[list[bmesh.types.BMEdge]] = []
        while remaining:
            first = remaining.pop()
            component = [first]
            frontier = [first]
            while frontier:
                edge = frontier.pop()
                linked = {
                    candidate
                    for vertex in edge.verts
                    for candidate in vertex.link_edges
                    if candidate.is_boundary and candidate in remaining
                }
                remaining.difference_update(linked)
                component.extend(linked)
                frontier.extend(linked)
            components.append(component)

        for component in components:
            vertices = {vertex for edge in component for vertex in edge.verts}
            perimeter = sum(
                (
                    obj.matrix_world @ edge.verts[0].co
                    - obj.matrix_world @ edge.verts[1].co
                ).length
                for edge in component
            )
            if (
                len(component) > MICRO_HOLE_MAX_EDGES
                or len(vertices) > MICRO_HOLE_MAX_EDGES
                or perimeter > MICRO_HOLE_MAX_PERIMETER_M
            ):
                continue
            result = bmesh.ops.holes_fill(
                bm,
                edges=component,
                sides=MICRO_HOLE_MAX_EDGES,
            )
            faces = list(result.get("faces", []))
            if not faces:
                raise RuntimeError(
                    "Micro-hole repair found a tiny boundary but created no face"
                )
            bmesh.ops.recalc_face_normals(bm, faces=faces)
            filled.append(
                {
                    "edgeCount": len(component),
                    "vertexCount": len(vertices),
                    "perimeterM": float(perimeter),
                    "faceCount": len(faces),
                }
            )

        if filled:
            bm.normal_update()
            bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update(calc_edges=True)
    after = _topology_metrics(mesh)
    if before["connectedComponents"] != after["connectedComponents"]:
        raise RuntimeError(
            "Micro-hole repair changed connected-component count: "
            f"before={before}, after={after}"
        )
    if after["boundaryLoops"] != before["boundaryLoops"] - len(filled):
        raise RuntimeError(
            "Micro-hole repair did not remove one loop per filled hole: "
            f"before={before}, after={after}, filled={filled}"
        )
    return {
        "method": (
            "Blender BMesh holes_fill on boundary loops with at most eight edges "
            "and at most 10 mm world-space perimeter"
        ),
        "topologyBefore": before,
        "topologyAfter": after,
        "filledHoleCount": len(filled),
        "filledHoles": filled,
    }


def _barycentric_coordinates(
    point: Vector,
    a: Vector,
    b: Vector,
    c: Vector,
) -> Vector:
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
    return Vector((1.0 - v - w, v, w))


class _SmoothBodySampler:
    def __init__(self, body: bpy.types.Object) -> None:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = body.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
        try:
            matrix = evaluated.matrix_world.copy()
            normal_matrix = matrix.to_3x3().inverted().transposed()
            self.vertices = [matrix @ vertex.co for vertex in mesh.vertices]
            self.normals = []
            for vertex in mesh.vertices:
                normal = normal_matrix @ vertex.normal
                if normal.length_squared <= 1e-16:
                    normal = Vector((0.0, 0.0, 1.0))
                else:
                    normal.normalize()
                self.normals.append(normal)
            mesh.calc_loop_triangles()
            self.triangles = [
                tuple(int(index) for index in triangle.vertices)
                for triangle in mesh.loop_triangles
            ]
        finally:
            evaluated.to_mesh_clear()
        if not self.triangles:
            raise RuntimeError("Smooth-normal repair requires evaluated body triangles")
        self.tree = BVHTree.FromPolygons(
            self.vertices,
            self.triangles,
            all_triangles=True,
        )

    def nearest(self, point: Vector) -> tuple[Vector, Vector]:
        nearest = self.tree.find_nearest(point)
        if nearest is None:
            raise RuntimeError("Smooth-normal repair could not sample the target body")
        location, _face_normal, triangle_index, _distance = nearest
        if triangle_index is None or triangle_index < 0:
            raise RuntimeError("Smooth-normal repair received no target triangle")
        first, second, third = self.triangles[triangle_index]
        barycentric = _barycentric_coordinates(
            location,
            self.vertices[first],
            self.vertices[second],
            self.vertices[third],
        )
        normal = (
            self.normals[first] * barycentric.x
            + self.normals[second] * barycentric.y
            + self.normals[third] * barycentric.z
        )
        if normal.length_squared <= 1e-16:
            normal = (self.vertices[second] - self.vertices[first]).cross(
                self.vertices[third] - self.vertices[first]
            )
        if normal.length_squared <= 1e-16:
            raise RuntimeError("Smooth-normal repair received a degenerate normal")
        normal.normalize()
        return location, normal


def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def _highcut_floor(x: float) -> float:
    fraction = (abs(x) - HIGHCUT_CENTER_HALF_WIDTH_M) / (
        HIGHCUT_OUTER_HALF_WIDTH_M - HIGHCUT_CENTER_HALF_WIDTH_M
    )
    return HIGHCUT_CENTER_FLOOR_M + (
        HIGHCUT_SIDE_FLOOR_M - HIGHCUT_CENTER_FLOOR_M
    ) * _smoothstep(fraction)


def _residual_edge_rms(
    residuals: list[Vector],
    adjacency: dict[int, set[int]],
) -> float:
    total = 0.0
    count = 0
    for left, neighbours in adjacency.items():
        for right in neighbours:
            if right <= left:
                continue
            total += (residuals[left] - residuals[right]).length_squared
            count += 1
    return math.sqrt(total / max(count, 1))


def _recalculate_normals(obj: bpy.types.Object) -> None:
    mesh = obj.data
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.normal_update()
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update(calc_edges=True)


def repair_shell_surface(
    shell: bpy.types.Object,
    body: bpy.types.Object,
    armature: bpy.types.Object,
) -> dict[str, Any]:
    """Repair micro holes, flat-normal faceting and the low crotch tail."""
    tiny_hole_repair = _fill_tiny_boundary_holes(shell)
    before_topology = _topology_metrics(shell.data)
    if before_topology["connectedComponents"] != 1:
        raise RuntimeError("Surface repair requires one connected primary shell")
    if before_topology["boundaryLoops"] != 5:
        raise RuntimeError(
            "Surface repair requires five anatomical openings after micro-hole closure; "
            f"topology={before_topology}"
        )

    sampler = _SmoothBodySampler(body)
    adjacency = _adjacency(shell.data)
    boundary = _boundary_vertices(shell.data)
    inverse_root = armature.matrix_world.inverted_safe()
    root_matrix = armature.matrix_world.copy()
    inverse_object = shell.matrix_world.inverted_safe()
    original_world = [shell.matrix_world @ vertex.co for vertex in shell.data.vertices]
    local_points = [inverse_root @ point for point in original_world]

    raw_lifts: list[float] = []
    repair_zone: list[bool] = []
    for local in local_points:
        active = abs(local.x) <= HIGHCUT_OUTER_HALF_WIDTH_M and local.z < 0.835
        repair_zone.append(active)
        if not active:
            raw_lifts.append(0.0)
            continue
        target = _highcut_floor(local.x)
        raw_lifts.append(min(HIGHCUT_MAX_LIFT_M, max(0.0, target - local.z)))

    lifts = list(raw_lifts)
    for _iteration in range(HIGHCUT_SMOOTH_ITERATIONS):
        updated = list(lifts)
        for index, neighbours in adjacency.items():
            if index in boundary or not repair_zone[index] or not neighbours:
                continue
            neighbour_mean = sum(lifts[item] for item in neighbours) / len(neighbours)
            updated[index] = (1.0 - HIGHCUT_SMOOTH_FACTOR) * raw_lifts[
                index
            ] + HIGHCUT_SMOOTH_FACTOR * neighbour_mean
        lifts = updated

    before_residuals: list[Vector] = []
    after_residuals: list[Vector] = []
    displacements: list[float] = []
    signed_clearances: list[float] = []
    capped = 0
    lifted = 0

    for index, vertex in enumerate(shell.data.vertices):
        original = original_world[index]
        original_anchor, original_normal = sampler.nearest(original)
        if (original - original_anchor).dot(original_normal) < 0.0:
            original_normal = -original_normal
        before_residuals.append(original - original_anchor)

        query_local = local_points[index].copy()
        query_local.z += lifts[index]
        if lifts[index] > 1e-8:
            lifted += 1
        query = root_matrix @ query_local
        anchor, normal = sampler.nearest(query)
        if (original - anchor).dot(normal) < 0.0:
            normal = -normal
        candidate = anchor + normal * CLEARANCE_M
        delta = candidate - original
        limit = (
            REPAIR_MAX_WORLD_STEP_M
            if repair_zone[index]
            else REPAIR_DEFAULT_WORLD_STEP_M
        )
        if delta.length > limit:
            delta.normalize()
            delta *= limit
            candidate = original + delta
            capped += 1
        vertex.co = inverse_object @ candidate
        displacements.append(delta.length)
        residual = candidate - anchor
        after_residuals.append(residual)
        signed_clearances.append(residual.dot(normal))

    _recalculate_normals(shell)
    after_topology = _topology_metrics(shell.data)
    if after_topology != before_topology:
        raise RuntimeError(
            "Surface reprojection changed topology: "
            f"before={before_topology}, after={after_topology}"
        )

    return {
        "method": (
            "micro-hole closure followed by barycentric smooth-normal body "
            "reprojection with bounded high-cut lift"
        ),
        "tinyHoleRepair": tiny_hole_repair,
        "parameters": {
            "clearanceM": CLEARANCE_M,
            "defaultMaximumWorldStepM": REPAIR_DEFAULT_WORLD_STEP_M,
            "highcutMaximumWorldStepM": REPAIR_MAX_WORLD_STEP_M,
            "highcutCenterFloorM": HIGHCUT_CENTER_FLOOR_M,
            "highcutSideFloorM": HIGHCUT_SIDE_FLOOR_M,
            "highcutMaximumLiftM": HIGHCUT_MAX_LIFT_M,
            "highcutSmoothingIterations": HIGHCUT_SMOOTH_ITERATIONS,
            "highcutSmoothingFactor": HIGHCUT_SMOOTH_FACTOR,
            "normalRepresentation": (
                "barycentric interpolation of evaluated body vertex normals"
            ),
        },
        "metrics": {
            "topologyBeforeReprojection": before_topology,
            "topologyAfterReprojection": after_topology,
            "repairZoneVertexCount": sum(repair_zone),
            "liftedVertexCount": lifted,
            "cappedVertexCount": capped,
            "worldDisplacementM": _statistics(displacements),
            "signedClearanceAfterM": _statistics(signed_clearances),
            "surfaceResidualEdgeRmsBeforeM": _residual_edge_rms(
                before_residuals,
                adjacency,
            ),
            "surfaceResidualEdgeRmsAfterM": _residual_edge_rms(
                after_residuals,
                adjacency,
            ),
        },
        "acceptance": "PENDING_ACTUAL_RENDER_AND_POSE_REVIEW",
    }


def repair_hood_roll(
    hood: bpy.types.Object | None,
    armature: bpy.types.Object,
) -> dict[str, Any]:
    """Compress the shoulder-wide folded roll while preserving topology."""
    if hood is None:
        return {"status": "NOT_FOUND"}
    if hood.type != "MESH":
        return {"status": "SKIPPED_NON_MESH", "objectType": hood.type}
    inverse_root = armature.matrix_world.inverted_safe()
    root_matrix = armature.matrix_world.copy()
    inverse_object = hood.matrix_world.inverted_safe()
    displacements: list[float] = []
    for vertex in hood.data.vertices:
        original = hood.matrix_world @ vertex.co
        local = inverse_root @ original
        local.x *= HOOD_LATERAL_SCALE
        candidate = root_matrix @ local
        vertex.co = inverse_object @ candidate
        displacements.append((candidate - original).length)
    _recalculate_normals(hood)
    return {
        "status": "EXECUTED",
        "object": hood.name,
        "lateralScale": HOOD_LATERAL_SCALE,
        "worldDisplacementM": _statistics(displacements),
    }


def _write_report(report: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def install(pattern: ModuleType) -> None:
    """Wrap the current constructor with measured post-LoBoFit repairs."""
    original = pattern.create_outfit

    def create_outfit(*args, **kwargs):
        garments = original(*args, **kwargs)
        body = args[0]
        armature = args[1]
        shell = next(obj for obj in garments if obj.name == "Heather_Body_Shell")
        hood = next(
            (obj for obj in garments if obj.name == "Heather_Hood_Folded_Roll"),
            None,
        )
        report = {
            "schemaVersion": 1,
            "designRevision": DESIGN_REVISION,
            "target": "SiroinoSotai_PC",
            "shellRepair": repair_shell_surface(shell, body, armature),
            "hoodRepair": repair_hood_roll(hood, armature),
            "completionClaim": False,
        }
        _write_report(report)
        print("Smooth-normal high-cut repair: " + json.dumps(report))
        return garments

    pattern.create_outfit = create_outfit
    pattern.DESIGN_REVISION = DESIGN_REVISION
