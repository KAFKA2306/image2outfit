#!/usr/bin/env python3
"""v28 overrides for the closed-component hooded bodysuit generator.

The stable v27 polar-profile and mesh helpers are reused, while the three
visually rejected mechanisms are replaced: the pointed underbody, the bulky
constant-radius sleeve root, and the broad sheet-like rear hood.
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

import siroino_heather_closed_components_v27 as base

DESIGN_REVISION = "v28-flat-saddle-contoured-cap-hood-roll"
RESEARCH_OUTPUT = Path(
    "Assets/GenWorks/siroino-heather-hooded-bodysuit/Research/"
    "flat-saddle-cap-hood-roll-trial.json"
)


def _bottom_z(theta: float) -> float:
    """Broaden the front/back low region instead of converging to a point."""
    side = abs(math.cos(theta))
    return 0.665 + 0.105 * (side**1.80)


def _torso_and_saddle(
    pattern: ModuleType,
    profile: base.PolarBodyProfile,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    body_tree: BVHTree,
) -> bpy.types.Object:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for row in range(base.TORSO_ROWS):
        v = row / (base.TORSO_ROWS - 1)
        for column in range(base.ANGLE_COUNT):
            theta = math.tau * column / base.ANGLE_COUNT
            bottom = _bottom_z(theta)
            top = 1.005 - 0.010 * base._side_strength(theta)
            z = bottom + (top - bottom) * v
            yoke_boost = (0.008 + 0.018 * base._side_strength(theta)) * (v**5)
            point = profile.point(z, theta, base.BODY_CLEARANCE_M, yoke_boost)
            vertices.append((point.x, point.y, point.z))

    for row in range(base.TORSO_ROWS - 1):
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

    top_row = (base.TORSO_ROWS - 1) * base.ANGLE_COUNT
    neck_start = len(vertices)
    for column in range(base.ANGLE_COUNT):
        theta = math.tau * column / base.ANGLE_COUNT
        vertices.append(
            (
                0.080 * math.cos(theta),
                -0.006 + 0.060 * math.sin(theta),
                1.018 + 0.003 * math.sin(theta),
            )
        )
    for column in range(base.ANGLE_COUNT):
        nxt = (column + 1) % base.ANGLE_COUNT
        faces.append(
            (
                top_row + column,
                top_row + nxt,
                neck_start + nxt,
                neck_start + column,
            )
        )

    front_center = 3 * base.ANGLE_COUNT // 4
    back_center = base.ANGLE_COUNT // 4
    offsets = tuple(range(-14, 15, 2))
    front_row = tuple(
        (front_center + offset) % base.ANGLE_COUNT for offset in offsets
    )
    back_row = tuple(
        (back_center - offset) % base.ANGLE_COUNT for offset in offsets
    )
    saddle_rows: list[tuple[int, ...]] = [front_row]
    longitudinal_steps = 16
    for step in range(1, longitudinal_steps):
        t = step / longitudinal_steps
        indices: list[int] = []
        for front_index, back_index in zip(front_row, back_row, strict=True):
            front_point = Vector(vertices[front_index])
            back_point = Vector(vertices[back_index])
            point = front_point.lerp(back_point, t)
            point.z -= 0.012 * math.sin(math.pi * t)
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
        minimum_clearance=0.012,
    )
    obj["constructionRepresentation"] = (
        "angular torso field, continuous yoke and fifteen-column flat pelvic saddle"
    )
    obj["bodyTopologyCopied"] = False
    obj["pelvicSaddleColumns"] = len(front_row)
    return obj


def _arm_centers(
    pattern: ModuleType,
    armature: bpy.types.Object,
    side: str,
) -> list[Vector]:
    upper_head, upper_tail = pattern.bone_segment(armature, f"UpperArm_{side}")
    lower_head, lower_tail = pattern.bone_segment(armature, f"LowerArm_{side}")
    direction = (upper_tail - upper_head).normalized()
    shoulder_inner = upper_head - direction * 0.038
    centers: list[Vector] = []
    for ring in range(base.SLEEVE_RINGS):
        t = ring / (base.SLEEVE_RINGS - 1)
        if t <= 0.50:
            centers.append(shoulder_inner.lerp(upper_tail, t / 0.50))
        else:
            centers.append(lower_head.lerp(lower_tail, (t - 0.50) / 0.50))
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
        if t < 0.10:
            radius = 0.034 + 0.014 * base._smoothstep(t / 0.10)
        elif t < 0.28:
            radius = 0.048 - 0.010 * base._smoothstep((t - 0.10) / 0.18)
        else:
            radius = 0.038 - 0.012 * base._smoothstep((t - 0.28) / 0.72)
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
        thickness=0.0013,
        minimum_clearance=0.008,
    )


def _folded_back_hood(
    pattern: ModuleType,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    body_tree: BVHTree,
) -> bpy.types.Object:
    del body_tree
    points: list[tuple[float, float, float]] = []
    samples = 33
    for index in range(samples):
        theta = math.pi * index / (samples - 1)
        points.append(
            (
                0.088 * math.cos(theta),
                0.012 + 0.062 * math.sin(theta),
                1.018 + 0.018 * math.sin(theta),
            )
        )
    hood = pattern.v9.base.curve_tube(
        "Heather_Hood_Folded_Roll",
        points,
        0.019,
        material,
        armature,
        "Chest",
        resolution=4,
    )
    pattern.v9.base.transfer_nearest_body_weights(hood, body)
    hood["hoodConstruction"] = "contoured U-shaped folded hood roll around rear neck"
    return hood


def _validate(
    objects: list[bpy.types.Object],
    profile: base.PolarBodyProfile,
) -> dict[str, object]:
    result = base._ORIGINAL_VALIDATE(objects, profile)
    result["pelvicSaddleColumns"] = 15
    result["primaryRepresentation"] = (
        "polar torso with flat saddle, contoured sleeve caps and hood roll"
    )
    return result


def _rewrite_trial() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / RESEARCH_OUTPUT
    data = json.loads(path.read_text(encoding="utf-8"))
    data["revision"] = DESIGN_REVISION
    data["method"] = "flat saddle, contoured sleeve caps and folded hood roll"
    data["implementation"]["topologySource"] = (
        "continuous torso/yoke, fifteen-column flat saddle, contoured sleeve caps, "
        "fitted cuffs and U-shaped folded hood roll"
    )
    data["metrics"]["pelvicSaddleColumns"] = 15
    data["metrics"]["primaryRepresentation"] = (
        "polar torso with flat saddle, contoured sleeve caps and hood roll"
    )
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _activate_overrides() -> None:
    base.DESIGN_REVISION = DESIGN_REVISION
    base.RESEARCH_OUTPUT = RESEARCH_OUTPUT
    base._bottom_z = _bottom_z
    base._torso_and_saddle = _torso_and_saddle
    base._arm_centers = _arm_centers
    base._sleeve = _sleeve
    base._folded_back_hood = _folded_back_hood
    if not hasattr(base, "_ORIGINAL_VALIDATE"):
        base._ORIGINAL_VALIDATE = base._validate
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
    """Install the v28 visual-mechanism replacements."""
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
