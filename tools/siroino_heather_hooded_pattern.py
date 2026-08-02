#!/usr/bin/env python3
"""Smooth sampled-pattern v8 for the Siroino heather hooded bodysuit."""
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
    point: Vector
    normal: Vector


class SurfaceSampler:
    """Fast deterministic front/back sampling of the tracked Siroino body."""

    def __init__(self, body: bpy.types.Object) -> None:
        self.body = body
        normal_matrix = body.matrix_world.to_3x3()
        self.samples: list[tuple[Vector, Vector]] = [
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
        center_bin = round(z * 100)
        candidates: list[tuple[Vector, Vector]] = []
        for delta in range(-4, 5):
            candidates.extend(self.z_bins.get(center_bin + delta, []))
        close = [
            item
            for item in candidates
            if abs(item[0].x - x) <= 0.030 and abs(item[0].z - z) <= 0.045
        ]
        if not close:
            close = sorted(
                candidates or self.samples,
                key=lambda item: abs(item[0].x - x) * 1.8 + abs(item[0].z - z),
            )[:40]
        point, normal = (
            min(close, key=lambda item: item[0].y)
            if front
            else max(close, key=lambda item: item[0].y)
        )
        return SurfaceSample(point.copy(), normal.copy())

    def side_y(self, x: float, z: float) -> float:
        front = self.sample(x, z, front=True).point.y
        back = self.sample(x, z, front=False).point.y
        return 0.5 * (front + back)


def _uv_grid(mesh: bpy.types.Mesh, rows: int, columns: int) -> None:
    uv = mesh.uv_layers.new(name="UVMap")
    stride = columns + 1
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            row, column = divmod(vertex_index, stride)
            uv.data[loop_index].uv = (
                column / max(1, columns),
                1.0 - row / max(1, rows - 1),
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
    thickness: float = 0.0012,
    bevel: float = 0.0004,
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
    _uv_grid(mesh, rows, columns)
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
    if bevel:
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
    columns: int = 36,
    offset: float = 0.014,
) -> bpy.types.Object:
    """Create a smooth variable-width panel sampled directly from the body surface.

    Each row is ``(center_z, edge_z, half_width)``.  Curving the final row's
    center and edge heights produces a clean neckline without polygon stair-steps.
    """
    vertices: list[tuple[float, float, float]] = []
    for center_z, edge_z, half_width in rows:
        for column in range(columns + 1):
            s = -1.0 + 2.0 * column / columns
            x = half_width * s
            z = center_z + (edge_z - center_z) * (abs(s) ** 1.75)
            sample = sampler.sample(x, z, front=front)
            direction = sample.normal
            if front and direction.y > 0.0:
                direction = -direction
            if not front and direction.y < 0.0:
                direction = -direction
            point = sample.point + direction.normalized() * offset
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
        bevel=0.00035,
    )


def _torso_panels(
    sampler: SurfaceSampler,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> list[bpy.types.Object]:
    rows = [
        (0.785, 0.785, 0.135),
        (0.820, 0.820, 0.145),
        (0.855, 0.855, 0.155),
        (0.895, 0.895, 0.170),
        (0.935, 0.936, 0.185),
        (0.972, 0.982, 0.205),
        (1.000, 1.032, 0.215),
    ]
    return [
        _sampled_panel(
            "Heather_Front_Upper_Panel",
            sampler,
            armature,
            material,
            rows,
            front=True,
        ),
        _sampled_panel(
            "Heather_Back_Upper_Panel",
            sampler,
            armature,
            material,
            rows,
            front=False,
        ),
    ]


def _highcut_panels(
    sampler: SurfaceSampler,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> list[bpy.types.Object]:
    rows = [
        (0.615, 0.615, 0.025),
        (0.645, 0.645, 0.030),
        (0.680, 0.680, 0.042),
        (0.720, 0.720, 0.060),
        (0.760, 0.760, 0.082),
        (0.800, 0.800, 0.110),
        (0.840, 0.840, 0.138),
    ]
    return [
        _sampled_panel(
            "Heather_Highcut_Front_Panel",
            sampler,
            armature,
            material,
            rows,
            front=True,
            columns=32,
            offset=0.015,
        ),
        _sampled_panel(
            "Heather_Highcut_Back_Panel",
            sampler,
            armature,
            material,
            rows,
            front=False,
            columns=32,
            offset=0.015,
        ),
    ]


def _segment_distance(point: Vector, start: Vector, end: Vector) -> tuple[float, float]:
    vector = end - start
    length_squared = vector.length_squared
    if length_squared <= 1e-12:
        return (point - start).length, 0.0
    t = max(0.0, min(1.0, (point - start).dot(vector) / length_squared))
    closest = start + vector * t
    return (point - closest).length, t


def _arm_shell(
    name: str,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    side: str,
    *,
    cuff: bool,
) -> bpy.types.Object:
    upper_start, upper_end = bone_segment(armature, f"UpperArm_{side}")
    lower_start, lower_end = bone_segment(armature, f"LowerArm_{side}")
    selected: list[bpy.types.MeshPolygon] = []
    for polygon in body.data.polygons:
        center = body.matrix_world @ polygon.center
        upper_distance, upper_t = _segment_distance(center, upper_start, upper_end)
        lower_distance, lower_t = _segment_distance(center, lower_start, lower_end)
        if cuff:
            include = lower_distance <= 0.060 and lower_t >= 0.79
        else:
            include = (
                (upper_distance <= 0.072 and upper_t >= 0.015)
                or (lower_distance <= 0.060 and lower_t <= 0.86)
            )
        if include:
            selected.append(polygon)
    if not selected:
        raise RuntimeError(f"Arm shell selection produced no faces: {name}")

    used: dict[int, int] = {}
    source_indices: list[int] = []
    vertices: list[tuple[float, float, float]] = []
    faces: list[list[int]] = []
    source_uv = body.data.uv_layers.active
    face_uvs: list[list[tuple[float, float]]] = []
    for polygon in selected:
        face: list[int] = []
        uvs: list[tuple[float, float]] = []
        for loop_index in polygon.loop_indices:
            source_index = body.data.loops[loop_index].vertex_index
            if source_index not in used:
                used[source_index] = len(vertices)
                source_indices.append(source_index)
                coordinate = body.matrix_world @ body.data.vertices[source_index].co
                vertices.append((coordinate.x, coordinate.y, coordinate.z))
            face.append(used[source_index])
            if source_uv:
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
    for polygon, values in zip(mesh.polygons, face_uvs):
        for loop_index, value in zip(polygon.loop_indices, values):
            uv_layer.data[loop_index].uv = value
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
                if item.weight <= 1e-8:
                    continue
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
    smooth = obj.modifiers.new("Arm boundary smoothing", "SUBSURF")
    smooth.subdivision_type = "CATMULL_CLARK"
    smooth.levels = 1
    smooth.render_levels = 1
    while obj.modifiers.find(smooth.name) > 0:
        bpy.ops.object.modifier_move_up(modifier=smooth.name)
    bpy.ops.object.modifier_apply(modifier=smooth.name)
    shrink = obj.modifiers.new("Siroino fitted clearance", "SHRINKWRAP")
    shrink.target = body
    shrink.wrap_method = "NEAREST_SURFACEPOINT"
    shrink.wrap_mode = "OUTSIDE_SURFACE"
    shrink.offset = 0.014 if not cuff else 0.016
    while obj.modifiers.find(shrink.name) > 0:
        bpy.ops.object.modifier_move_up(modifier=shrink.name)
    bpy.ops.object.modifier_apply(modifier=shrink.name)
    solidify = obj.modifiers.new("Sleeve fabric thickness", "SOLIDIFY")
    solidify.thickness = 0.0013 if not cuff else 0.0017
    solidify.offset = 1.0
    solidify.use_even_offset = True
    while obj.modifiers.find(solidify.name) > 0:
        bpy.ops.object.modifier_move_up(modifier=solidify.name)
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    edge_finish = obj.modifiers.new("Sleeve edge finish", "BEVEL")
    edge_finish.width = 0.0004
    edge_finish.segments = 2
    while obj.modifiers.find(edge_finish.name) > 0:
        bpy.ops.object.modifier_move_up(modifier=edge_finish.name)
    bpy.ops.object.modifier_apply(modifier=edge_finish.name)
    obj.select_set(False)
    return obj


def _sleeves_and_cuffs(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    fabric: bpy.types.Material,
    trim: bpy.types.Material,
) -> list[bpy.types.Object]:
    garments: list[bpy.types.Object] = []
    for side in ("L", "R"):
        garments.append(
            _arm_shell(
                f"Heather_Long_Sleeve_{side}",
                body,
                armature,
                fabric,
                side,
                cuff=False,
            )
        )
        garments.append(
            _arm_shell(
                f"Heather_Rib_Cuff_{side}",
                body,
                armature,
                trim,
                side,
                cuff=True,
            )
        )
    return garments


def _hood_half(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    side: str,
) -> bpy.types.Object:
    profiles = [
        (1.025, 0.068, -0.026, 0.050),
        (1.000, 0.095, -0.002, 0.105),
        (0.965, 0.108, 0.008, 0.132),
        (0.928, 0.102, 0.014, 0.132),
        (0.895, 0.075, 0.018, 0.108),
        (0.875, 0.030, 0.020, 0.070),
    ]
    columns = 20
    vertices: list[tuple[float, float, float]] = []
    if side == "L":
        start_angle, end_angle = math.pi / 2.0, math.pi
    else:
        start_angle, end_angle = 0.0, math.pi / 2.0
    for z, radius_x, center_y, radius_y in profiles:
        for column in range(columns + 1):
            u = column / columns
            angle = start_angle + (end_angle - start_angle) * u
            fold = 0.006 * math.sin(math.pi * u)
            x = radius_x * math.cos(angle)
            y = center_y + radius_y * math.sin(angle) + fold
            vertices.append((x, y, z - 0.003 * math.sin(math.pi * u)))
    return _grid_object(
        f"Heather_Hood_Outer_{side}",
        vertices,
        len(profiles),
        columns,
        material,
        armature,
        body,
        thickness=0.0020,
        bevel=0.0005,
        subdivision=1,
    )


def _neck_band(
    sampler: SurfaceSampler,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    points = [
        (
            0.080 * math.cos(math.tau * index / 80),
            0.002 + 0.066 * math.sin(math.tau * index / 80),
            1.018 - 0.004 * max(0.0, -math.sin(math.tau * index / 80)),
        )
        for index in range(80)
    ]
    band = base.curve_tube(
        "Heather_Hood_Neck_Band",
        points,
        0.0027,
        material,
        armature,
        "Chest",
        cyclic=True,
        resolution=3,
    )
    base.transfer_nearest_body_weights(band, sampler.body)
    return band


def _placket_and_buttons(
    sampler: SurfaceSampler,
    armature: bpy.types.Object,
    trim: bpy.types.Material,
    buttons: bpy.types.Material,
) -> list[bpy.types.Object]:
    surface = sampler.sample(0.0, 0.965, front=True)
    y = surface.point.y - 0.018
    placket = legacy.rounded_box(
        "Heather_Henley_Placket",
        (0.0, y, 0.965),
        (0.014, 0.0028, 0.047),
        trim,
        armature,
        "Chest",
        bevel=0.0014,
    )
    result = [placket]
    for index, z in enumerate((0.990, 0.963, 0.936), start=1):
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


def _cords_and_ties(
    sampler: SurfaceSampler,
    armature: bpy.types.Object,
    trim: bpy.types.Material,
) -> list[bpy.types.Object]:
    front_y = sampler.sample(0.035, 1.000, front=True).point.y - 0.020
    result: list[bpy.types.Object] = []
    for side, sign in (("L", -1.0), ("R", 1.0)):
        cord = base.curve_tube(
            f"Heather_Hood_Drawcord_{side}",
            [
                (sign * 0.040, front_y, 1.008),
                (sign * 0.044, front_y - 0.005, 0.982),
                (sign * 0.046, front_y - 0.007, 0.954),
                (sign * 0.041, front_y - 0.003, 0.932),
            ],
            0.00135,
            trim,
            armature,
            "Chest",
            resolution=3,
        )
        base.transfer_nearest_body_weights(cord, sampler.body)
        result.append(cord)

        x = sign * 0.140
        z = 0.800
        y = sampler.side_y(x, z)
        tie = base.curve_tube(
            f"Heather_Side_Tie_{side}",
            [
                (x, y, z),
                (sign * 0.158, y - 0.002, z + 0.003),
                (sign * 0.177, y + 0.003, z - 0.012),
                (sign * 0.188, y + 0.010, z - 0.032),
            ],
            0.0015,
            trim,
            armature,
            "Hips",
            resolution=3,
        )
        base.transfer_nearest_body_weights(tie, sampler.body)
        result.append(tie)
    return result


def _seams(
    sampler: SurfaceSampler,
    armature: bpy.types.Object,
    trim: bpy.types.Material,
) -> list[bpy.types.Object]:
    front_points = [
        (
            0.0,
            sampler.sample(0.0, z, front=True).point.y - 0.017,
            z,
        )
        for z in (0.625, 0.675, 0.730, 0.790, 0.850, 0.915)
    ]
    back_points = [
        (
            0.0,
            sampler.sample(0.0, z, front=False).point.y + 0.017,
            z,
        )
        for z in (0.625, 0.675, 0.730, 0.790, 0.850, 0.915)
    ]
    front = base.curve_tube(
        "Heather_Center_Front_Seam",
        front_points,
        0.0005,
        trim,
        armature,
        "Spine",
        resolution=2,
    )
    back = base.curve_tube(
        "Heather_Center_Back_Seam",
        back_points,
        0.0005,
        trim,
        armature,
        "Spine",
        resolution=2,
    )
    hood = base.curve_tube(
        "Heather_Hood_Center_Seam",
        [
            (0.0, 0.052, 1.025),
            (0.0, 0.103, 1.000),
            (0.0, 0.140, 0.965),
            (0.0, 0.146, 0.928),
            (0.0, 0.126, 0.895),
            (0.0, 0.090, 0.875),
        ],
        0.00065,
        trim,
        armature,
        "Chest",
        resolution=2,
    )
    for obj in (front, back, hood):
        base.transfer_nearest_body_weights(obj, sampler.body)
    return [front, back, hood]


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
            _neck_band(sampler, armature, fabric),
        ]
    )
    garments.extend(_placket_and_buttons(sampler, armature, trim, button_material))
    garments.extend(_cords_and_ties(sampler, armature, trim))
    garments.extend(_seams(sampler, armature, trim))
    return garments
