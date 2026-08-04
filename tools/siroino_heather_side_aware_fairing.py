#!/usr/bin/env python3
"""Side-aware shell fairing and pose-driven clearance repair.

The v24 nearest-triangle reprojection produced a formally positive neutral
clearance but amplified triangle-normal discontinuities and collapsed the two
sides of the narrow underbody onto the same body region. This stage instead:

* preserves the source-derived side of every garment vertex,
* applies boundary-protected Taubin fairing,
* separates the front and rear underbody with body cross-section envelopes,
* corrects only vertices implicated by the six required pose BVH audits, and
* rebuilds the folded hood as a continuous fabric panel rather than a tube.

All operations mutate the generated Blender meshes and write measured evidence.
They do not assert visual completion.
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

DESIGN_REVISION = "v25-side-aware-taubin-shell"
STATIC_MIN_CLEARANCE_M = 0.020
UNDERBODY_CLEARANCE_M = 0.034
UNDERBODY_CENTER_FLOOR_M = 0.625
UNDERBODY_SIDE_FLOOR_M = 0.755
UNDERBODY_CENTER_HALF_WIDTH_M = 0.020
UNDERBODY_OUTER_HALF_WIDTH_M = 0.165
UNDERBODY_MAX_LIFT_M = 0.095
FAIRING_CYCLES = 6
FAIRING_LAMBDA = 0.24
FAIRING_MU = -0.245
POSE_CORRECTION_ROUNDS = 2
POSE_MAX_STEP_PER_ROUND_M = 0.020
POSE_MAX_TOTAL_STEP_M = 0.038
SECTION_BIN_M = 0.005
MICRO_HOLE_MAX_EDGES = 8
MICRO_HOLE_MAX_PERIMETER_M = 0.010

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = (
    ROOT
    / "Assets"
    / "GenWorks"
    / "siroino-heather-hooded-bodysuit"
    / "Research"
    / "side-aware-taubin-shell-trial.json"
)
POSES = ("neutral", "arms-up", "arm-cross", "crouch", "sit", "prone")


def _statistics(values: list[float]) -> dict[str, float]:
    if not values:
        return {"minimum": 0.0, "mean": 0.0, "maximum": 0.0}
    return {
        "minimum": min(values),
        "mean": sum(values) / len(values),
        "maximum": max(values),
    }


def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def _adjacency(mesh: bpy.types.Mesh) -> dict[int, set[int]]:
    result = {vertex.index: set() for vertex in mesh.vertices}
    for edge in mesh.edges:
        left, right = edge.vertices
        result[left].add(right)
        result[right].add(left)
    return result


def _boundary_vertices(mesh: bpy.types.Mesh) -> set[int]:
    edge_use: Counter[tuple[int, int]] = Counter()
    for polygon in mesh.polygons:
        vertices = list(polygon.vertices)
        for index, left in enumerate(vertices):
            right = vertices[(index + 1) % len(vertices)]
            edge_use[tuple(sorted((left, right)))] += 1
    return {vertex for edge, count in edge_use.items() if count == 1 for vertex in edge}


def _boundary_protection(
    mesh: bpy.types.Mesh,
    adjacency: dict[int, set[int]],
) -> list[float]:
    protection = [0.0] * len(mesh.vertices)
    frontier = _boundary_vertices(mesh)
    visited = set(frontier)
    for vertex in frontier:
        protection[vertex] = 1.0
    for value in (0.78, 0.48, 0.22):
        next_frontier = {
            neighbour
            for index in frontier
            for neighbour in adjacency[index]
            if neighbour not in visited
        }
        for vertex in next_frontier:
            protection[vertex] = max(protection[vertex], value)
        visited.update(next_frontier)
        frontier = next_frontier
    return protection


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
    remaining = set(boundary_adjacency)
    loops = 0
    while remaining:
        loops += 1
        stack = [remaining.pop()]
        while stack:
            neighbours = boundary_adjacency[stack.pop()] & remaining
            remaining.difference_update(neighbours)
            stack.extend(neighbours)
    return {
        "connectedComponents": components,
        "boundaryLoops": loops,
        "boundaryEdges": len(boundary_edges),
    }


def _fill_tiny_boundary_holes(obj: bpy.types.Object) -> dict[str, Any]:
    mesh = obj.data
    before = _topology_metrics(mesh)
    bm = bmesh.new()
    filled: list[dict[str, Any]] = []
    try:
        bm.from_mesh(mesh)
        remaining = {edge for edge in bm.edges if edge.is_boundary}
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
                raise RuntimeError("Tiny-boundary closure created no face")
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
            "Tiny-boundary closure changed connected-component count: "
            f"before={before}, after={after}"
        )
    if after["boundaryLoops"] != before["boundaryLoops"] - len(filled):
        raise RuntimeError(
            "Tiny-boundary closure did not remove exactly one loop per repair: "
            f"before={before}, after={after}, filled={filled}"
        )
    return {
        "topologyBefore": before,
        "topologyAfter": after,
        "filledHoleCount": len(filled),
        "filledHoles": filled,
    }


def _barycentric_coordinates(
    point: Vector,
    first: Vector,
    second: Vector,
    third: Vector,
) -> Vector:
    edge_0 = second - first
    edge_1 = third - first
    offset = point - first
    dot_00 = edge_0.dot(edge_0)
    dot_01 = edge_0.dot(edge_1)
    dot_11 = edge_1.dot(edge_1)
    dot_20 = offset.dot(edge_0)
    dot_21 = offset.dot(edge_1)
    denominator = dot_00 * dot_11 - dot_01 * dot_01
    if abs(denominator) <= 1e-16:
        return Vector((1.0, 0.0, 0.0))
    second_weight = (dot_11 * dot_20 - dot_01 * dot_21) / denominator
    third_weight = (dot_00 * dot_21 - dot_01 * dot_20) / denominator
    return Vector((1.0 - second_weight - third_weight, second_weight, third_weight))


class _BodySampler:
    def __init__(
        self,
        body: bpy.types.Object,
        armature: bpy.types.Object,
    ) -> None:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = body.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
        try:
            matrix = evaluated.matrix_world.copy()
            normal_matrix = matrix.to_3x3().inverted().transposed()
            self.world_vertices = [matrix @ vertex.co for vertex in mesh.vertices]
            self.world_normals: list[Vector] = []
            for vertex in mesh.vertices:
                normal = normal_matrix @ vertex.normal
                if normal.length_squared <= 1e-16:
                    normal = Vector((0.0, 0.0, 1.0))
                else:
                    normal.normalize()
                self.world_normals.append(normal)
            mesh.calc_loop_triangles()
            self.triangles = [
                tuple(int(index) for index in triangle.vertices)
                for triangle in mesh.loop_triangles
            ]
        finally:
            evaluated.to_mesh_clear()
        if not self.triangles:
            raise RuntimeError("Body sampler requires evaluated body triangles")
        self.tree = BVHTree.FromPolygons(
            self.world_vertices,
            self.triangles,
            all_triangles=True,
        )
        self.root_matrix = armature.matrix_world.copy()
        self.inverse_root = self.root_matrix.inverted_safe()
        self.local_vertices = [
            self.inverse_root @ point for point in self.world_vertices
        ]
        self.section_bins: dict[int, list[float]] = {}
        for point in self.local_vertices:
            if abs(point.x) > 0.11:
                continue
            key = round(point.z / SECTION_BIN_M)
            self.section_bins.setdefault(key, []).append(float(point.y))

    def nearest(self, point: Vector) -> tuple[Vector, Vector]:
        nearest = self.tree.find_nearest(point)
        if nearest is None:
            raise RuntimeError("Could not sample the evaluated body")
        location, _face_normal, triangle_index, _distance = nearest
        if triangle_index is None or triangle_index < 0:
            raise RuntimeError("Body sampler received no triangle index")
        first, second, third = self.triangles[triangle_index]
        barycentric = _barycentric_coordinates(
            location,
            self.world_vertices[first],
            self.world_vertices[second],
            self.world_vertices[third],
        )
        normal = (
            self.world_normals[first] * barycentric.x
            + self.world_normals[second] * barycentric.y
            + self.world_normals[third] * barycentric.z
        )
        if normal.length_squared <= 1e-16:
            normal = (self.world_vertices[second] - self.world_vertices[first]).cross(
                self.world_vertices[third] - self.world_vertices[first]
            )
        if normal.length_squared <= 1e-16:
            raise RuntimeError("Body sampler received a degenerate normal")
        normal.normalize()
        return location, normal

    def section(self, z_value: float) -> tuple[float, float, float]:
        key = round(z_value / SECTION_BIN_M)
        values: list[float] = []
        for radius in range(0, 9):
            offsets = (0,) if radius == 0 else (-radius, radius)
            for offset in offsets:
                values.extend(self.section_bins.get(key + offset, []))
            if len(values) >= 16:
                break
        if len(values) < 4:
            raise RuntimeError(f"No body cross section near root-local z={z_value:.4f}")
        minimum = min(values)
        maximum = max(values)
        return minimum, maximum, (minimum + maximum) * 0.5


def _underbody_floor(x_value: float) -> float:
    fraction = (abs(x_value) - UNDERBODY_CENTER_HALF_WIDTH_M) / (
        UNDERBODY_OUTER_HALF_WIDTH_M - UNDERBODY_CENTER_HALF_WIDTH_M
    )
    return UNDERBODY_CENTER_FLOOR_M + (
        UNDERBODY_SIDE_FLOOR_M - UNDERBODY_CENTER_FLOOR_M
    ) * _smoothstep(fraction)


def _underbody_weight(local: Vector) -> float:
    x_weight = 1.0 - _smoothstep((abs(local.x) - 0.018) / (0.078 - 0.018))
    z_weight = 1.0 - _smoothstep((local.z - 0.660) / (0.760 - 0.660))
    return max(0.0, min(1.0, x_weight * z_weight))


def _taubin_fair(
    points: list[Vector],
    adjacency: dict[int, set[int]],
    protection: list[float],
    *,
    cycles: int = FAIRING_CYCLES,
) -> list[Vector]:
    current = [point.copy() for point in points]
    for _cycle in range(cycles):
        first = [point.copy() for point in current]
        for index, neighbours in adjacency.items():
            if not neighbours:
                continue
            mean = sum((current[item] for item in neighbours), Vector()) / len(
                neighbours
            )
            first[index] = current[index] + (mean - current[index]) * FAIRING_LAMBDA * (
                1.0 - protection[index]
            )
        second = [point.copy() for point in first]
        for index, neighbours in adjacency.items():
            if not neighbours:
                continue
            mean = sum((first[item] for item in neighbours), Vector()) / len(neighbours)
            second[index] = first[index] + (mean - first[index]) * FAIRING_MU * (
                1.0 - protection[index]
            )
        current = second
    return current


def _orient_outward(
    point: Vector,
    anchor: Vector,
    normal: Vector,
) -> Vector:
    residual = point - anchor
    if residual.dot(normal) < 0.0:
        normal = -normal
    if residual.length_squared <= 1e-14:
        return normal.normalized()
    direction = residual.normalized()
    if direction.dot(normal) < 0.35:
        direction = (direction + normal * 1.5).normalized()
    return direction


def _set_world_points(
    obj: bpy.types.Object,
    points: list[Vector],
) -> None:
    inverse_object = obj.matrix_world.inverted_safe()
    for vertex, point in zip(obj.data.vertices, points, strict=True):
        vertex.co = inverse_object @ point
    obj.data.update(calc_edges=True)


def _recalculate_normals(obj: bpy.types.Object) -> None:
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.normal_update()
        bm.to_mesh(obj.data)
    finally:
        bm.free()
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    obj.data.update(calc_edges=True)


def _apply_static_fairing(
    shell: bpy.types.Object,
    sampler: _BodySampler,
    armature: bpy.types.Object,
) -> dict[str, Any]:
    adjacency = _adjacency(shell.data)
    protection = _boundary_protection(shell.data, adjacency)
    original = [shell.matrix_world @ vertex.co for vertex in shell.data.vertices]
    original_local = [sampler.inverse_root @ point for point in original]

    lifted: list[Vector] = []
    lifts: list[float] = []
    for local in original_local:
        candidate = local.copy()
        active = abs(local.x) <= UNDERBODY_OUTER_HALF_WIDTH_M and local.z < 0.835
        lift = 0.0
        if active:
            lift = min(
                UNDERBODY_MAX_LIFT_M,
                max(0.0, _underbody_floor(local.x) - local.z),
            )
            candidate.z += lift
        lifted.append(sampler.root_matrix @ candidate)
        lifts.append(lift)

    fair = _taubin_fair(lifted, adjacency, protection)
    corrected: list[Vector] = []
    signed_clearances: list[float] = []
    displacements: list[float] = []
    underbody_vertices = 0
    capped = 0

    for index, point in enumerate(fair):
        local = sampler.inverse_root @ point
        weight = _underbody_weight(local)
        if weight > 0.0:
            minimum_y, maximum_y, center_y = sampler.section(local.z)
            original_side = 1.0 if original_local[index].y >= center_y else -1.0
            target_y = (
                maximum_y + UNDERBODY_CLEARANCE_M
                if original_side > 0.0
                else minimum_y - UNDERBODY_CLEARANCE_M
            )
            local.y = local.y * (1.0 - weight) + target_y * weight
            point = sampler.root_matrix @ local
            underbody_vertices += 1

        anchor, normal = sampler.nearest(point)
        direction = _orient_outward(point, anchor, normal)
        clearance = (point - anchor).dot(direction)
        if clearance < STATIC_MIN_CLEARANCE_M:
            point = anchor + direction * STATIC_MIN_CLEARANCE_M
            clearance = STATIC_MIN_CLEARANCE_M

        delta = point - original[index]
        maximum_step = 0.105 if weight > 0.0 else 0.032
        if delta.length > maximum_step:
            delta.normalize()
            delta *= maximum_step
            point = original[index] + delta
            capped += 1
            anchor, normal = sampler.nearest(point)
            direction = _orient_outward(point, anchor, normal)
            clearance = (point - anchor).dot(direction)

        corrected.append(point)
        displacements.append((point - original[index]).length)
        signed_clearances.append(clearance)

    _set_world_points(shell, corrected)
    _recalculate_normals(shell)
    return {
        "fairing": {
            "cycles": FAIRING_CYCLES,
            "lambda": FAIRING_LAMBDA,
            "mu": FAIRING_MU,
            "boundaryProtectionRings": 4,
        },
        "liftedVertexCount": sum(value > 1e-8 for value in lifts),
        "underbodySeparatedVertexCount": underbody_vertices,
        "cappedVertexCount": capped,
        "worldDisplacementM": _statistics(displacements),
        "signedClearanceAfterM": _statistics(signed_clearances),
    }


def _rotate(
    armature: bpy.types.Object,
    bone_name: str,
    degrees: tuple[float, float, float],
) -> None:
    bone = armature.pose.bones.get(bone_name)
    if bone is None:
        raise RuntimeError(f"Required pose bone missing: {bone_name}")
    bone.rotation_mode = "XYZ"
    bone.rotation_euler = tuple(math.radians(value) for value in degrees)


def _clear_pose(
    armature: bpy.types.Object,
    base_location: Vector,
    base_rotation: Vector,
    base_scale: Vector,
) -> None:
    armature.location = base_location.copy()
    armature.rotation_mode = "XYZ"
    armature.rotation_euler = base_rotation.copy()
    armature.scale = base_scale.copy()
    for bone in armature.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0.0, 0.0, 0.0)
        bone.location = (0.0, 0.0, 0.0)
        bone.scale = (1.0, 1.0, 1.0)


def _apply_pose(
    armature: bpy.types.Object,
    base_location: Vector,
    base_rotation: Vector,
    base_scale: Vector,
    name: str,
) -> None:
    _clear_pose(armature, base_location, base_rotation, base_scale)
    if name == "arms-up":
        _rotate(armature, "UpperArm_L", (-112.0, 0.0, -8.0))
        _rotate(armature, "UpperArm_R", (-112.0, 0.0, 8.0))
        _rotate(armature, "LowerArm_L", (-7.0, 0.0, 0.0))
        _rotate(armature, "LowerArm_R", (-7.0, 0.0, 0.0))
    elif name == "arm-cross":
        _rotate(armature, "UpperArm_L", (-42.0, 18.0, -54.0))
        _rotate(armature, "UpperArm_R", (-42.0, -18.0, 54.0))
        _rotate(armature, "LowerArm_L", (-82.0, 0.0, 16.0))
        _rotate(armature, "LowerArm_R", (-82.0, 0.0, -16.0))
        _rotate(armature, "Chest", (5.0, 0.0, 0.0))
    elif name == "crouch":
        _rotate(armature, "UpperLeg_L", (48.0, 0.0, 7.0))
        _rotate(armature, "UpperLeg_R", (48.0, 0.0, -7.0))
        _rotate(armature, "LowerLeg_L", (-72.0, 0.0, 0.0))
        _rotate(armature, "LowerLeg_R", (-72.0, 0.0, 0.0))
        _rotate(armature, "Spine", (12.0, 0.0, 0.0))
        hips = armature.pose.bones.get("Hips")
        if hips is not None:
            hips.location.z = -0.10
    elif name == "sit":
        _rotate(armature, "UpperLeg_L", (78.0, 0.0, 4.0))
        _rotate(armature, "UpperLeg_R", (78.0, 0.0, -4.0))
        _rotate(armature, "LowerLeg_L", (-82.0, 0.0, 0.0))
        _rotate(armature, "LowerLeg_R", (-82.0, 0.0, 0.0))
        _rotate(armature, "Spine", (9.0, 0.0, 0.0))
        _rotate(armature, "Chest", (7.0, 0.0, 0.0))
        _rotate(armature, "UpperArm_L", (-18.0, 0.0, -14.0))
        _rotate(armature, "UpperArm_R", (-18.0, 0.0, 14.0))
        hips = armature.pose.bones.get("Hips")
        if hips is not None:
            hips.location.z = -0.17
    elif name == "prone":
        armature.rotation_euler.x += math.radians(78.0)
        armature.location.z += 0.46
        _rotate(armature, "Spine", (12.0, 0.0, 0.0))
        _rotate(armature, "Chest", (15.0, 0.0, 0.0))
        _rotate(armature, "UpperArm_L", (-126.0, 0.0, -16.0))
        _rotate(armature, "UpperArm_R", (-126.0, 0.0, 16.0))
        _rotate(armature, "LowerArm_L", (-18.0, 0.0, 0.0))
        _rotate(armature, "LowerArm_R", (-18.0, 0.0, 0.0))
        _rotate(armature, "UpperLeg_L", (-8.0, 0.0, 3.0))
        _rotate(armature, "UpperLeg_R", (-8.0, 0.0, -3.0))
    bpy.context.view_layer.update()


def _pose_overlap_counts(
    shell: bpy.types.Object,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    base_location: Vector,
    base_rotation: Vector,
    base_scale: Vector,
) -> tuple[list[int], dict[str, int]]:
    counts = [0] * len(shell.data.vertices)
    pose_pairs: dict[str, int] = {}
    for pose_name in POSES:
        _apply_pose(
            armature,
            base_location,
            base_rotation,
            base_scale,
            pose_name,
        )
        depsgraph = bpy.context.evaluated_depsgraph_get()
        body_tree = BVHTree.FromObject(body, depsgraph, deform=True, cage=False)
        shell_tree = BVHTree.FromObject(shell, depsgraph, deform=True, cage=False)
        if body_tree is None or shell_tree is None:
            raise RuntimeError(f"Could not build BVH for pose {pose_name}")
        overlaps = body_tree.overlap(shell_tree)
        pose_pairs[pose_name] = len(overlaps)
        for _body_polygon, garment_polygon in overlaps:
            if garment_polygon >= len(shell.data.polygons):
                continue
            for vertex in shell.data.polygons[garment_polygon].vertices:
                counts[vertex] += 1
    _clear_pose(armature, base_location, base_rotation, base_scale)
    bpy.context.view_layer.update()
    return counts, pose_pairs


def _smooth_displacements(
    displacements: list[Vector],
    adjacency: dict[int, set[int]],
    active: set[int],
) -> list[Vector]:
    current = [value.copy() for value in displacements]
    expanded = set(active)
    for index in list(active):
        expanded.update(adjacency[index])
    for _iteration in range(3):
        updated = [value.copy() for value in current]
        for index in expanded:
            neighbours = adjacency[index]
            if not neighbours:
                continue
            mean = sum((current[item] for item in neighbours), Vector()) / len(
                neighbours
            )
            updated[index] = current[index] * 0.68 + mean * 0.32
        current = updated
    return current


def _apply_pose_correction(
    shell: bpy.types.Object,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    sampler: _BodySampler,
) -> dict[str, Any]:
    adjacency = _adjacency(shell.data)
    protection = _boundary_protection(shell.data, adjacency)
    base_location = armature.location.copy()
    base_rotation = armature.rotation_euler.copy()
    base_scale = armature.scale.copy()
    initial_points = [shell.matrix_world @ vertex.co for vertex in shell.data.vertices]
    rounds: list[dict[str, Any]] = []

    counts, before_pairs = _pose_overlap_counts(
        shell,
        body,
        armature,
        base_location,
        base_rotation,
        base_scale,
    )
    for round_index in range(POSE_CORRECTION_ROUNDS):
        active = {index for index, count in enumerate(counts) if count > 0}
        if not active:
            break
        points = [shell.matrix_world @ vertex.co for vertex in shell.data.vertices]
        displacements = [Vector() for _ in points]
        for index in active:
            point = points[index]
            anchor, normal = sampler.nearest(point)
            direction = _orient_outward(point, anchor, normal)
            local = sampler.inverse_root @ point
            underbody = _underbody_weight(local)
            if underbody > 0.0:
                minimum_y, maximum_y, center_y = sampler.section(local.z)
                sign = 1.0 if local.y >= center_y else -1.0
                radial = sampler.root_matrix.to_3x3() @ Vector((0.0, sign, 0.0))
                radial.normalize()
                direction = (
                    direction * (1.0 - underbody) + radial * underbody
                ).normalized()
                _ = minimum_y, maximum_y
            step = min(
                POSE_MAX_STEP_PER_ROUND_M,
                0.004 + 0.0015 * math.sqrt(float(counts[index])),
            )
            step *= 0.72 + 0.28 * (1.0 - protection[index])
            displacements[index] = direction * step
        displacements = _smooth_displacements(displacements, adjacency, active)
        corrected: list[Vector] = []
        capped = 0
        for index, point in enumerate(points):
            candidate = point + displacements[index]
            total = candidate - initial_points[index]
            if total.length > POSE_MAX_TOTAL_STEP_M:
                total.normalize()
                total *= POSE_MAX_TOTAL_STEP_M
                candidate = initial_points[index] + total
                capped += 1
            corrected.append(candidate)
        _set_world_points(shell, corrected)
        _recalculate_normals(shell)
        counts, after_round = _pose_overlap_counts(
            shell,
            body,
            armature,
            base_location,
            base_rotation,
            base_scale,
        )
        rounds.append(
            {
                "round": round_index + 1,
                "activeVertexCount": len(active),
                "cappedVertexCount": capped,
                "posePairsAfter": after_round,
                "totalPairsAfter": sum(after_round.values()),
            }
        )

    final_points = [shell.matrix_world @ vertex.co for vertex in shell.data.vertices]
    return {
        "posePairsBefore": before_pairs,
        "totalPairsBefore": sum(before_pairs.values()),
        "rounds": rounds,
        "posePairsAfter": rounds[-1]["posePairsAfter"] if rounds else before_pairs,
        "totalPairsAfter": (
            rounds[-1]["totalPairsAfter"] if rounds else sum(before_pairs.values())
        ),
        "worldDisplacementFromStaticM": _statistics(
            [
                (final - initial).length
                for final, initial in zip(final_points, initial_points, strict=True)
            ]
        ),
    }


def _move_modifier_before_armature(
    obj: bpy.types.Object,
    modifier: bpy.types.Modifier,
) -> None:
    while obj.modifiers.find(modifier.name) > 0:
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_move_up(modifier=modifier.name)


def _rebuild_folded_hood(
    hood: bpy.types.Object | None,
    sampler: _BodySampler,
    armature: bpy.types.Object,
) -> dict[str, Any]:
    if hood is None:
        return {"status": "NOT_FOUND"}
    if hood.type != "MESH":
        return {"status": "SKIPPED_NON_MESH", "objectType": hood.type}

    current_local = [
        sampler.inverse_root @ (hood.matrix_world @ vertex.co)
        for vertex in hood.data.vertices
    ]
    average_y = sum(point.y for point in current_local) / max(len(current_local), 1)
    _minimum_y, _maximum_y, center_y = sampler.section(1.025)
    back_sign = 1.0 if average_y >= center_y else -1.0

    columns = 25
    rows = 7
    local_vertices: list[Vector] = []
    faces: list[tuple[int, int, int, int]] = []
    for row in range(rows):
        vertical = row / (rows - 1)
        half_width = 0.145 - 0.035 * vertical
        for column in range(columns):
            lateral = 2.0 * column / (columns - 1) - 1.0
            x_value = half_width * lateral
            z_value = 1.010 + 0.145 * vertical - 0.018 * lateral * lateral
            minimum_y, maximum_y, _section_center = sampler.section(z_value)
            surface_y = maximum_y if back_sign > 0.0 else minimum_y
            fold_depth = 0.024 + 0.058 * vertical + 0.012 * (1.0 - lateral * lateral)
            y_value = surface_y + back_sign * fold_depth
            local_vertices.append(Vector((x_value, y_value, z_value)))
    for row in range(rows - 1):
        for column in range(columns - 1):
            first = row * columns + column
            second = first + 1
            fourth = (row + 1) * columns + column
            third = fourth + 1
            faces.append((first, second, third, fourth))

    world_vertices = [sampler.root_matrix @ point for point in local_vertices]
    inverse_object = hood.matrix_world.inverted_safe()
    mesh = bpy.data.meshes.new("Heather_Hood_Folded_Panel_Mesh")
    mesh.from_pydata([inverse_object @ point for point in world_vertices], [], faces)
    mesh.update(calc_edges=True)
    if hood.data.materials:
        mesh.materials.append(hood.data.materials[0])
    previous_mesh = hood.data
    hood.data = mesh
    if previous_mesh.users == 0:
        bpy.data.meshes.remove(previous_mesh)

    while hood.vertex_groups:
        hood.vertex_groups.remove(hood.vertex_groups[0])
    chest = hood.vertex_groups.new(name="Chest")
    neck = hood.vertex_groups.new(name="Neck")
    for row in range(rows):
        vertical = row / (rows - 1)
        indices = [row * columns + column for column in range(columns)]
        neck_weight = 0.28 + 0.42 * vertical
        chest.add(indices, 1.0 - neck_weight, "REPLACE")
        neck.add(indices, neck_weight, "REPLACE")

    bpy.ops.object.select_all(action="DESELECT")
    hood.select_set(True)
    bpy.context.view_layer.objects.active = hood
    subdivision = hood.modifiers.new("Folded hood surface", "SUBSURF")
    subdivision.subdivision_type = "CATMULL_CLARK"
    subdivision.levels = 1
    subdivision.render_levels = 1
    _move_modifier_before_armature(hood, subdivision)
    bpy.ops.object.modifier_apply(modifier=subdivision.name)
    solidify = hood.modifiers.new("Folded hood thickness", "SOLIDIFY")
    solidify.thickness = 0.003
    solidify.offset = 0.0
    _move_modifier_before_armature(hood, solidify)
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    hood.select_set(False)
    _recalculate_normals(hood)
    return {
        "status": "EXECUTED",
        "representation": "continuous subdivided and solidified folded hood panel",
        "columns": columns,
        "rows": rows,
        "backSign": back_sign,
        "vertexCountAfter": len(hood.data.vertices),
        "polygonCountAfter": len(hood.data.polygons),
    }


def _write_report(report: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def install(pattern: ModuleType) -> None:
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
        topology_repair = _fill_tiny_boundary_holes(shell)
        topology = _topology_metrics(shell.data)
        if topology["connectedComponents"] != 1 or topology["boundaryLoops"] != 5:
            raise RuntimeError(
                "v25 requires one connected shell with five anatomical openings; "
                f"measured={topology}"
            )
        sampler = _BodySampler(body, armature)
        static_fairing = _apply_static_fairing(shell, sampler, armature)
        pose_correction = _apply_pose_correction(shell, body, armature, sampler)
        hood_rebuild = _rebuild_folded_hood(hood, sampler, armature)
        final_topology = _topology_metrics(shell.data)
        if final_topology != topology:
            raise RuntimeError(
                "v25 fairing changed shell topology: "
                f"before={topology}, after={final_topology}"
            )
        report = {
            "schemaVersion": 1,
            "designRevision": DESIGN_REVISION,
            "target": "SiroinoSotai_PC",
            "method": (
                "source-side-preserving Taubin fairing, body-section underbody "
                "separation and two-round required-pose BVH correction"
            ),
            "topologyRepair": topology_repair,
            "topologyAfter": final_topology,
            "staticFairing": static_fairing,
            "poseCorrection": pose_correction,
            "hoodRebuild": hood_rebuild,
            "completionClaim": False,
            "acceptance": "PENDING_ACTUAL_RENDER_AND_INDEPENDENT_POSE_AUDIT",
        }
        _write_report(report)
        print("Side-aware Taubin shell: " + json.dumps(report))
        return garments

    pattern.create_outfit = create_outfit
    pattern.DESIGN_REVISION = DESIGN_REVISION
