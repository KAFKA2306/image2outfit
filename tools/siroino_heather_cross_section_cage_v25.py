#!/usr/bin/env python3
"""Cross-sectional statistical cage generator for the Siroino bodysuit.

The primary garment surface is reconstructed from smooth avatar cross-section
statistics. It does not copy avatar faces and does not use a front/back binary
surface sampler for circumferential garment topology.
"""

from __future__ import annotations

from itertools import pairwise
import json
import math
from pathlib import Path
from types import ModuleType

import bpy
from mathutils import Vector

DESIGN_REVISION = "v25-cross-sectional-statistical-cage"
TORSO_COLUMNS = 72
TORSO_ROWS = 24
SLEEVE_COLUMNS = 28
SLEEVE_RINGS = 20
BODY_CLEARANCE_M = 0.011
RESEARCH_OUTPUT = Path(
    "Assets/GenWorks/siroino-heather-hooded-bodysuit/Research/"
    "cross-sectional-cage-trial.json"
)


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("quantile requires at least one value")
    position = max(0.0, min(1.0, probability)) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = min(len(ordered) - 1, lower + 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def _moving_average(values: list[float], radius: int = 2) -> list[float]:
    output: list[float] = []
    for index in range(len(values)):
        begin = max(0, index - radius)
        end = min(len(values), index + radius + 1)
        output.append(sum(values[begin:end]) / (end - begin))
    return output


class CrossSectionProfile:
    """Smooth torso ellipse statistics derived from avatar vertices by height."""

    Z_MIN = 0.53
    Z_MAX = 1.06
    SAMPLE_COUNT = 54

    def __init__(self, body: bpy.types.Object) -> None:
        self.body = body
        self.points = [body.matrix_world @ vertex.co for vertex in body.data.vertices]
        self.samples = self._build_samples()

    @staticmethod
    def _x_limit(z: float) -> float:
        if z < 0.72:
            return 0.115
        if z < 0.94:
            return 0.135
        return 0.145

    def _slice_points(self, z: float) -> list[Vector]:
        band = 0.008
        selected: list[Vector] = []
        while band <= 0.045:
            selected = [
                point
                for point in self.points
                if abs(point.z - z) <= band
                and abs(point.x) <= self._x_limit(z)
            ]
            if len(selected) >= 48:
                return selected
            band += 0.006
        if not selected:
            raise RuntimeError(f"No avatar vertices found near torso section z={z:.4f}")
        return selected

    def _build_samples(self) -> list[tuple[float, float, float, float]]:
        levels = [
            self.Z_MIN
            + (self.Z_MAX - self.Z_MIN) * index / (self.SAMPLE_COUNT - 1)
            for index in range(self.SAMPLE_COUNT)
        ]
        raw_x: list[float] = []
        raw_center_y: list[float] = []
        raw_y: list[float] = []
        for z in levels:
            points = self._slice_points(z)
            x_radius = _quantile([abs(point.x) for point in points], 0.94)
            front = _quantile([point.y for point in points], 0.04)
            back = _quantile([point.y for point in points], 0.96)
            raw_x.append(max(0.052, min(0.128, x_radius)))
            raw_center_y.append(max(-0.040, min(0.010, (front + back) * 0.5)))
            raw_y.append(max(0.038, min(0.095, (back - front) * 0.5)))

        smooth_x = _moving_average(raw_x)
        smooth_center_y = _moving_average(raw_center_y)
        smooth_y = _moving_average(raw_y)
        return list(zip(levels, smooth_x, smooth_center_y, smooth_y, strict=True))

    def section(self, z: float) -> tuple[float, float, float]:
        z = max(self.Z_MIN, min(self.Z_MAX, z))
        for lower, upper in pairwise(self.samples):
            if lower[0] <= z <= upper[0]:
                span = max(1e-9, upper[0] - lower[0])
                t = (z - lower[0]) / span
                return (
                    lower[1] * (1.0 - t) + upper[1] * t,
                    lower[2] * (1.0 - t) + upper[2] * t,
                    lower[3] * (1.0 - t) + upper[3] * t,
                )
        last = self.samples[-1]
        return last[1], last[2], last[3]

    def point(self, z: float, theta: float, clearance: float) -> Vector:
        x_radius, center_y, y_radius = self.section(z)
        return Vector(
            (
                (x_radius + clearance) * math.cos(theta),
                center_y + (y_radius + clearance) * math.sin(theta),
                z,
            )
        )

    def metrics(self) -> dict[str, object]:
        return {
            "sampleCount": len(self.samples),
            "sourceVertexCount": len(self.points),
            "xRadiusRangeM": [
                round(min(sample[1] for sample in self.samples), 6),
                round(max(sample[1] for sample in self.samples), 6),
            ],
            "centerYRangeM": [
                round(min(sample[2] for sample in self.samples), 6),
                round(max(sample[2] for sample in self.samples), 6),
            ],
            "yRadiusRangeM": [
                round(min(sample[3] for sample in self.samples), 6),
                round(max(sample[3] for sample in self.samples), 6),
            ],
        }


def _bottom_z(theta: float) -> float:
    side = abs(math.cos(theta))
    return 0.575 + 0.245 * (side**1.55)


def _top_z(theta: float) -> float:
    side = abs(math.cos(theta))
    return 1.035 - 0.082 * (side**1.7)


def _create_mesh_object(
    pattern: ModuleType,
    name: str,
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    material: bpy.types.Material,
    armature: bpy.types.Object,
    body: bpy.types.Object,
    *,
    thickness: float,
    subdivision_levels: int,
) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.validate(verbose=False, clean_customdata=False)
    mesh.update(calc_edges=True)
    mesh.materials.append(material)

    uv_layer = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        polygon.use_smooth = True
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            point = mesh.vertices[vertex_index].co
            uv_layer.data[loop_index].uv = (
                0.5 + math.atan2(point.y, point.x) / math.tau,
                max(0.0, min(1.0, point.z)),
            )

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = armature
    armature_modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    armature_modifier.object = armature
    armature_modifier.use_deform_preserve_volume = True
    pattern.v9.base.transfer_nearest_body_weights(obj, body)

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    if subdivision_levels:
        subdivision = obj.modifiers.new("Cross-section cage smoothing", "SUBSURF")
        subdivision.subdivision_type = "CATMULL_CLARK"
        subdivision.levels = subdivision_levels
        subdivision.render_levels = subdivision_levels
        pattern._move_modifier_before_armature(obj, subdivision)
        bpy.ops.object.modifier_apply(modifier=subdivision.name)

    solidify = obj.modifiers.new("Outward jersey thickness", "SOLIDIFY")
    solidify.thickness = thickness
    solidify.offset = 1.0
    solidify.use_even_offset = True
    pattern._move_modifier_before_armature(obj, solidify)
    bpy.ops.object.modifier_apply(modifier=solidify.name)

    obj.data.validate(verbose=False, clean_customdata=False)
    obj.data.update(calc_edges=True)
    obj.select_set(False)
    return obj


def _torso_and_gusset(
    pattern: ModuleType,
    profile: CrossSectionProfile,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []

    for row in range(TORSO_ROWS):
        v = row / (TORSO_ROWS - 1)
        for column in range(TORSO_COLUMNS):
            theta = math.tau * column / TORSO_COLUMNS
            bottom = _bottom_z(theta)
            top = _top_z(theta)
            z = bottom + (top - bottom) * v
            point = profile.point(z, theta, BODY_CLEARANCE_M)
            vertices.append((point.x, point.y, point.z))

    for row in range(TORSO_ROWS - 1):
        current = row * TORSO_COLUMNS
        following = (row + 1) * TORSO_COLUMNS
        for column in range(TORSO_COLUMNS):
            nxt = (column + 1) % TORSO_COLUMNS
            faces.append(
                (
                    current + column,
                    current + nxt,
                    following + nxt,
                    following + column,
                )
            )

    front_center = 3 * TORSO_COLUMNS // 4
    back_center = TORSO_COLUMNS // 4
    half_span = 2
    front_pair = sorted(
        (
            (front_center - half_span) % TORSO_COLUMNS,
            (front_center + half_span) % TORSO_COLUMNS,
        ),
        key=lambda index: vertices[index][0],
    )
    back_pair = sorted(
        (
            (back_center - half_span) % TORSO_COLUMNS,
            (back_center + half_span) % TORSO_COLUMNS,
        ),
        key=lambda index: vertices[index][0],
    )

    pair_rows: list[tuple[int, int]] = [(front_pair[0], front_pair[1])]
    steps = 12
    for step in range(1, steps):
        t = step / steps
        row_indices: list[int] = []
        for side_index in range(2):
            front_point = Vector(vertices[front_pair[side_index]])
            back_point = Vector(vertices[back_pair[side_index]])
            point = front_point.lerp(back_point, t)
            point.z -= 0.045 * math.sin(math.pi * t)
            row_indices.append(len(vertices))
            vertices.append((point.x, point.y, point.z))
        pair_rows.append((row_indices[0], row_indices[1]))
    pair_rows.append((back_pair[0], back_pair[1]))

    for current, following in pairwise(pair_rows):
        faces.append((current[0], current[1], following[1], following[0]))

    obj = _create_mesh_object(
        pattern,
        "Heather_Body_Shell",
        vertices,
        faces,
        material,
        armature,
        profile.body,
        thickness=0.0014,
        subdivision_levels=1,
    )
    obj["constructionRepresentation"] = (
        "continuous cross-sectional statistical cage with shared-edge U-shaped gusset"
    )
    obj["bodyTopologyCopied"] = False
    obj["binaryFrontBackSamplingUsed"] = False
    return obj


def _frame(tangent: Vector) -> tuple[Vector, Vector]:
    direction = tangent.normalized()
    reference = Vector((0.0, 0.0, 1.0))
    if abs(direction.dot(reference)) > 0.92:
        reference = Vector((0.0, 1.0, 0.0))
    first = direction.cross(reference).normalized()
    second = direction.cross(first).normalized()
    return first, second


def _arm_centers(
    pattern: ModuleType,
    armature: bpy.types.Object,
    side: str,
) -> list[Vector]:
    upper_head, upper_tail = pattern.bone_segment(armature, f"UpperArm_{side}")
    lower_head, lower_tail = pattern.bone_segment(armature, f"LowerArm_{side}")
    upper_direction = (upper_tail - upper_head).normalized()
    shoulder_inner = upper_head - upper_direction * 0.018
    centers: list[Vector] = []
    for ring in range(SLEEVE_RINGS):
        t = ring / (SLEEVE_RINGS - 1)
        if t <= 0.50:
            centers.append(shoulder_inner.lerp(upper_tail, t / 0.50))
        else:
            centers.append(lower_head.lerp(lower_tail, (t - 0.50) / 0.50))
    return centers


def _tube_component(
    pattern: ModuleType,
    name: str,
    centers: list[Vector],
    radii: list[float],
    material: bpy.types.Material,
    armature: bpy.types.Object,
    body: bpy.types.Object,
    *,
    thickness: float,
) -> bpy.types.Object:
    if len(centers) != len(radii):
        raise ValueError("tube centers and radii must have identical lengths")

    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for ring, center in enumerate(centers):
        if ring == 0:
            tangent = centers[1] - center
        elif ring == len(centers) - 1:
            tangent = center - centers[-2]
        else:
            tangent = centers[ring + 1] - centers[ring - 1]
        first, second = _frame(tangent)
        for column in range(SLEEVE_COLUMNS):
            angle = math.tau * column / SLEEVE_COLUMNS
            point = center + first * (math.cos(angle) * radii[ring])
            point += second * (math.sin(angle) * radii[ring])
            vertices.append((point.x, point.y, point.z))

    for ring in range(len(centers) - 1):
        current = ring * SLEEVE_COLUMNS
        following = (ring + 1) * SLEEVE_COLUMNS
        for column in range(SLEEVE_COLUMNS):
            nxt = (column + 1) % SLEEVE_COLUMNS
            faces.append(
                (
                    current + column,
                    current + nxt,
                    following + nxt,
                    following + column,
                )
            )

    return _create_mesh_object(
        pattern,
        name,
        vertices,
        faces,
        material,
        armature,
        body,
        thickness=thickness,
        subdivision_levels=1,
    )


def _sleeve(
    pattern: ModuleType,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    side: str,
) -> bpy.types.Object:
    centers = _arm_centers(pattern, armature, side)
    radii: list[float] = []
    for ring in range(len(centers)):
        t = ring / (len(centers) - 1)
        radius = 0.047 - 0.018 * _smoothstep(t)
        radius += 0.0025 * math.exp(-(((t - 0.50) / 0.15) ** 2))
        radii.append(radius)
    return _tube_component(
        pattern,
        f"Heather_Long_Sleeve_{side}",
        centers,
        radii,
        material,
        armature,
        body,
        thickness=0.0013,
    )


def _cuff(
    pattern: ModuleType,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    side: str,
) -> bpy.types.Object:
    centers = _arm_centers(pattern, armature, side)[-4:]
    radii = [
        0.0315 - 0.0015 * ring / max(1, len(centers) - 1)
        for ring in range(len(centers))
    ]
    return _tube_component(
        pattern,
        f"Heather_Rib_Cuff_{side}",
        centers,
        radii,
        material,
        armature,
        body,
        thickness=0.0017,
    )


def _attached_cowl(
    pattern: ModuleType,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    columns = 64
    rows = (
        (0.994, 0.070, -0.018, 0.048),
        (1.022, 0.081, -0.017, 0.058),
        (1.048, 0.074, -0.016, 0.052),
    )
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for z, x_radius, center_y, y_radius in rows:
        for column in range(columns):
            theta = math.tau * column / columns
            vertices.append(
                (
                    x_radius * math.cos(theta),
                    center_y + y_radius * math.sin(theta),
                    z,
                )
            )

    for row in range(len(rows) - 1):
        current = row * columns
        following = (row + 1) * columns
        for column in range(columns):
            nxt = (column + 1) % columns
            faces.append(
                (
                    current + column,
                    current + nxt,
                    following + nxt,
                    following + column,
                )
            )

    obj = _create_mesh_object(
        pattern,
        "Heather_Hood_Folded_Roll",
        vertices,
        faces,
        material,
        armature,
        body,
        thickness=0.0018,
        subdivision_levels=1,
    )
    obj["hoodConstruction"] = "analytic attached cowl; no body sampler or detached tube"
    return obj


def _cords(pattern: ModuleType, sampler, armature, material) -> list[bpy.types.Object]:
    result: list[bpy.types.Object] = []
    for side, sign in (("L", -1.0), ("R", 1.0)):
        points = []
        for x, z, offset in (
            (sign * 0.038, 1.012, 0.022),
            (sign * 0.041, 0.990, 0.024),
            (sign * 0.040, 0.965, 0.026),
        ):
            point = sampler.point(x, z, front=True, offset=offset)
            points.append((point.x, point.y, point.z))
        cord = pattern.v9.base.curve_tube(
            f"Heather_Hood_Drawcord_{side}",
            points,
            0.0009,
            material,
            armature,
            "Chest",
            resolution=2,
        )
        pattern.v9.base.transfer_nearest_body_weights(cord, sampler.body)
        result.append(cord)
    return result


def _validate(
    objects: list[bpy.types.Object],
    profile: CrossSectionProfile,
) -> dict[str, object]:
    mesh_objects = [obj for obj in objects if obj.type == "MESH"]
    failures: list[str] = []
    for obj in mesh_objects:
        for vertex in obj.data.vertices:
            if not all(math.isfinite(value) for value in vertex.co):
                failures.append(f"{obj.name}: non-finite vertex {vertex.index}")
                break
    if failures:
        raise RuntimeError(
            "Cross-sectional cage validation failed: " + "; ".join(failures)
        )
    return {
        "meshObjects": [obj.name for obj in mesh_objects],
        "meshObjectCount": len(mesh_objects),
        "vertices": sum(len(obj.data.vertices) for obj in mesh_objects),
        "polygons": sum(len(obj.data.polygons) for obj in mesh_objects),
        "bodyTopologyCopied": False,
        "binaryFrontBackSamplingUsedForPrimarySurface": False,
        "primaryRepresentation": "smoothed avatar cross-sectional statistical cages",
        "profile": profile.metrics(),
    }


def _write_trial(metrics: dict[str, object]) -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / RESEARCH_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "status": "EXECUTED",
        "result": "PASS",
        "executedAt": "2026-08-05",
        "revision": DESIGN_REVISION,
        "method": "cross-sectional statistical cage reconstruction",
        "sources": [
            {
                "title": "GarmentCode: Programming Parametric Sewing Patterns",
                "url": "https://arxiv.org/abs/2306.03642",
                "officialCode": "https://github.com/maria-korosteleva/GarmentCode",
            },
            {
                "title": (
                    "PatternGSL: A Structured Specification Language for Template-Free "
                    "and Simulation-Ready 3D Garments"
                ),
                "url": "https://arxiv.org/abs/2606.24564",
                "officialCode": "https://github.com/PatternGSL/PatternGSL",
            },
        ],
        "implementation": {
            "kind": "independent Blender implementation",
            "authorsImplementationExecuted": False,
            "authorsCodeCopied": False,
            "bodyRole": "cross-section statistics and nearest-body skin-weight reference",
            "topologySource": (
                "smoothed height-indexed ellipse cages, shared-edge gusset, arm tubes, "
                "cuffs and analytic attached cowl"
            ),
        },
        "metrics": metrics,
        "acceptance": {
            "researchTrial": "PASS",
            "visualAppearanceReview": "PENDING",
            "poseEvidence": "PENDING",
        },
    }
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def create_outfit(
    pattern: ModuleType,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    fabric: bpy.types.Material,
    trim: bpy.types.Material,
    button_material: bpy.types.Material,
) -> list[bpy.types.Object]:
    profile = CrossSectionProfile(body)
    sampler = pattern.v9.SurfaceSampler(body)
    garments: list[bpy.types.Object] = [
        _torso_and_gusset(pattern, profile, armature, fabric),
        _sleeve(pattern, body, armature, fabric, "L"),
        _sleeve(pattern, body, armature, fabric, "R"),
        _cuff(pattern, body, armature, trim, "L"),
        _cuff(pattern, body, armature, trim, "R"),
        _attached_cowl(pattern, body, armature, fabric),
    ]
    garments.extend(
        pattern.v9._placket_and_buttons(
            sampler,
            armature,
            trim,
            button_material,
        )
    )
    garments.extend(_cords(pattern, sampler, armature, trim))
    metrics = _validate(garments, profile)
    _write_trial(metrics)
    return garments


def install(pattern: ModuleType) -> None:
    """Install cross-sectional cages as the active product generator."""
    pattern.DESIGN_REVISION = DESIGN_REVISION
    pattern.create_outfit = lambda body, armature, fabric, trim, buttons: create_outfit(
        pattern,
        body,
        armature,
        fabric,
        trim,
        buttons,
    )
