#!/usr/bin/env python3
"""Continuous sampled-pattern v9 for the Siroino heather hooded bodysuit."""

from __future__ import annotations

import math
from dataclasses import dataclass

import bpy
from mathutils import Vector

import siroino_heather_hooded_geometry as legacy
import siroino_strappy_knit_build as base

bone_segment = legacy.bone_segment
clean_meshes = legacy.clean_meshes


@dataclass(frozen=True)
class SurfaceSample:
    y: float
    normal: Vector


class SurfaceSampler:
    """Interpolate body Y and normal at exact X/Z coordinates."""

    def __init__(self, body: bpy.types.Object) -> None:
        self.body = body
        normal_matrix = body.matrix_world.to_3x3()
        self.samples = [
            (
                body.matrix_world @ vertex.co,
                (normal_matrix @ vertex.normal).normalized(),
            )
            for vertex in body.data.vertices
        ]
        self.z_bins: dict[int, list[tuple[Vector, Vector]]] = {}
        for point, normal in self.samples:
            self.z_bins.setdefault(round(point.z * 100), []).append((point, normal))

    def sample(self, x: float, z: float, *, front: bool) -> SurfaceSample:
        candidates: list[tuple[Vector, Vector]] = []
        center_bin = round(z * 100)
        for delta in range(-5, 6):
            candidates.extend(self.z_bins.get(center_bin + delta, []))
        if not candidates:
            candidates = self.samples
        ranked = sorted(
            candidates,
            key=lambda item: (item[0].x - x) ** 2 + (item[0].z - z) ** 2,
        )[:24]
        side_ranked = sorted(ranked, key=lambda item: item[0].y)
        side = side_ranked[:12] if front else side_ranked[-12:]
        weights: list[float] = []
        for point, _normal in side:
            distance_squared = (point.x - x) ** 2 + (point.z - z) ** 2
            weights.append(1.0 / max(1e-7, distance_squared))
        total = sum(weights)
        y = sum(weight * item[0].y for weight, item in zip(weights, side)) / total
        normal = Vector((0.0, 0.0, 0.0))
        for weight, (_point, item_normal) in zip(weights, side):
            normal += item_normal * weight
        if normal.length_squared <= 1e-12:
            normal = Vector((0.0, -1.0 if front else 1.0, 0.0))
        else:
            normal.normalize()
        if front and normal.y > 0.0:
            normal = -normal
        if not front and normal.y < 0.0:
            normal = -normal
        return SurfaceSample(y=y, normal=normal)

    def point(self, x: float, z: float, *, front: bool, offset: float) -> Vector:
        sampled = self.sample(x, z, front=front)
        return Vector((x, sampled.y, z)) + sampled.normal * offset

    def side_y(self, x: float, z: float) -> float:
        return 0.5 * (
            self.sample(x, z, front=True).y + self.sample(x, z, front=False).y
        )


def _grid_object(
    name: str,
    vertices: list[tuple[float, float, float]],
    rows: int,
    columns: int,
    material: bpy.types.Material,
    armature: bpy.types.Object,
    body: bpy.types.Object,
    *,
    thickness: float,
    bevel: float,
    subdivision: int = 0,
) -> bpy.types.Object:
    stride = columns + 1
    faces = [
        (
            row * stride + column,
            row * stride + column + 1,
            (row + 1) * stride + column + 1,
            (row + 1) * stride + column,
        )
        for row in range(rows - 1)
        for column in range(columns)
    ]
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    uv = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            row, column = divmod(vertex_index, stride)
            uv.data[loop_index].uv = (
                column / max(1, columns),
                1.0 - row / max(1, rows - 1),
            )
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = armature
    armature_modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    armature_modifier.object = armature
    armature_modifier.use_deform_preserve_volume = True
    base.transfer_nearest_body_weights(obj, body)
    for polygon in mesh.polygons:
        polygon.use_smooth = True

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if subdivision:
        smooth = obj.modifiers.new("Pattern smoothing", "SUBSURF")
        smooth.subdivision_type = "CATMULL_CLARK"
        smooth.levels = subdivision
        smooth.render_levels = subdivision
        while obj.modifiers.find(smooth.name) > 0:
            bpy.ops.object.modifier_move_up(modifier=smooth.name)
        bpy.ops.object.modifier_apply(modifier=smooth.name)
    solidify = obj.modifiers.new("Outward fabric thickness", "SOLIDIFY")
    solidify.thickness = thickness
    solidify.offset = 1.0
    solidify.use_even_offset = True
    while obj.modifiers.find(solidify.name) > 0:
        bpy.ops.object.modifier_move_up(modifier=solidify.name)
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    edge_finish = obj.modifiers.new("Finished pattern edge", "BEVEL")
    edge_finish.width = bevel
    edge_finish.segments = 2
    while obj.modifiers.find(edge_finish.name) > 0:
        bpy.ops.object.modifier_move_up(modifier=edge_finish.name)
    bpy.ops.object.modifier_apply(modifier=edge_finish.name)
    obj.select_set(False)
    return obj


def _sampled_panel(
    name: str,
    sampler: SurfaceSampler,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    rows: list[tuple[float, float, float]],
    *,
    front: bool,
    columns: int,
    offset: float,
) -> bpy.types.Object:
    vertices: list[tuple[float, float, float]] = []
    for center_z, edge_z, half_width in rows:
        for column in range(columns + 1):
            s = -1.0 + 2.0 * column / columns
            x = half_width * s
            z = center_z + (edge_z - center_z) * abs(s) ** 1.7
            point = sampler.point(x, z, front=front, offset=offset)
            vertices.append((point.x, point.y, point.z))
    return _grid_object(
        name,
        vertices,
        len(rows),
        columns,
        material,
        armature,
        sampler.body,
        thickness=0.0012,
        bevel=0.0004,
    )


def _torso_panels(
    sampler: SurfaceSampler,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> list[bpy.types.Object]:
    rows = [
        (0.795, 0.795, 0.132),
        (0.835, 0.835, 0.145),
        (0.875, 0.875, 0.158),
        (0.915, 0.915, 0.173),
        (0.955, 0.958, 0.188),
        (0.992, 1.006, 0.202),
        (1.025, 1.047, 0.198),
    ]
    return [
        _sampled_panel(
            "Heather_Front_Upper_Panel",
            sampler,
            armature,
            material,
            rows,
            front=True,
            columns=40,
            offset=0.030,
        ),
        _sampled_panel(
            "Heather_Back_Upper_Panel",
            sampler,
            armature,
            material,
            rows,
            front=False,
            columns=40,
            offset=0.030,
        ),
    ]


def _highcut_panels(
    sampler: SurfaceSampler,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> list[bpy.types.Object]:
    rows = [
        (0.660, 0.660, 0.018),
        (0.690, 0.690, 0.026),
        (0.725, 0.725, 0.040),
        (0.765, 0.765, 0.062),
        (0.805, 0.805, 0.095),
        (0.845, 0.845, 0.135),
    ]
    return [
        _sampled_panel(
            "Heather_Highcut_Front_Panel",
            sampler,
            armature,
            material,
            rows,
            front=True,
            columns=34,
            offset=0.026,
        ),
        _sampled_panel(
            "Heather_Highcut_Back_Panel",
            sampler,
            armature,
            material,
            rows,
            front=False,
            columns=34,
            offset=0.030,
        ),
    ]


def _segment_distance(point: Vector, start: Vector, end: Vector) -> tuple[float, float]:
    vector = end - start
    length_squared = vector.length_squared
    if length_squared <= 1e-12:
        return (point - start).length, 0.0
    t = max(0.0, min(1.0, (point - start).dot(vector) / length_squared))
    return (point - (start + vector * t)).length, t


def _copy_sleeve_shell(
    name: str,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    side: str,
) -> bpy.types.Object:
    upper_start, upper_end = bone_segment(armature, f"UpperArm_{side}")
    lower_start, lower_end = bone_segment(armature, f"LowerArm_{side}")
    selected = []
    for polygon in body.data.polygons:
        center = body.matrix_world @ polygon.center
        upper_distance, upper_t = _segment_distance(center, upper_start, upper_end)
        lower_distance, lower_t = _segment_distance(center, lower_start, lower_end)
        if (upper_distance <= 0.060 and 0.075 <= upper_t <= 1.0) or (
            lower_distance <= 0.053 and lower_t <= 0.84
        ):
            selected.append(polygon)
    if not selected:
        raise RuntimeError(f"No body faces selected for {name}")

    normal_matrix = body.matrix_world.to_3x3()
    used: dict[int, int] = {}
    source_indices: list[int] = []
    vertices: list[tuple[float, float, float]] = []
    faces: list[list[int]] = []
    face_uvs: list[list[tuple[float, float]]] = []
    source_uv = body.data.uv_layers.active
    for polygon in selected:
        face: list[int] = []
        uvs: list[tuple[float, float]] = []
        for loop_index in polygon.loop_indices:
            source_index = body.data.loops[loop_index].vertex_index
            if source_index not in used:
                used[source_index] = len(vertices)
                source_indices.append(source_index)
                source_vertex = body.data.vertices[source_index]
                point = body.matrix_world @ source_vertex.co
                normal = (normal_matrix @ source_vertex.normal).normalized()
                point += normal * 0.028
                vertices.append((point.x, point.y, point.z))
            face.append(used[source_index])
            if source_uv is not None:
                uv = source_uv.data[loop_index].uv
                uvs.append((float(uv.x), float(uv.y)))
            else:
                uvs.append((0.0, 0.0))
        faces.append(face)
        face_uvs.append(uvs)

    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for polygon, polygon_uvs in zip(mesh.polygons, face_uvs):
        for loop_index, uv in zip(polygon.loop_indices, polygon_uvs):
            uv_layer.data[loop_index].uv = uv
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = armature
    armature_modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    armature_modifier.object = armature
    armature_modifier.use_deform_preserve_volume = True

    groups = {
        group.name: obj.vertex_groups.new(name=group.name)
        for group in body.vertex_groups
    }
    fallback = groups.get("Hips") or next(iter(groups.values()))
    for new_index, source_index in enumerate(source_indices):
        assignments = body.data.vertices[source_index].groups
        total = sum(item.weight for item in assignments if item.weight > 1e-8)
        if total <= 1e-8:
            fallback.add([new_index], 1.0, "REPLACE")
        else:
            for item in assignments:
                if item.weight > 1e-8:
                    groups[body.vertex_groups[item.group].name].add(
                        [new_index],
                        float(item.weight) / total,
                        "REPLACE",
                    )
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    solidify = obj.modifiers.new("Sleeve fabric thickness", "SOLIDIFY")
    solidify.thickness = 0.0013
    solidify.offset = 1.0
    solidify.use_even_offset = True
    while obj.modifiers.find(solidify.name) > 0:
        bpy.ops.object.modifier_move_up(modifier=solidify.name)
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    edge_finish = obj.modifiers.new("Sleeve edge finish", "BEVEL")
    edge_finish.width = 0.00035
    edge_finish.segments = 2
    while obj.modifiers.find(edge_finish.name) > 0:
        bpy.ops.object.modifier_move_up(modifier=edge_finish.name)
    bpy.ops.object.modifier_apply(modifier=edge_finish.name)
    obj.select_set(False)
    return obj


def _cuff(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    side: str,
) -> bpy.types.Object:
    lower_start, lower_end = bone_segment(armature, f"LowerArm_{side}")
    hand_start, hand_end = bone_segment(armature, f"Hand_{side}")
    lower = lower_end - lower_start
    hand = hand_end - hand_start
    cuff = legacy.weighted_tube(
        f"Heather_Rib_Cuff_{side}",
        [
            lower_start + lower * 0.78,
            lower_start + lower * 0.90,
            lower_end,
            hand_start + hand * 0.035,
        ],
        [0.0290, 0.0280, 0.0270, 0.0265],
        [
            {f"LowerArm_{side}": 1.0},
            {f"LowerArm_{side}": 1.0},
            {f"LowerArm_{side}": 0.75, f"Hand_{side}": 0.25},
            {f"LowerArm_{side}": 0.25, f"Hand_{side}": 0.75},
        ],
        material,
        armature,
        segments=40,
        thickness=0.0016,
    )
    base.transfer_nearest_body_weights(cuff, body)
    return cuff


def _sleeves_and_cuffs(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    fabric: bpy.types.Material,
    trim: bpy.types.Material,
) -> list[bpy.types.Object]:
    result: list[bpy.types.Object] = []
    for side in ("L", "R"):
        result.append(
            _copy_sleeve_shell(
                f"Heather_Long_Sleeve_{side}",
                body,
                armature,
                fabric,
                side,
            )
        )
        result.append(_cuff(body, armature, trim, side))
    return result


def _hood_half(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    side: str,
) -> bpy.types.Object:
    profiles = [
        (1.040, 0.036, 0.120, 0.030),
        (1.012, 0.050, 0.125, 0.040),
        (0.980, 0.060, 0.132, 0.046),
        (0.946, 0.060, 0.134, 0.046),
        (0.916, 0.050, 0.130, 0.038),
        (0.892, 0.032, 0.122, 0.025),
    ]
    columns = 18
    if side == "L":
        start_angle, end_angle = math.pi / 2.0, math.pi
    else:
        start_angle, end_angle = 0.0, math.pi / 2.0
    vertices: list[tuple[float, float, float]] = []
    for z, radius_x, center_y, radius_y in profiles:
        for column in range(columns + 1):
            u = column / columns
            angle = start_angle + (end_angle - start_angle) * u
            x = radius_x * math.cos(angle)
            y = center_y + radius_y * math.sin(angle)
            vertices.append((x, y, z - 0.002 * math.sin(math.pi * u)))
    return _grid_object(
        f"Heather_Hood_Outer_{side}",
        vertices,
        len(profiles),
        columns,
        material,
        armature,
        body,
        thickness=0.0018,
        bevel=0.00045,
        subdivision=1,
    )


def _neck_band(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    points = [
        (
            0.092 * math.cos(math.tau * index / 80),
            0.018 + 0.084 * math.sin(math.tau * index / 80),
            1.040,
        )
        for index in range(80)
    ]
    band = base.curve_tube(
        "Heather_Hood_Neck_Band",
        points,
        0.0025,
        material,
        armature,
        "Chest",
        cyclic=True,
        resolution=3,
    )
    base.transfer_nearest_body_weights(band, body)
    return band


def _placket_and_buttons(
    sampler: SurfaceSampler,
    armature: bpy.types.Object,
    trim: bpy.types.Material,
    buttons: bpy.types.Material,
) -> list[bpy.types.Object]:
    y = sampler.sample(0.0, 0.990, front=True).y - 0.034
    placket = legacy.rounded_box(
        "Heather_Henley_Placket",
        (0.0, y, 0.990),
        (0.014, 0.0028, 0.042),
        trim,
        armature,
        "Chest",
        bevel=0.0014,
    )
    result = [placket]
    for index, z in enumerate((1.010, 0.988, 0.966), start=1):
        bpy.ops.mesh.primitive_uv_sphere_add(
            segments=24,
            ring_count=12,
            location=(0.0, y - 0.006, z),
            scale=(0.0048, 0.0023, 0.0048),
        )
        button = bpy.context.active_object
        button.name = f"Heather_Henley_Button_{index:02d}"
        button.data.materials.append(buttons)
        base.rigid_mesh_weight(button, armature, "Chest")
        for polygon in button.data.polygons:
            polygon.use_smooth = True
        result.append(button)
    return result


def _cords_ties_seams(
    sampler: SurfaceSampler,
    armature: bpy.types.Object,
    trim: bpy.types.Material,
) -> list[bpy.types.Object]:
    result: list[bpy.types.Object] = []
    front_y = sampler.sample(0.038, 1.025, front=True).y - 0.035
    for side, sign in (("L", -1.0), ("R", 1.0)):
        cord = base.curve_tube(
            f"Heather_Hood_Drawcord_{side}",
            [
                (sign * 0.040, front_y, 1.030),
                (sign * 0.044, front_y - 0.004, 1.005),
                (sign * 0.046, front_y - 0.006, 0.980),
                (sign * 0.041, front_y - 0.002, 0.958),
            ],
            0.00135,
            trim,
            armature,
            "Chest",
            resolution=3,
        )
        base.transfer_nearest_body_weights(cord, sampler.body)
        result.append(cord)

        x = sign * 0.150
        z = 0.805
        y = sampler.side_y(x, z)
        tie = base.curve_tube(
            f"Heather_Side_Tie_{side}",
            [
                (x, y, z),
                (sign * 0.168, y - 0.002, z + 0.002),
                (sign * 0.184, y + 0.004, z - 0.012),
                (sign * 0.194, y + 0.012, z - 0.030),
            ],
            0.0015,
            trim,
            armature,
            "Hips",
            resolution=3,
        )
        base.transfer_nearest_body_weights(tie, sampler.body)
        result.append(tie)

    front_points = [
        (0.0, sampler.sample(0.0, z, front=True).y - 0.031, z)
        for z in (0.670, 0.720, 0.775, 0.835, 0.895, 0.955)
    ]
    back_points = [
        (0.0, sampler.sample(0.0, z, front=False).y + 0.033, z)
        for z in (0.670, 0.720, 0.775, 0.835, 0.895, 0.955)
    ]
    for name, points in (
        ("Heather_Center_Front_Seam", front_points),
        ("Heather_Center_Back_Seam", back_points),
        (
            "Heather_Hood_Center_Seam",
            [
                (0.0, 0.150, 1.040),
                (0.0, 0.165, 1.012),
                (0.0, 0.178, 0.980),
                (0.0, 0.180, 0.946),
                (0.0, 0.168, 0.916),
                (0.0, 0.147, 0.892),
            ],
        ),
    ):
        seam = base.curve_tube(
            name,
            points,
            0.00055,
            trim,
            armature,
            "Chest" if "Hood" in name else "Spine",
            resolution=2,
        )
        base.transfer_nearest_body_weights(seam, sampler.body)
        result.append(seam)
    return result


def create_outfit(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    fabric: bpy.types.Material,
    trim: bpy.types.Material,
    button_material: bpy.types.Material,
) -> list[bpy.types.Object]:
    sampler = SurfaceSampler(body)
    garments: list[bpy.types.Object] = []
    garments.extend(_torso_panels(sampler, armature, fabric))
    garments.extend(_highcut_panels(sampler, armature, fabric))
    garments.extend(_sleeves_and_cuffs(body, armature, fabric, trim))
    garments.extend(
        [
            _hood_half(body, armature, fabric, "L"),
            _hood_half(body, armature, fabric, "R"),
            _neck_band(body, armature, fabric),
        ]
    )
    garments.extend(_placket_and_buttons(sampler, armature, trim, button_material))
    garments.extend(_cords_ties_seams(sampler, armature, trim))
    return garments
