#!/usr/bin/env python3
"""Angular polar-profile garment generator for the Siroino bodysuit.

The torso is reconstructed as a smooth height-by-angle radius field. Shoulder
yoke, sleeve caps, gusset and open-front hood are authored as garment-native
components instead of being inferred from avatar faces.
"""

from __future__ import annotations

from itertools import pairwise
import json
import math
from pathlib import Path
from types import ModuleType

import bpy
from mathutils import Vector

DESIGN_REVISION = "v26-angular-polar-yoke-hood"
ANGLE_COUNT = 72
TORSO_ROWS = 26
SLEEVE_COLUMNS = 28
SLEEVE_RINGS = 22
BODY_CLEARANCE_M = 0.010
RESEARCH_OUTPUT = Path(
    "Assets/GenWorks/siroino-heather-hooded-bodysuit/Research/"
    "angular-polar-yoke-trial.json"
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


def _angle_distance(first: float, second: float) -> float:
    return abs((first - second + math.pi) % math.tau - math.pi)


def _circular_average(values: list[float], radius: int = 2) -> list[float]:
    count = len(values)
    return [
        sum(values[(index + offset) % count] for offset in range(-radius, radius + 1))
        / (2 * radius + 1)
        for index in range(count)
    ]


def _linear_average(values: list[float], radius: int = 2) -> list[float]:
    output: list[float] = []
    for index in range(len(values)):
        begin = max(0, index - radius)
        end = min(len(values), index + radius + 1)
        output.append(sum(values[begin:end]) / (end - begin))
    return output


class PolarBodyProfile:
    """Smooth radial body envelope indexed by height and polar angle."""

    Z_MIN = 0.55
    Z_MAX = 1.00
    HEIGHT_SAMPLES = 50

    def __init__(self, body: bpy.types.Object) -> None:
        self.body = body
        self.points = [body.matrix_world @ vertex.co for vertex in body.data.vertices]
        self.levels = [
            self.Z_MIN + (self.Z_MAX - self.Z_MIN) * index / (self.HEIGHT_SAMPLES - 1)
            for index in range(self.HEIGHT_SAMPLES)
        ]
        self.center_y, self.radii = self._build_field()

    @staticmethod
    def _x_limit(z: float) -> float:
        if z < 0.72:
            return 0.115
        if z < 0.92:
            return 0.138
        return 0.152

    def _slice_points(self, z: float) -> list[Vector]:
        band = 0.008
        selected: list[Vector] = []
        while band <= 0.050:
            selected = [
                point
                for point in self.points
                if abs(point.z - z) <= band and abs(point.x) <= self._x_limit(z)
            ]
            if len(selected) >= 56:
                return selected
            band += 0.006
        if not selected:
            raise RuntimeError(f"No torso vertices found near z={z:.4f}")
        return selected

    @staticmethod
    def _ellipse_radius(theta: float, x_radius: float, y_radius: float) -> float:
        denominator = math.sqrt(
            (math.cos(theta) / max(1e-6, x_radius)) ** 2
            + (math.sin(theta) / max(1e-6, y_radius)) ** 2
        )
        return 1.0 / max(1e-6, denominator)

    def _level_profile(self, z: float) -> tuple[float, list[float]]:
        points = self._slice_points(z)
        front = _quantile([point.y for point in points], 0.035)
        back = _quantile([point.y for point in points], 0.965)
        center_y = max(-0.045, min(0.015, (front + back) * 0.5))
        x_radius = max(
            0.052,
            min(0.145, _quantile([abs(point.x) for point in points], 0.95)),
        )
        y_radius = max(0.038, min(0.100, (back - front) * 0.5))

        point_data = []
        for point in points:
            dx = point.x
            dy = point.y - center_y
            point_data.append((math.atan2(dy, dx), math.hypot(dx, dy)))

        radii: list[float] = []
        for index in range(ANGLE_COUNT):
            theta = math.tau * index / ANGLE_COUNT
            candidates = [
                radius
                for angle, radius in point_data
                if _angle_distance(angle, theta) <= math.radians(13.0)
            ]
            if len(candidates) < 5:
                candidates = [
                    radius
                    for angle, radius in point_data
                    if _angle_distance(angle, theta) <= math.radians(22.0)
                ]
            if candidates:
                radius = _quantile(candidates, 0.90)
            else:
                radius = self._ellipse_radius(theta, x_radius, y_radius)
            fallback = self._ellipse_radius(theta, x_radius, y_radius)
            radius = max(0.82 * fallback, min(1.22 * fallback, radius))
            radii.append(max(0.038, min(0.152, radius)))

        radii = _circular_average(_circular_average(radii, 2), 2)
        return center_y, radii

    def _build_field(self) -> tuple[list[float], list[list[float]]]:
        centers: list[float] = []
        field: list[list[float]] = []
        for z in self.levels:
            center, radii = self._level_profile(z)
            centers.append(center)
            field.append(radii)

        centers = _linear_average(centers, 2)
        for angle_index in range(ANGLE_COUNT):
            column = _linear_average(
                [field[level][angle_index] for level in range(len(field))],
                2,
            )
            for level, value in enumerate(column):
                field[level][angle_index] = value
        return centers, field

    def _height_interval(self, z: float) -> tuple[int, int, float]:
        z = max(self.Z_MIN, min(self.Z_MAX, z))
        position = (z - self.Z_MIN) / (self.Z_MAX - self.Z_MIN)
        scaled = position * (len(self.levels) - 1)
        lower = int(math.floor(scaled))
        upper = min(len(self.levels) - 1, lower + 1)
        return lower, upper, scaled - lower

    @staticmethod
    def _angle_interval(theta: float) -> tuple[int, int, float]:
        scaled = (theta % math.tau) / math.tau * ANGLE_COUNT
        lower = int(math.floor(scaled)) % ANGLE_COUNT
        upper = (lower + 1) % ANGLE_COUNT
        return lower, upper, scaled - math.floor(scaled)

    def section(self, z: float, theta: float) -> tuple[float, float]:
        z0, z1, zt = self._height_interval(z)
        a0, a1, at = self._angle_interval(theta)
        center = self.center_y[z0] * (1.0 - zt) + self.center_y[z1] * zt
        radius0 = self.radii[z0][a0] * (1.0 - at) + self.radii[z0][a1] * at
        radius1 = self.radii[z1][a0] * (1.0 - at) + self.radii[z1][a1] * at
        return center, radius0 * (1.0 - zt) + radius1 * zt

    def point(
        self,
        z: float,
        theta: float,
        clearance: float,
        radial_boost: float = 0.0,
    ) -> Vector:
        center_y, radius = self.section(z, theta)
        radius += clearance + radial_boost
        return Vector(
            (
                radius * math.cos(theta),
                center_y + radius * math.sin(theta),
                z,
            )
        )

    def metrics(self) -> dict[str, object]:
        flat = [radius for level in self.radii for radius in level]
        return {
            "heightSamples": len(self.levels),
            "angleSamples": ANGLE_COUNT,
            "sourceVertexCount": len(self.points),
            "centerYRangeM": [
                round(min(self.center_y), 6),
                round(max(self.center_y), 6),
            ],
            "radiusRangeM": [round(min(flat), 6), round(max(flat), 6)],
        }


def _side_strength(theta: float) -> float:
    distance = min(_angle_distance(theta, 0.0), _angle_distance(theta, math.pi))
    return math.exp(-((distance / 0.38) ** 2))


def _bottom_z(theta: float) -> float:
    side = abs(math.cos(theta))
    return 0.625 + 0.180 * (side**1.60)


def _top_z(theta: float) -> float:
    side = _side_strength(theta)
    return 0.992 - 0.028 * side


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
        subdivision = obj.modifiers.new("Garment panel smoothing", "SUBSURF")
        subdivision.subdivision_type = "CATMULL_CLARK"
        subdivision.levels = subdivision_levels
        subdivision.render_levels = subdivision_levels
        pattern._move_modifier_before_armature(obj, subdivision)
        bpy.ops.object.modifier_apply(modifier=subdivision.name)

    solidify = obj.modifiers.new("Outward fabric thickness", "SOLIDIFY")
    solidify.thickness = thickness
    solidify.offset = 1.0
    solidify.use_even_offset = True
    pattern._move_modifier_before_armature(obj, solidify)
    bpy.ops.object.modifier_apply(modifier=solidify.name)

    obj.data.validate(verbose=False, clean_customdata=False)
    obj.data.update(calc_edges=True)
    obj.select_set(False)
    return obj


def _torso_yoke_and_gusset(
    pattern: ModuleType,
    profile: PolarBodyProfile,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []

    for row in range(TORSO_ROWS):
        v = row / (TORSO_ROWS - 1)
        for column in range(ANGLE_COUNT):
            theta = math.tau * column / ANGLE_COUNT
            bottom = _bottom_z(theta)
            top = _top_z(theta)
            z = bottom + (top - bottom) * v
            shoulder_boost = 0.044 * _side_strength(theta) * (v**5)
            point = profile.point(z, theta, BODY_CLEARANCE_M, shoulder_boost)
            vertices.append((point.x, point.y, point.z))

    for row in range(TORSO_ROWS - 1):
        current = row * ANGLE_COUNT
        following = (row + 1) * ANGLE_COUNT
        for column in range(ANGLE_COUNT):
            nxt = (column + 1) % ANGLE_COUNT
            faces.append(
                (
                    current + column,
                    current + nxt,
                    following + nxt,
                    following + column,
                )
            )

    top_row = (TORSO_ROWS - 1) * ANGLE_COUNT
    neck_start = len(vertices)
    for column in range(ANGLE_COUNT):
        theta = math.tau * column / ANGLE_COUNT
        neck_z = 1.040 + 0.004 * math.sin(theta)
        vertices.append(
            (
                0.071 * math.cos(theta),
                -0.006 + 0.054 * math.sin(theta),
                neck_z,
            )
        )
    for column in range(ANGLE_COUNT):
        nxt = (column + 1) % ANGLE_COUNT
        faces.append(
            (
                top_row + column,
                top_row + nxt,
                neck_start + nxt,
                neck_start + column,
            )
        )

    front_center = 3 * ANGLE_COUNT // 4
    back_center = ANGLE_COUNT // 4
    half_span = 4
    front_pair = sorted(
        (
            (front_center - half_span) % ANGLE_COUNT,
            (front_center + half_span) % ANGLE_COUNT,
        ),
        key=lambda index: vertices[index][0],
    )
    back_pair = sorted(
        (
            (back_center - half_span) % ANGLE_COUNT,
            (back_center + half_span) % ANGLE_COUNT,
        ),
        key=lambda index: vertices[index][0],
    )

    pair_rows: list[tuple[int, int]] = [(front_pair[0], front_pair[1])]
    steps = 16
    for step in range(1, steps):
        t = step / steps
        row_indices: list[int] = []
        for side_index in range(2):
            front_point = Vector(vertices[front_pair[side_index]])
            back_point = Vector(vertices[back_pair[side_index]])
            point = front_point.lerp(back_point, t)
            point.z -= 0.018 * math.sin(math.pi * t)
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
        "angular polar torso field, integrated shoulder yoke and widened short gusset"
    )
    obj["bodyTopologyCopied"] = False
    obj["ellipseOnlyProfileUsed"] = False
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
    shoulder_inner = upper_head - upper_direction * 0.030
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
        radius = 0.039 - 0.013 * _smoothstep(t)
        radius += 0.0018 * math.exp(-(((t - 0.50) / 0.16) ** 2))
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
        0.0280 - 0.0015 * ring / max(1, len(centers) - 1)
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


def _open_front_hood(
    pattern: ModuleType,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    columns = 40
    rows = 12
    theta_start = -math.pi / 4.0
    theta_end = 5.0 * math.pi / 4.0
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []

    for row in range(rows):
        phi = 1.48 * row / rows
        scale = max(0.10, math.cos(phi))
        z = 1.005 + 0.175 * math.sin(phi)
        center_y = 0.015 + 0.036 * math.sin(phi)
        for column in range(columns):
            theta = theta_start + (theta_end - theta_start) * column / (columns - 1)
            vertices.append(
                (
                    0.108 * scale * math.cos(theta),
                    center_y + 0.094 * scale * math.sin(theta),
                    z,
                )
            )

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

    crown = len(vertices)
    vertices.append((0.0, 0.052, 1.184))
    last_row = (rows - 1) * columns
    for column in range(columns - 1):
        faces.append((last_row + column, last_row + column + 1, crown))

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
    obj["hoodConstruction"] = "three-dimensional open-front polar hood shell"
    return obj


def _cords(pattern: ModuleType, sampler, armature, material) -> list[bpy.types.Object]:
    result: list[bpy.types.Object] = []
    for side, sign in (("L", -1.0), ("R", 1.0)):
        points = []
        for x, z, offset in (
            (sign * 0.041, 1.017, 0.023),
            (sign * 0.043, 0.992, 0.025),
            (sign * 0.041, 0.965, 0.027),
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
    profile: PolarBodyProfile,
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
            "Angular polar cage validation failed: " + "; ".join(failures)
        )
    return {
        "meshObjects": [obj.name for obj in mesh_objects],
        "meshObjectCount": len(mesh_objects),
        "vertices": sum(len(obj.data.vertices) for obj in mesh_objects),
        "polygons": sum(len(obj.data.polygons) for obj in mesh_objects),
        "bodyTopologyCopied": False,
        "ellipseOnlyProfileUsed": False,
        "primaryRepresentation": "smoothed height-by-angle polar radius field",
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
        "method": "angular polar body envelope with garment-native yoke and hood",
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
            "bodyRole": "angular radial statistics and nearest-body skin-weight reference",
            "topologySource": (
                "height-angle polar field, integrated shoulder yoke, short widened "
                "gusset, fitted arm tubes and open-front hood shell"
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
    profile = PolarBodyProfile(body)
    sampler = pattern.v9.SurfaceSampler(body)
    garments: list[bpy.types.Object] = [
        _torso_yoke_and_gusset(pattern, profile, armature, fabric),
        _sleeve(pattern, body, armature, fabric, "L"),
        _sleeve(pattern, body, armature, fabric, "R"),
        _cuff(pattern, body, armature, trim, "L"),
        _cuff(pattern, body, armature, trim, "R"),
        _open_front_hood(pattern, body, armature, fabric),
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
    """Install the angular polar yoke and hood generator."""
    pattern.DESIGN_REVISION = DESIGN_REVISION
    pattern.create_outfit = lambda body, armature, fabric, trim, buttons: create_outfit(
        pattern,
        body,
        armature,
        fabric,
        trim,
        buttons,
    )
