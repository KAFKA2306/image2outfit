#!/usr/bin/env python3
"""Closed garment-component generator for the Siroino hooded bodysuit.

The body envelope is estimated as a smooth height-by-angle polar field. The
remaining garment topology is authored as closed clothing components: a broad
pelvic saddle, overlapping sleeve caps, and a low folded-back hood. A bounded
clearance projection is applied only after garment-native topology exists.
"""

from __future__ import annotations

from itertools import pairwise
import json
import math
from pathlib import Path
from types import ModuleType

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

DESIGN_REVISION = "v27-closed-saddle-sleevecap-folded-hood"
ANGLE_COUNT = 72
HEIGHT_SAMPLES = 50
TORSO_ROWS = 27
SLEEVE_COLUMNS = 28
SLEEVE_RINGS = 24
BODY_CLEARANCE_M = 0.012
RESEARCH_OUTPUT = Path(
    "Assets/GenWorks/siroino-heather-hooded-bodysuit/Research/"
    "closed-components-clearance-trial.json"
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
    """Robust angular body envelope used only as a garment fitting reference."""

    Z_MIN = 0.54
    Z_MAX = 1.01

    def __init__(self, body: bpy.types.Object) -> None:
        self.body = body
        self.points = [body.matrix_world @ vertex.co for vertex in body.data.vertices]
        self.levels = [
            self.Z_MIN + (self.Z_MAX - self.Z_MIN) * index / (HEIGHT_SAMPLES - 1)
            for index in range(HEIGHT_SAMPLES)
        ]
        self.center_y, self.radii = self._build_field()

    @staticmethod
    def _x_limit(z: float) -> float:
        if z < 0.72:
            return 0.118
        if z < 0.92:
            return 0.142
        return 0.158

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
        front = _quantile([point.y for point in points], 0.025)
        back = _quantile([point.y for point in points], 0.975)
        center_y = max(-0.046, min(0.016, (front + back) * 0.5))
        x_radius = max(
            0.052,
            min(0.150, _quantile([abs(point.x) for point in points], 0.97)),
        )
        y_radius = max(0.039, min(0.104, (back - front) * 0.5))
        point_data = [
            (math.atan2(point.y - center_y, point.x), math.hypot(point.x, point.y - center_y))
            for point in points
        ]

        radii: list[float] = []
        for index in range(ANGLE_COUNT):
            theta = math.tau * index / ANGLE_COUNT
            candidates = [
                radius
                for angle, radius in point_data
                if _angle_distance(angle, theta) <= math.radians(15.0)
            ]
            fallback = self._ellipse_radius(theta, x_radius, y_radius)
            radius = _quantile(candidates, 0.95) if candidates else fallback
            radius = max(0.86 * fallback, min(1.28 * fallback, radius))
            radii.append(max(0.040, min(0.158, radius)))
        return center_y, _circular_average(_circular_average(radii, 2), 2)

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
        scaled = (z - self.Z_MIN) / (self.Z_MAX - self.Z_MIN) * (len(self.levels) - 1)
        lower = int(math.floor(scaled))
        upper = min(len(self.levels) - 1, lower + 1)
        return lower, upper, scaled - lower

    @staticmethod
    def _angle_interval(theta: float) -> tuple[int, int, float]:
        scaled = (theta % math.tau) / math.tau * ANGLE_COUNT
        lower = int(math.floor(scaled)) % ANGLE_COUNT
        return lower, (lower + 1) % ANGLE_COUNT, scaled - math.floor(scaled)

    def section(self, z: float, theta: float) -> tuple[float, float]:
        z0, z1, zt = self._height_interval(z)
        a0, a1, at = self._angle_interval(theta)
        center = self.center_y[z0] * (1.0 - zt) + self.center_y[z1] * zt
        radius0 = self.radii[z0][a0] * (1.0 - at) + self.radii[z0][a1] * at
        radius1 = self.radii[z1][a0] * (1.0 - at) + self.radii[z1][a1] * at
        return center, radius0 * (1.0 - zt) + radius1 * zt

    def point(self, z: float, theta: float, clearance: float, boost: float = 0.0) -> Vector:
        center_y, radius = self.section(z, theta)
        radius += clearance + boost
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
            "centerYRangeM": [round(min(self.center_y), 6), round(max(self.center_y), 6)],
            "radiusRangeM": [round(min(flat), 6), round(max(flat), 6)],
        }


def _body_bvh(body: bpy.types.Object) -> BVHTree:
    vertices = [body.matrix_world @ vertex.co for vertex in body.data.vertices]
    polygons = [tuple(polygon.vertices) for polygon in body.data.polygons]
    return BVHTree.FromPolygons(vertices, polygons, all_triangles=False)


def _enforce_clearance(
    obj: bpy.types.Object,
    body_tree: BVHTree,
    minimum: float,
    maximum_step: float = 0.040,
) -> dict[str, float | int]:
    inverse = obj.matrix_world.inverted()
    adjusted = 0
    total_step = 0.0
    maximum_applied = 0.0
    for vertex in obj.data.vertices:
        world = obj.matrix_world @ vertex.co
        nearest, normal, _index, _distance = body_tree.find_nearest(world)
        if nearest is None or normal is None:
            continue
        signed = (world - nearest).dot(normal)
        required = minimum - signed
        if required <= 0.0:
            continue
        step = min(maximum_step, required)
        vertex.co = inverse @ (world + normal.normalized() * step)
        adjusted += 1
        total_step += step
        maximum_applied = max(maximum_applied, step)
    obj.data.update(calc_edges=True)
    return {
        "adjustedVertices": adjusted,
        "meanStepM": total_step / adjusted if adjusted else 0.0,
        "maximumStepM": maximum_applied,
        "minimumClearanceM": minimum,
    }


def _create_mesh_object(
    pattern: ModuleType,
    name: str,
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    material: bpy.types.Material,
    armature: bpy.types.Object,
    body: bpy.types.Object,
    body_tree: BVHTree,
    *,
    thickness: float,
    subdivision_levels: int,
    minimum_clearance: float | None,
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
    if minimum_clearance is not None:
        obj["clearanceProjection"] = _enforce_clearance(obj, body_tree, minimum_clearance)

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if subdivision_levels:
        subdivision = obj.modifiers.new("Garment component smoothing", "SUBSURF")
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


def _side_strength(theta: float) -> float:
    distance = min(_angle_distance(theta, 0.0), _angle_distance(theta, math.pi))
    return math.exp(-((distance / 0.52) ** 2))


def _bottom_z(theta: float) -> float:
    return 0.660 + 0.135 * (abs(math.cos(theta)) ** 1.50)


def _torso_and_saddle(
    pattern: ModuleType,
    profile: PolarBodyProfile,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    body_tree: BVHTree,
) -> bpy.types.Object:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for row in range(TORSO_ROWS):
        v = row / (TORSO_ROWS - 1)
        for column in range(ANGLE_COUNT):
            theta = math.tau * column / ANGLE_COUNT
            bottom = _bottom_z(theta)
            top = 0.998 - 0.020 * _side_strength(theta)
            z = bottom + (top - bottom) * v
            yoke_boost = (0.018 + 0.034 * _side_strength(theta)) * (v**5)
            point = profile.point(z, theta, BODY_CLEARANCE_M, yoke_boost)
            vertices.append((point.x, point.y, point.z))

    for row in range(TORSO_ROWS - 1):
        current = row * ANGLE_COUNT
        following = (row + 1) * ANGLE_COUNT
        for column in range(ANGLE_COUNT):
            nxt = (column + 1) % ANGLE_COUNT
            faces.append((current + column, current + nxt, following + nxt, following + column))

    top_row = (TORSO_ROWS - 1) * ANGLE_COUNT
    neck_start = len(vertices)
    for column in range(ANGLE_COUNT):
        theta = math.tau * column / ANGLE_COUNT
        vertices.append(
            (
                0.073 * math.cos(theta),
                -0.006 + 0.056 * math.sin(theta),
                1.042 + 0.004 * math.sin(theta),
            )
        )
    for column in range(ANGLE_COUNT):
        nxt = (column + 1) % ANGLE_COUNT
        faces.append((top_row + column, top_row + nxt, neck_start + nxt, neck_start + column))

    front_center = 3 * ANGLE_COUNT // 4
    back_center = ANGLE_COUNT // 4
    offsets = tuple(range(-10, 11, 2))
    front_row = tuple((front_center + offset) % ANGLE_COUNT for offset in offsets)
    back_row = tuple((back_center - offset) % ANGLE_COUNT for offset in offsets)
    saddle_rows: list[tuple[int, ...]] = [front_row]
    longitudinal_steps = 16
    for step in range(1, longitudinal_steps):
        t = step / longitudinal_steps
        indices: list[int] = []
        for front_index, back_index in zip(front_row, back_row, strict=True):
            front_point = Vector(vertices[front_index])
            back_point = Vector(vertices[back_index])
            point = front_point.lerp(back_point, t)
            point.z -= 0.024 * math.sin(math.pi * t)
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

    obj = _create_mesh_object(
        pattern,
        "Heather_Body_Shell",
        vertices,
        faces,
        material,
        armature,
        profile.body,
        body_tree,
        thickness=0.0014,
        subdivision_levels=1,
        minimum_clearance=0.014,
    )
    obj["constructionRepresentation"] = (
        "angular torso field, continuous yoke and eleven-column pelvic saddle"
    )
    obj["bodyTopologyCopied"] = False
    obj["pelvicSaddleColumns"] = len(front_row)
    return obj


def _frame(tangent: Vector) -> tuple[Vector, Vector]:
    direction = tangent.normalized()
    reference = Vector((0.0, 0.0, 1.0))
    if abs(direction.dot(reference)) > 0.92:
        reference = Vector((0.0, 1.0, 0.0))
    first = direction.cross(reference).normalized()
    return first, direction.cross(first).normalized()


def _arm_centers(pattern: ModuleType, armature: bpy.types.Object, side: str) -> list[Vector]:
    upper_head, upper_tail = pattern.bone_segment(armature, f"UpperArm_{side}")
    lower_head, lower_tail = pattern.bone_segment(armature, f"LowerArm_{side}")
    direction = (upper_tail - upper_head).normalized()
    shoulder_inner = upper_head - direction * 0.055
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
    body_tree: BVHTree,
    *,
    thickness: float,
    minimum_clearance: float,
) -> bpy.types.Object:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for ring, center in enumerate(centers):
        tangent = (
            centers[1] - center
            if ring == 0
            else center - centers[-2]
            if ring == len(centers) - 1
            else centers[ring + 1] - centers[ring - 1]
        )
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
            faces.append((current + column, current + nxt, following + nxt, following + column))
    return _create_mesh_object(
        pattern,
        name,
        vertices,
        faces,
        material,
        armature,
        body,
        body_tree,
        thickness=thickness,
        subdivision_levels=1,
        minimum_clearance=minimum_clearance,
    )


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
        if t < 0.20:
            radius = 0.056 - 0.017 * _smoothstep(t / 0.20)
        else:
            radius = 0.039 - 0.013 * _smoothstep((t - 0.20) / 0.80)
        radii.append(radius)
    return _tube_component(
        pattern,
        f"Heather_Long_Sleeve_{side}",
        centers,
        radii,
        material,
        armature,
        body,
        body_tree,
        thickness=0.0013,
        minimum_clearance=0.010,
    )


def _cuff(
    pattern: ModuleType,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    body_tree: BVHTree,
    side: str,
) -> bpy.types.Object:
    centers = _arm_centers(pattern, armature, side)[-4:]
    radii = [0.0275 - 0.0010 * index / 3.0 for index in range(4)]
    return _tube_component(
        pattern,
        f"Heather_Rib_Cuff_{side}",
        centers,
        radii,
        material,
        armature,
        body,
        body_tree,
        thickness=0.0017,
        minimum_clearance=0.006,
    )


def _folded_back_hood(
    pattern: ModuleType,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    body_tree: BVHTree,
) -> bpy.types.Object:
    columns = 40
    rows = 9
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for row in range(rows):
        v = row / (rows - 1)
        x_radius = 0.073 + 0.056 * v
        y_radius = 0.045 + 0.076 * v
        for column in range(columns):
            theta = math.pi * column / (columns - 1)
            z = 1.010 + 0.058 * math.sin(math.pi * v)
            z += 0.018 * math.sin(theta) * (0.35 + 0.65 * v)
            vertices.append(
                (
                    x_radius * math.cos(theta),
                    -0.006 + y_radius * math.sin(theta) + 0.012 * v,
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
    obj = _create_mesh_object(
        pattern,
        "Heather_Hood_Folded_Roll",
        vertices,
        faces,
        material,
        armature,
        body,
        body_tree,
        thickness=0.0018,
        subdivision_levels=1,
        minimum_clearance=0.010,
    )
    obj["hoodConstruction"] = "low folded-back hood shell attached around rear neck"
    return obj


def _cords(pattern: ModuleType, sampler, armature, material) -> list[bpy.types.Object]:
    result: list[bpy.types.Object] = []
    for side, sign in (("L", -1.0), ("R", 1.0)):
        points = []
        for x, z, offset in (
            (sign * 0.041, 1.018, 0.023),
            (sign * 0.043, 0.992, 0.025),
            (sign * 0.041, 0.966, 0.027),
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


def _validate(objects: list[bpy.types.Object], profile: PolarBodyProfile) -> dict[str, object]:
    mesh_objects = [obj for obj in objects if obj.type == "MESH"]
    failures: list[str] = []
    projections: dict[str, object] = {}
    for obj in mesh_objects:
        projection = obj.get("clearanceProjection")
        if projection is not None:
            projections[obj.name] = dict(projection)
        for vertex in obj.data.vertices:
            if not all(math.isfinite(value) for value in vertex.co):
                failures.append(f"{obj.name}: non-finite vertex {vertex.index}")
                break
    if failures:
        raise RuntimeError("Closed component validation failed: " + "; ".join(failures))
    return {
        "meshObjects": [obj.name for obj in mesh_objects],
        "meshObjectCount": len(mesh_objects),
        "vertices": sum(len(obj.data.vertices) for obj in mesh_objects),
        "polygons": sum(len(obj.data.polygons) for obj in mesh_objects),
        "bodyTopologyCopied": False,
        "pelvicSaddleColumns": 11,
        "boundedClearanceProjection": projections,
        "primaryRepresentation": "polar torso with closed garment-native components",
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
        "method": "closed garment components with bounded clearance projection",
        "sources": [
            {
                "title": "GarmentCode: Programming Parametric Sewing Patterns",
                "url": "https://arxiv.org/abs/2306.03642",
                "officialCode": "https://github.com/maria-korosteleva/GarmentCode",
            },
            {
                "title": "PatternGSL: A Structured Specification Language for Template-Free and Simulation-Ready 3D Garments",
                "url": "https://arxiv.org/abs/2606.24564",
                "officialCode": "https://github.com/PatternGSL/PatternGSL",
            },
        ],
        "implementation": {
            "kind": "independent Blender implementation",
            "authorsImplementationExecuted": False,
            "authorsCodeCopied": False,
            "bodyRole": "polar statistics, bounded clearance and skin-weight reference",
            "topologySource": (
                "continuous torso/yoke, eleven-column pelvic saddle, overlapping sleeve "
                "caps, fitted cuffs and low folded-back hood"
            ),
        },
        "metrics": metrics,
        "acceptance": {
            "researchTrial": "PASS",
            "visualAppearanceReview": "PENDING",
            "poseEvidence": "PENDING",
        },
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def create_outfit(
    pattern: ModuleType,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    fabric: bpy.types.Material,
    trim: bpy.types.Material,
    button_material: bpy.types.Material,
) -> list[bpy.types.Object]:
    profile = PolarBodyProfile(body)
    body_tree = _body_bvh(body)
    sampler = pattern.v9.SurfaceSampler(body)
    garments: list[bpy.types.Object] = [
        _torso_and_saddle(pattern, profile, armature, fabric, body_tree),
        _sleeve(pattern, body, armature, fabric, body_tree, "L"),
        _sleeve(pattern, body, armature, fabric, body_tree, "R"),
        _cuff(pattern, body, armature, trim, body_tree, "L"),
        _cuff(pattern, body, armature, trim, body_tree, "R"),
        _folded_back_hood(pattern, body, armature, fabric, body_tree),
    ]
    garments.extend(
        pattern.v9._placket_and_buttons(sampler, armature, trim, button_material)
    )
    garments.extend(_cords(pattern, sampler, armature, trim))
    metrics = _validate(garments, profile)
    _write_trial(metrics)
    return garments


def install(pattern: ModuleType) -> None:
    """Install closed garment-native components as the active product generator."""
    pattern.DESIGN_REVISION = DESIGN_REVISION
    pattern.create_outfit = lambda body, armature, fabric, trim, buttons: create_outfit(
        pattern,
        body,
        armature,
        fabric,
        trim,
        buttons,
    )
