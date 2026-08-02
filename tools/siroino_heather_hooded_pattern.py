#!/usr/bin/env python3
"""Body-derived v7 pattern for the Siroino heather hooded bodysuit."""
from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable

import bmesh
import bpy
from mathutils import Vector

import siroino_heather_hooded_geometry as legacy
import siroino_strappy_knit_build as base

bone_segment = legacy.bone_segment
clean_meshes = legacy.clean_meshes


def _world_vertex(body: bpy.types.Object, index: int) -> Vector:
    return body.matrix_world @ body.data.vertices[index].co


def _world_normal(body: bpy.types.Object, index: int) -> Vector:
    normal = body.matrix_world.to_3x3() @ body.data.vertices[index].normal
    return normal.normalized()


def _group_index(body: bpy.types.Object, name: str) -> int | None:
    group = body.vertex_groups.get(name)
    return None if group is None else group.index


def _vertex_weight(body: bpy.types.Object, vertex_index: int, group_index: int | None) -> float:
    if group_index is None:
        return 0.0
    for assignment in body.data.vertices[vertex_index].groups:
        if assignment.group == group_index:
            return float(assignment.weight)
    return 0.0


def _polygon_average_weight(
    body: bpy.types.Object,
    polygon: bpy.types.MeshPolygon,
    group_indices: tuple[int | None, ...],
) -> float:
    values = []
    for vertex_index in polygon.vertices:
        values.append(
            sum(_vertex_weight(body, vertex_index, index) for index in group_indices)
        )
    return sum(values) / max(1, len(values))


def _copy_shell(
    name: str,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    predicate: Callable[[bpy.types.MeshPolygon, Vector], bool],
    *,
    offset: float,
    thickness: float = 0.0012,
    bevel: float = 0.00035,
) -> bpy.types.Object:
    """Copy selected Siroino faces and preserve their UVs and skin weights."""
    source_uv = body.data.uv_layers.active
    used: dict[int, int] = {}
    vertices: list[Vector] = []
    source_indices: list[int] = []
    faces: list[list[int]] = []
    face_uvs: list[list[tuple[float, float]]] = []

    for polygon in body.data.polygons:
        center = body.matrix_world @ polygon.center
        if not predicate(polygon, center):
            continue
        face: list[int] = []
        uvs: list[tuple[float, float]] = []
        for loop_index in polygon.loop_indices:
            source_index = body.data.loops[loop_index].vertex_index
            if source_index not in used:
                used[source_index] = len(vertices)
                vertices.append(
                    _world_vertex(body, source_index)
                    + _world_normal(body, source_index) * offset
                )
                source_indices.append(source_index)
            face.append(used[source_index])
            if source_uv is not None:
                uv = source_uv.data[loop_index].uv
                uvs.append((float(uv.x), float(uv.y)))
            else:
                coordinate = _world_vertex(body, source_index)
                uvs.append(((coordinate.x + 0.60) / 1.20, coordinate.z))
        faces.append(face)
        face_uvs.append(uvs)

    if not faces:
        raise RuntimeError(f"Siroino shell selection produced no faces: {name}")

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
            continue
        for item in assignments:
            if item.weight <= 1e-8:
                continue
            group_name = body.vertex_groups[item.group].name
            groups[group_name].add(
                [new_index],
                float(item.weight) / total,
                "REPLACE",
            )

    for polygon in mesh.polygons:
        polygon.use_smooth = True
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    solidify = obj.modifiers.new("Outward jersey thickness", "SOLIDIFY")
    solidify.thickness = thickness
    solidify.offset = 1.0
    solidify.use_even_offset = True
    while obj.modifiers.find(solidify.name) > 0:
        bpy.ops.object.modifier_move_up(modifier=solidify.name)
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    if bevel > 0.0:
        edge_finish = obj.modifiers.new("Finished pattern edge", "BEVEL")
        edge_finish.width = bevel
        edge_finish.segments = 2
        while obj.modifiers.find(edge_finish.name) > 0:
            bpy.ops.object.modifier_move_up(modifier=edge_finish.name)
        bpy.ops.object.modifier_apply(modifier=edge_finish.name)

    cleanup = bmesh.new()
    cleanup.from_mesh(mesh)
    bmesh.ops.dissolve_degenerate(cleanup, dist=1e-7, edges=list(cleanup.edges))
    zero_area = [face for face in cleanup.faces if face.calc_area() <= 1e-12]
    if zero_area:
        bmesh.ops.delete(cleanup, geom=zero_area, context="FACES")
    loose = [vertex for vertex in cleanup.verts if not vertex.link_faces]
    if loose:
        bmesh.ops.delete(cleanup, geom=loose, context="VERTS")
    cleanup.to_mesh(mesh)
    cleanup.free()
    mesh.update(calc_edges=True)
    obj.select_set(False)
    return obj


def _torso_width(z: float) -> float:
    if z < 0.835:
        return 0.118
    if z < 0.910:
        return 0.150
    if z < 0.985:
        return 0.178
    return max(0.078, 0.178 - (z - 0.985) * 1.75)


def _torso_top(x: float) -> float:
    return 1.004 + min(abs(x), 0.12) * 0.20


def _highcut_width(z: float) -> float:
    t = max(0.0, min(1.0, (z - 0.640) / (0.825 - 0.640)))
    return 0.026 + 0.096 * (t ** 0.86)


def _front(center: Vector) -> bool:
    return center.y <= 0.0


def _back(center: Vector) -> bool:
    return center.y > 0.0


def _torso_shells(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> list[bpy.types.Object]:
    def common(center: Vector) -> bool:
        return (
            0.792 <= center.z <= _torso_top(center.x)
            and abs(center.x) <= _torso_width(center.z)
        )

    front = _copy_shell(
        "Heather_Front_Upper_Panel",
        body,
        armature,
        material,
        lambda _polygon, center: common(center) and _front(center),
        offset=0.0065,
    )
    back = _copy_shell(
        "Heather_Back_Upper_Panel",
        body,
        armature,
        material,
        lambda _polygon, center: common(center) and _back(center),
        offset=0.0065,
    )
    return [front, back]


def _highcut_shells(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> list[bpy.types.Object]:
    def common(center: Vector) -> bool:
        return (
            0.630 <= center.z <= 0.830
            and abs(center.x) <= _highcut_width(center.z)
        )

    front = _copy_shell(
        "Heather_Highcut_Front_Panel",
        body,
        armature,
        material,
        lambda _polygon, center: common(center) and _front(center),
        offset=0.0068,
    )
    back = _copy_shell(
        "Heather_Highcut_Back_Panel",
        body,
        armature,
        material,
        lambda _polygon, center: common(center) and _back(center),
        offset=0.0068,
    )
    return [front, back]


def _sleeves_and_cuffs(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    fabric: bpy.types.Material,
    trim: bpy.types.Material,
) -> list[bpy.types.Object]:
    garments: list[bpy.types.Object] = []
    for side in ("L", "R"):
        upper = _group_index(body, f"UpperArm_{side}")
        lower = _group_index(body, f"LowerArm_{side}")
        hand = _group_index(body, f"Hand_{side}")
        _, lower_end = bone_segment(armature, f"LowerArm_{side}")

        def sleeve_predicate(
            polygon: bpy.types.MeshPolygon,
            _center: Vector,
            upper_index: int | None = upper,
            lower_index: int | None = lower,
            hand_index: int | None = hand,
        ) -> bool:
            arm_weight = _polygon_average_weight(
                body,
                polygon,
                (upper_index, lower_index),
            )
            hand_weight = _polygon_average_weight(body, polygon, (hand_index,))
            return arm_weight >= 0.085 and hand_weight <= 0.44

        def cuff_predicate(
            polygon: bpy.types.MeshPolygon,
            center: Vector,
            lower_index: int | None = lower,
            hand_index: int | None = hand,
            wrist: Vector = lower_end,
        ) -> bool:
            wrist_weight = _polygon_average_weight(
                body,
                polygon,
                (lower_index, hand_index),
            )
            return wrist_weight >= 0.12 and (center - wrist).length <= 0.046

        garments.append(
            _copy_shell(
                f"Heather_Long_Sleeve_{side}",
                body,
                armature,
                fabric,
                sleeve_predicate,
                offset=0.0068,
            )
        )
        garments.append(
            _copy_shell(
                f"Heather_Rib_Cuff_{side}",
                body,
                armature,
                trim,
                cuff_predicate,
                offset=0.0088,
                thickness=0.0016,
                bevel=0.00045,
            )
        )
    return garments


def _grid_mesh(
    name: str,
    vertices: list[tuple[float, float, float]],
    rows: int,
    columns: int,
    material: bpy.types.Material,
    armature: bpy.types.Object,
    body: bpy.types.Object,
    *,
    thickness: float,
) -> bpy.types.Object:
    faces: list[tuple[int, int, int, int]] = []
    stride = columns + 1
    for row in range(rows - 1):
        for column in range(columns):
            a = row * stride + column
            faces.append((a, a + 1, a + stride + 1, a + stride))
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
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True
    base.transfer_nearest_body_weights(obj, body)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    solidify = obj.modifiers.new("Hood fabric thickness", "SOLIDIFY")
    solidify.thickness = thickness
    solidify.offset = 0.0
    solidify.use_even_offset = True
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    subdivision = obj.modifiers.new("Hood drape smoothing", "SUBSURF")
    subdivision.subdivision_type = "CATMULL_CLARK"
    subdivision.levels = 1
    subdivision.render_levels = 1
    bpy.ops.object.modifier_apply(modifier=subdivision.name)
    edge_finish = obj.modifiers.new("Hood edge finish", "BEVEL")
    edge_finish.width = 0.0005
    edge_finish.segments = 2
    bpy.ops.object.modifier_apply(modifier=edge_finish.name)
    obj.select_set(False)
    return obj


def _hood_panel(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    side: str,
) -> bpy.types.Object:
    sign = -1.0 if side == "L" else 1.0
    rows = [
        (1.035, 0.052, 0.070, 0.032),
        (1.006, 0.078, 0.106, 0.056),
        (0.972, 0.096, 0.126, 0.068),
        (0.938, 0.088, 0.120, 0.063),
        (0.906, 0.060, 0.101, 0.047),
        (0.880, 0.014, 0.079, 0.017),
    ]
    columns = 16
    vertices: list[tuple[float, float, float]] = []
    for z, width, center_y, wrap in rows:
        for column in range(columns + 1):
            u = column / columns
            x = sign * width * u
            fold = 0.009 * math.sin(math.pi * u)
            y = center_y - wrap * u + fold
            row_drop = 0.005 * math.sin(math.pi * u)
            vertices.append((x, y, z - row_drop))
    return _grid_mesh(
        f"Heather_Hood_Outer_{side}",
        vertices,
        len(rows),
        columns,
        material,
        armature,
        body,
        thickness=0.0018,
    )


def _neck_band(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    points = []
    segments = 72
    for index in range(segments):
        angle = math.tau * index / segments
        points.append(
            (
                0.064 * math.cos(angle),
                -0.002 + 0.047 * math.sin(angle),
                1.010 - 0.004 * max(0.0, -math.sin(angle)),
            )
        )
    band = base.curve_tube(
        "Heather_Hood_Neck_Band",
        points,
        0.0030,
        material,
        armature,
        "Chest",
        cyclic=True,
        resolution=3,
    )
    base.transfer_nearest_body_weights(band, body)
    return band


def _surface_y(
    body: bpy.types.Object,
    x: float,
    z: float,
    *,
    front: bool,
) -> float:
    candidates = [
        _world_vertex(body, vertex.index)
        for vertex in body.data.vertices
        if abs(_world_vertex(body, vertex.index).x - x) <= 0.020
        and abs(_world_vertex(body, vertex.index).z - z) <= 0.028
    ]
    if not candidates:
        candidates = [
            _world_vertex(body, vertex.index)
            for vertex in body.data.vertices
            if abs(_world_vertex(body, vertex.index).z - z) <= 0.045
        ]
    if not candidates:
        raise RuntimeError(f"Could not sample body surface at x={x}, z={z}")
    return min(point.y for point in candidates) if front else max(point.y for point in candidates)


def _placket_and_buttons(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    trim: bpy.types.Material,
    buttons: bpy.types.Material,
) -> list[bpy.types.Object]:
    y = _surface_y(body, 0.0, 0.966, front=True) - 0.010
    placket = legacy.rounded_box(
        "Heather_Henley_Placket",
        (0.0, y, 0.966),
        (0.015, 0.0030, 0.050),
        trim,
        armature,
        "Chest",
        bevel=0.0015,
    )
    result = [placket]
    for index, z in enumerate((0.992, 0.963, 0.934), start=1):
        bpy.ops.mesh.primitive_uv_sphere_add(
            segments=24,
            ring_count=12,
            location=(0.0, y - 0.0065, z),
            scale=(0.0053, 0.0025, 0.0053),
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
    body: bpy.types.Object,
    armature: bpy.types.Object,
    trim: bpy.types.Material,
) -> list[bpy.types.Object]:
    front_neck_y = _surface_y(body, 0.034, 1.000, front=True) - 0.016
    result = []
    for side, sign in (("L", -1.0), ("R", 1.0)):
        cord = base.curve_tube(
            f"Heather_Hood_Drawcord_{side}",
            [
                (sign * 0.035, front_neck_y, 1.006),
                (sign * 0.040, front_neck_y - 0.006, 0.978),
                (sign * 0.043, front_neck_y - 0.008, 0.946),
                (sign * 0.038, front_neck_y - 0.004, 0.925),
            ],
            0.00145,
            trim,
            armature,
            "Chest",
            resolution=3,
        )
        base.transfer_nearest_body_weights(cord, body)
        result.append(cord)

        hip_x = sign * 0.108
        hip_z = 0.790
        hip_y = _surface_y(body, hip_x, hip_z, front=True) - 0.014
        tie = base.curve_tube(
            f"Heather_Side_Tie_{side}",
            [
                (hip_x, hip_y, hip_z),
                (sign * 0.132, hip_y - 0.006, hip_z + 0.004),
                (sign * 0.158, hip_y - 0.004, hip_z - 0.012),
                (sign * 0.176, hip_y + 0.002, hip_z - 0.034),
            ],
            0.0016,
            trim,
            armature,
            "Hips",
            resolution=3,
        )
        base.transfer_nearest_body_weights(tie, body)
        result.append(tie)
    return result


def _seams(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    trim: bpy.types.Material,
) -> list[bpy.types.Object]:
    front_points = []
    for z in (0.650, 0.700, 0.755, 0.810, 0.865, 0.920):
        front_points.append(
            (0.0, _surface_y(body, 0.0, z, front=True) - 0.0085, z)
        )
    back_points = []
    for z in (0.650, 0.700, 0.755, 0.810, 0.865, 0.920):
        back_points.append(
            (0.0, _surface_y(body, 0.0, z, front=False) + 0.0085, z)
        )
    front = base.curve_tube(
        "Heather_Center_Front_Seam",
        front_points,
        0.00055,
        trim,
        armature,
        "Spine",
        resolution=2,
    )
    back = base.curve_tube(
        "Heather_Center_Back_Seam",
        back_points,
        0.00055,
        trim,
        armature,
        "Spine",
        resolution=2,
    )
    hood = base.curve_tube(
        "Heather_Hood_Center_Seam",
        [
            (0.0, 0.070, 1.035),
            (0.0, 0.106, 1.006),
            (0.0, 0.126, 0.972),
            (0.0, 0.120, 0.938),
            (0.0, 0.101, 0.906),
            (0.0, 0.079, 0.880),
        ],
        0.00065,
        trim,
        armature,
        "Chest",
        resolution=2,
    )
    for obj in (front, back, hood):
        base.transfer_nearest_body_weights(obj, body)
    return [front, back, hood]


def create_outfit(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    fabric: bpy.types.Material,
    trim: bpy.types.Material,
    button_material: bpy.types.Material,
) -> list[bpy.types.Object]:
    garments: list[bpy.types.Object] = []
    garments.extend(_torso_shells(body, armature, fabric))
    garments.extend(_highcut_shells(body, armature, fabric))
    garments.extend(_sleeves_and_cuffs(body, armature, fabric, trim))
    garments.extend(
        [
            _hood_panel(body, armature, fabric, "L"),
            _hood_panel(body, armature, fabric, "R"),
            _neck_band(body, armature, fabric),
        ]
    )
    garments.extend(
        _placket_and_buttons(body, armature, trim, button_material)
    )
    garments.extend(_cords_and_ties(body, armature, trim))
    garments.extend(_seams(body, armature, trim))
    return garments
