#!/usr/bin/env python3
"""v29 manifold-yoke overrides for the Siroino hooded bodysuit.

This revision replaces the remaining visually rejected mechanisms: abrupt
clearance spikes, the single-step rectangular neckline, rounded shoulder bulbs,
and the horizontal padded hood roll.
"""

from __future__ import annotations

import json
import math
from itertools import pairwise
from pathlib import Path
from types import ModuleType

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

import siroino_heather_fused_roll_v28 as previous

base = previous.base
DESIGN_REVISION = "v29-smoothed-clearance-tapered-yoke-fitted-sleeve"
RESEARCH_OUTPUT = Path(
    "Assets/GenWorks/siroino-heather-hooded-bodysuit/Research/"
    "smoothed-clearance-yoke-trial.json"
)


def _enforce_clearance(
    obj: bpy.types.Object,
    body_tree: BVHTree,
    minimum: float,
    maximum_step: float = 0.012,
) -> dict[str, float | int]:
    """Project with a topology-smoothed bounded displacement field."""
    inverse = obj.matrix_world.inverted()
    normals: list[Vector | None] = []
    displacements: list[float] = []
    for vertex in obj.data.vertices:
        world = obj.matrix_world @ vertex.co
        nearest, normal, _index, _distance = body_tree.find_nearest(world)
        if nearest is None or normal is None or normal.length_squared <= 1e-12:
            normals.append(None)
            displacements.append(0.0)
            continue
        normal = normal.normalized()
        signed = (world - nearest).dot(normal)
        normals.append(normal)
        displacements.append(min(maximum_step, max(0.0, minimum - signed)))

    neighbors: list[list[int]] = [[] for _ in obj.data.vertices]
    for edge in obj.data.edges:
        first, second = edge.vertices
        neighbors[first].append(second)
        neighbors[second].append(first)
    for _ in range(4):
        smoothed: list[float] = []
        for index, value in enumerate(displacements):
            adjacent = neighbors[index]
            if not adjacent:
                smoothed.append(value)
                continue
            average = sum(displacements[item] for item in adjacent) / len(adjacent)
            smoothed.append(min(maximum_step, 0.55 * value + 0.45 * average))
        displacements = smoothed

    adjusted = 0
    total_step = 0.0
    maximum_applied = 0.0
    for vertex, normal, step in zip(
        obj.data.vertices,
        normals,
        displacements,
        strict=True,
    ):
        if normal is None or step <= 1e-8:
            continue
        world = obj.matrix_world @ vertex.co
        vertex.co = inverse @ (world + normal * step)
        adjusted += 1
        total_step += step
        maximum_applied = max(maximum_applied, step)
    obj.data.update(calc_edges=True)
    return {
        "adjustedVertices": adjusted,
        "meanStepM": total_step / adjusted if adjusted else 0.0,
        "maximumStepM": maximum_applied,
        "minimumClearanceM": minimum,
        "smoothingIterations": 4,
    }


def _bottom_z(theta: float) -> float:
    side = abs(math.cos(theta))
    return 0.710 + 0.055 * (side**2.0)


def _torso_and_saddle(
    pattern: ModuleType,
    profile: base.PolarBodyProfile,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    body_tree: BVHTree,
) -> bpy.types.Object:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    torso_rows = 30
    for row in range(torso_rows):
        v = row / (torso_rows - 1)
        for column in range(base.ANGLE_COUNT):
            theta = math.tau * column / base.ANGLE_COUNT
            bottom = _bottom_z(theta)
            top = 1.000 - 0.006 * base._side_strength(theta)
            z = bottom + (top - bottom) * v
            yoke_boost = (0.004 + 0.012 * base._side_strength(theta)) * (v**6)
            point = profile.point(z, theta, 0.020, yoke_boost)
            vertices.append((point.x, point.y, point.z))

    for row in range(torso_rows - 1):
        current = row * base.ANGLE_COUNT
        following = (row + 1) * base.ANGLE_COUNT
        for column in range(base.ANGLE_COUNT):
            nxt = (column + 1) % base.ANGLE_COUNT
            faces.append(
                (
                    current + column,
                    current + nxt,
                    following + nxt,
                    following + column,
                )
            )

    outer_top = (torso_rows - 1) * base.ANGLE_COUNT
    previous_ring = tuple(outer_top + column for column in range(base.ANGLE_COUNT))
    yoke_rings = 5
    for step in range(1, yoke_rings + 1):
        t = step / yoke_rings
        ring_start = len(vertices)
        current_ring: list[int] = []
        for column in range(base.ANGLE_COUNT):
            theta = math.tau * column / base.ANGLE_COUNT
            outer = Vector(vertices[outer_top + column])
            target = Vector(
                (
                    0.057 * math.cos(theta),
                    -0.006 + 0.045 * math.sin(theta),
                    1.088 + 0.004 * math.sin(theta),
                )
            )
            eased = base._smoothstep(t)
            point = outer.lerp(target, eased)
            point.z += 0.010 * math.sin(math.pi * t)
            vertices.append((point.x, point.y, point.z))
            current_ring.append(ring_start + column)
        current_tuple = tuple(current_ring)
        for column in range(base.ANGLE_COUNT):
            nxt = (column + 1) % base.ANGLE_COUNT
            faces.append(
                (
                    previous_ring[column],
                    previous_ring[nxt],
                    current_tuple[nxt],
                    current_tuple[column],
                )
            )
        previous_ring = current_tuple

    front_center = 3 * base.ANGLE_COUNT // 4
    back_center = base.ANGLE_COUNT // 4
    offsets = tuple(range(-16, 17, 2))
    front_row = tuple(
        (front_center + offset) % base.ANGLE_COUNT for offset in offsets
    )
    back_row = tuple(
        (back_center - offset) % base.ANGLE_COUNT for offset in offsets
    )
    saddle_rows: list[tuple[int, ...]] = [front_row]
    longitudinal_steps = 14
    for step in range(1, longitudinal_steps):
        t = step / longitudinal_steps
        indices: list[int] = []
        for front_index, back_index in zip(front_row, back_row, strict=True):
            front_point = Vector(vertices[front_index])
            back_point = Vector(vertices[back_index])
            point = front_point.lerp(back_point, t)
            point.z -= 0.004 * math.sin(math.pi * t)
            indices.append(len(vertices))
            vertices.append((point.x, point.y, point.z))
        saddle_rows.append(tuple(indices))
    saddle_rows.append(back_row)
    for current, following in pairwise(saddle_rows):
        for column in range(len(current) - 1):
            faces.append(
                (
                    current[column],
                    current[column + 1],
                    following[column + 1],
                    following[column],
                )
            )

    obj = base._create_mesh_object(
        pattern,
        "Heather_Body_Shell",
        vertices,
        faces,
        material,
        armature,
        profile.body,
        body_tree,
        thickness=0.0014,
        subdivision_levels=0,
        minimum_clearance=0.006,
    )
    obj["constructionRepresentation"] = (
        "polar torso, five-ring tapered yoke and seventeen-column shallow saddle"
    )
    obj["bodyTopologyCopied"] = False
    obj["pelvicSaddleColumns"] = len(front_row)
    obj["taperedYokeRings"] = yoke_rings
    return obj


def _arm_centers(
    pattern: ModuleType,
    armature: bpy.types.Object,
    side: str,
) -> list[Vector]:
    upper_head, upper_tail = pattern.bone_segment(armature, f"UpperArm_{side}")
    lower_head, lower_tail = pattern.bone_segment(armature, f"LowerArm_{side}")
    direction = (upper_tail - upper_head).normalized()
    shoulder_inner = upper_head - direction * 0.018
    centers: list[Vector] = []
    for ring in range(base.SLEEVE_RINGS):
        t = ring / (base.SLEEVE_RINGS - 1)
        if t <= 0.52:
            centers.append(shoulder_inner.lerp(upper_tail, t / 0.52))
        else:
            centers.append(lower_head.lerp(lower_tail, (t - 0.52) / 0.48))
    return centers


def _sleeve(
    pattern: ModuleType,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    body_tree: BVHTree,
    side: str,
) -> bpy.types.Object:
    centers = _arm_centers(pattern, armature, side)
    radii: list[float] = []
    for ring in range(len(centers)):
        t = ring / (len(centers) - 1)
        if t < 0.12:
            radius = 0.027 + 0.006 * base._smoothstep(t / 0.12)
        elif t < 0.36:
            radius = 0.033 - 0.001 * base._smoothstep((t - 0.12) / 0.24)
        else:
            radius = 0.032 - 0.007 * base._smoothstep((t - 0.36) / 0.64)
        radii.append(radius)
    return base._tube_component(
        pattern,
        f"Heather_Long_Sleeve_{side}",
        centers,
        radii,
        material,
        armature,
        body,
        body_tree,
        thickness=0.0012,
        minimum_clearance=0.004,
    )


def _folded_back_hood(
    pattern: ModuleType,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    body_tree: BVHTree,
) -> bpy.types.Object:
    columns = 33
    rows = 6
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for row in range(rows):
        v = row / (rows - 1)
        for column in range(columns):
            theta = math.pi * column / (columns - 1)
            x_radius = 0.060 + 0.025 * v
            y_radius = 0.043 + 0.032 * v
            z = 1.082 - 0.036 * v + 0.010 * math.sin(theta) * (1.0 - v)
            y = 0.004 + y_radius * math.sin(theta) + 0.012 * v
            vertices.append((x_radius * math.cos(theta), y, z))
    for row in range(rows - 1):
        current = row * columns
        following = (row + 1) * columns
        for column in range(columns - 1):
            faces.append(
                (
                    current + column,
                    current + column + 1,
                    following + column + 1,
                    following + column,
                )
            )
    obj = base._create_mesh_object(
        pattern,
        "Heather_Hood_Folded_Roll",
        vertices,
        faces,
        material,
        armature,
        body,
        body_tree,
        thickness=0.0016,
        subdivision_levels=1,
        minimum_clearance=0.004,
    )
    obj["hoodConstruction"] = (
        "compact six-row folded hood shell confined to the rear neck"
    )
    return obj


def _validate(
    objects: list[bpy.types.Object],
    profile: base.PolarBodyProfile,
) -> dict[str, object]:
    result = base._ORIGINAL_VALIDATE(objects, profile)
    result["pelvicSaddleColumns"] = 17
    result["taperedYokeRings"] = 5
    result["clearanceDisplacementSmoothing"] = 4
    result["primaryRepresentation"] = (
        "polar torso with tapered yoke, shallow saddle, fitted sleeves and compact hood"
    )
    return result


def _rewrite_trial() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / RESEARCH_OUTPUT
    data = json.loads(path.read_text(encoding="utf-8"))
    data["revision"] = DESIGN_REVISION
    data["method"] = (
        "smoothed bounded clearance, tapered yoke, fitted sleeves and compact hood"
    )
    data["implementation"]["topologySource"] = (
        "continuous polar torso, five-ring tapered yoke, seventeen-column shallow "
        "saddle, fitted sleeve caps, cuffs and compact six-row rear-neck hood"
    )
    data["metrics"]["pelvicSaddleColumns"] = 17
    data["metrics"]["taperedYokeRings"] = 5
    data["metrics"]["clearanceDisplacementSmoothing"] = 4
    data["metrics"]["primaryRepresentation"] = (
        "polar torso with tapered yoke, shallow saddle, fitted sleeves and compact hood"
    )
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _activate_overrides() -> None:
    previous._activate_overrides()
    base.DESIGN_REVISION = DESIGN_REVISION
    base.RESEARCH_OUTPUT = RESEARCH_OUTPUT
    base._enforce_clearance = _enforce_clearance
    base._bottom_z = _bottom_z
    base._torso_and_saddle = _torso_and_saddle
    base._arm_centers = _arm_centers
    base._sleeve = _sleeve
    base._folded_back_hood = _folded_back_hood
    base._validate = _validate


def create_outfit(
    pattern: ModuleType,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    fabric: bpy.types.Material,
    trim: bpy.types.Material,
    button_material: bpy.types.Material,
) -> list[bpy.types.Object]:
    _activate_overrides()
    garments = base.create_outfit(
        pattern,
        body,
        armature,
        fabric,
        trim,
        button_material,
    )
    _rewrite_trial()
    return garments


def install(pattern: ModuleType) -> None:
    """Install the v29 manifold-yoke visual replacements."""
    _activate_overrides()
    pattern.DESIGN_REVISION = DESIGN_REVISION
    pattern.create_outfit = lambda body, armature, fabric, trim, buttons: create_outfit(
        pattern,
        body,
        armature,
        fabric,
        trim,
        buttons,
    )
