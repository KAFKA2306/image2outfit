#!/usr/bin/env python3
"""LoBoFit-inspired local-bone residual fitting for the Siroino bodysuit.

This is an independent deterministic prototype derived from the representation
principle in LoBoFit. It does not execute or copy the authors' implementation.
The fitted shell is encoded as body-relative residuals in the local frames of
its four strongest bones, smoothed locally, pulled toward the declared body
clearance, and decoded back to world space with bounded displacement.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

DESIGN_REVISION = "v23-dama-anchor-lobomap-residual-fit"
PAPER_TITLE = "LoBoFit: Flexible Garment Refitting via Local Bone Mapping Blending"
PAPER_URL = "https://arxiv.org/abs/2605.07450"
PAPER_DATE = "2026-05-08"
PAPER_LICENSE = "CC BY-NC-ND 4.0"
CLEARANCE_M = 0.022
MAX_STEP_M = 0.004
ITERATIONS = 6
INTERIOR_STRENGTH = 0.38
BOUNDARY_STRENGTH = 0.12
TARGET_PULL = 0.55

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = (
    ROOT
    / "Assets"
    / "GenWorks"
    / "siroino-heather-hooded-bodysuit"
    / "Research"
    / "lobofit-local-bone-trial.json"
)


def _world_bvh(body: bpy.types.Object) -> BVHTree:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = body.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        matrix = evaluated.matrix_world.copy()
        vertices = [matrix @ vertex.co for vertex in mesh.vertices]
        polygons = [tuple(polygon.vertices) for polygon in mesh.polygons]
        return BVHTree.FromPolygons(vertices, polygons, all_triangles=False)
    finally:
        evaluated.to_mesh_clear()


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


def _bone_rotations(armature: bpy.types.Object) -> dict[str, Matrix]:
    rotations: dict[str, Matrix] = {}
    for pose_bone in armature.pose.bones:
        world = armature.matrix_world @ pose_bone.matrix
        rotations[pose_bone.name] = world.to_quaternion().to_matrix()
    return rotations


def _normalized_weights(
    obj: bpy.types.Object,
    vertex: bpy.types.MeshVertex,
    rotations: dict[str, Matrix],
) -> dict[str, float]:
    ranked: list[tuple[str, float]] = []
    for assignment in vertex.groups:
        name = obj.vertex_groups[assignment.group].name
        if name in rotations and assignment.weight > 1e-8:
            ranked.append((name, float(assignment.weight)))
    ranked.sort(key=lambda item: item[1], reverse=True)
    ranked = ranked[:4]
    if not ranked:
        fallback = "Hips" if "Hips" in rotations else next(iter(rotations))
        return {fallback: 1.0}
    total = sum(weight for _, weight in ranked)
    return {name: weight / total for name, weight in ranked}


def _edge_local_rms(
    local_residuals: list[dict[str, Vector]],
    weights: list[dict[str, float]],
    adjacency: dict[int, set[int]],
) -> float:
    weighted_square = 0.0
    total_weight = 0.0
    for left, neighbours in adjacency.items():
        for right in neighbours:
            if right <= left:
                continue
            shared = set(local_residuals[left]) & set(local_residuals[right])
            for bone in shared:
                weight = min(weights[left][bone], weights[right][bone])
                delta = local_residuals[left][bone] - local_residuals[right][bone]
                weighted_square += weight * delta.length_squared
                total_weight += weight
    return math.sqrt(weighted_square / max(total_weight, 1e-12))


def _statistics(values: list[float]) -> dict[str, float]:
    if not values:
        return {"minimum": 0.0, "mean": 0.0, "maximum": 0.0}
    return {
        "minimum": min(values),
        "mean": sum(values) / len(values),
        "maximum": max(values),
    }


def fit_shell(
    shell: bpy.types.Object,
    body: bpy.types.Object,
    armature: bpy.types.Object,
) -> dict[str, Any]:
    """Apply bounded local-bone residual smoothing to the primary shell."""
    bvh = _world_bvh(body)
    adjacency = _adjacency(shell.data)
    boundary = _boundary_vertices(shell.data)
    rotations = _bone_rotations(armature)
    inverse_rotations = {name: matrix.inverted() for name, matrix in rotations.items()}
    weights = [
        _normalized_weights(shell, vertex, rotations) for vertex in shell.data.vertices
    ]

    world_points: list[Vector] = []
    anchors: list[Vector] = []
    normals: list[Vector] = []
    distances_before: list[float] = []
    local_residuals: list[dict[str, Vector]] = []
    target_local: list[dict[str, Vector]] = []

    for vertex, vertex_weights in zip(shell.data.vertices, weights, strict=True):
        world = shell.matrix_world @ vertex.co
        nearest = bvh.find_nearest(world)
        if nearest is None:
            raise RuntimeError(
                f"LoBoMap could not sample body near vertex {vertex.index}"
            )
        anchor, normal, _polygon, distance = nearest
        if normal.length_squared <= 1e-12:
            raise RuntimeError(
                f"LoBoMap received zero body normal at vertex {vertex.index}"
            )
        normal = normal.normalized()
        residual = world - anchor
        if residual.dot(normal) < 0.0:
            normal = -normal
        desired = normal * CLEARANCE_M

        world_points.append(world)
        anchors.append(anchor)
        normals.append(normal)
        distances_before.append(float(distance))
        local_residuals.append(
            {bone: inverse_rotations[bone] @ residual for bone in vertex_weights}
        )
        target_local.append(
            {bone: inverse_rotations[bone] @ desired for bone in vertex_weights}
        )

    roughness_before = _edge_local_rms(local_residuals, weights, adjacency)
    current = [
        {bone: value.copy() for bone, value in per_bone.items()}
        for per_bone in local_residuals
    ]
    for _iteration in range(ITERATIONS):
        updated: list[dict[str, Vector]] = []
        for index, per_bone in enumerate(current):
            strength = BOUNDARY_STRENGTH if index in boundary else INTERIOR_STRENGTH
            next_values: dict[str, Vector] = {}
            for bone, value in per_bone.items():
                neighbours = [
                    neighbour
                    for neighbour in adjacency[index]
                    if bone in current[neighbour]
                ]
                if neighbours:
                    weighted = Vector((0.0, 0.0, 0.0))
                    total = 0.0
                    for neighbour in neighbours:
                        influence = min(
                            weights[index][bone],
                            weights[neighbour][bone],
                        )
                        weighted += current[neighbour][bone] * influence
                        total += influence
                    neighbour_mean = weighted / max(total, 1e-12)
                else:
                    neighbour_mean = value
                desired = neighbour_mean.lerp(target_local[index][bone], TARGET_PULL)
                next_values[bone] = value.lerp(desired, strength)
            updated.append(next_values)
        current = updated

    roughness_after = _edge_local_rms(current, weights, adjacency)
    inverse_object = shell.matrix_world.inverted()
    displacements: list[float] = []
    distances_after: list[float] = []
    signed_clearance_after: list[float] = []

    for index, vertex in enumerate(shell.data.vertices):
        decoded = Vector((0.0, 0.0, 0.0))
        for bone, weight in weights[index].items():
            decoded += (rotations[bone] @ current[index][bone]) * weight
        signed = decoded.dot(normals[index])
        if signed < CLEARANCE_M * 0.75:
            decoded += normals[index] * (CLEARANCE_M * 0.75 - signed)
        candidate = anchors[index] + decoded
        delta = candidate - world_points[index]
        if delta.length > MAX_STEP_M:
            delta.normalize()
            delta *= MAX_STEP_M
            candidate = world_points[index] + delta
        vertex.co = inverse_object @ candidate
        displacements.append(delta.length)
        distances_after.append((candidate - anchors[index]).length)
        signed_clearance_after.append((candidate - anchors[index]).dot(normals[index]))

    shell.data.update(calc_edges=True)
    report = {
        "schemaVersion": 1,
        "paper": {
            "title": PAPER_TITLE,
            "url": PAPER_URL,
            "published": PAPER_DATE,
            "license": PAPER_LICENSE,
        },
        "implementation": {
            "kind": "independent LoBoFit-inspired deterministic prototype",
            "authorsImplementationExecuted": False,
            "authorsCodeCopied": False,
            "target": "SiroinoSotai_PC",
            "object": shell.name,
            "representation": (
                "body-relative residuals encoded in the local frames of the four "
                "strongest garment bones, locally smoothed and blended back"
            ),
            "clearanceM": CLEARANCE_M,
            "maximumWorldDisplacementM": MAX_STEP_M,
            "iterations": ITERATIONS,
            "boundaryStrength": BOUNDARY_STRENGTH,
            "interiorStrength": INTERIOR_STRENGTH,
            "targetPull": TARGET_PULL,
            "requirements": "Blender 4.4.3, Python 3.11, bpy, mathutils BVHTree",
        },
        "metrics": {
            "vertexCount": len(shell.data.vertices),
            "boundaryVertexCount": len(boundary),
            "bodyDistanceBeforeM": _statistics(distances_before),
            "bodyDistanceAfterM": _statistics(distances_after),
            "signedClearanceAfterM": _statistics(signed_clearance_after),
            "worldDisplacementM": _statistics(displacements),
            "localResidualEdgeRmsBeforeM": roughness_before,
            "localResidualEdgeRmsAfterM": roughness_after,
            "verticesBelow75PercentClearance": sum(
                value < CLEARANCE_M * 0.75 for value in signed_clearance_after
            ),
        },
        "expectedEffect": (
            "reduce locally incoherent shell offsets around shoulders, hips, crotch "
            "and openings without globally shrinking the garment"
        ),
        "failureConditions": [
            "topology or five anatomical openings change",
            "maximum displacement exceeds the configured bound",
            "signed body clearance falls below 75 percent of the target",
            "actual five-view or pose renders show worse silhouette or penetration",
        ],
        "adoptionDecision": "PROTOTYPE_PENDING_RENDER_REVIEW",
    }
    return report


def write_report(report: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def install(pattern: ModuleType) -> None:
    """Wrap the canonical outfit constructor with the local-bone fit trial."""
    original = pattern.create_outfit

    def create_outfit(*args, **kwargs):
        garments = original(*args, **kwargs)
        body = args[0]
        armature = args[1]
        shell = next(obj for obj in garments if obj.name == "Heather_Body_Shell")
        report = fit_shell(shell, body, armature)
        write_report(report)
        print("LoBoFit-inspired local-bone trial: " + json.dumps(report["metrics"]))
        return garments

    pattern.create_outfit = create_outfit
    pattern.DESIGN_REVISION = DESIGN_REVISION
