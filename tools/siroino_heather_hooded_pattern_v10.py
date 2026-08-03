#!/usr/bin/env python3
"""Body-topology v11 pattern for the Siroino heather hooded bodysuit.

This revision removes the mixed construction that left the v10 torso attached
to the body while keeping the v9 sleeves, cuffs, hood and trims on fixed,
oversized offsets. All fitted parts are now derived from SiroinoSotai_PC
topology, use the source UVs and weights, and share a 12 mm garment clearance.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import bpy
from mathutils import Vector

import siroino_heather_hooded_pattern as v9

# Preserve the geometry-module interface expected by the generic product build.
clean_meshes = v9.clean_meshes
bone_segment = v9.bone_segment


def _segment_distance(
    point: Vector,
    start: Vector,
    end: Vector,
) -> tuple[float, float]:
    vector = end - start
    length_squared = vector.length_squared
    if length_squared <= 1e-12:
        return (point - start).length, 0.0
    raw_t = (point - start).dot(vector) / length_squared
    closest = start + vector * raw_t
    return (point - closest).length, raw_t


def _move_modifier_before_armature(
    obj: bpy.types.Object,
    modifier: bpy.types.Modifier,
) -> None:
    while obj.modifiers.find(modifier.name) > 0:
        bpy.ops.object.modifier_move_up(modifier=modifier.name)


def _selected_polygons(
    body: bpy.types.Object,
    predicate: Callable[[Vector], bool],
) -> list[bpy.types.MeshPolygon]:
    selected: list[bpy.types.MeshPolygon] = []
    for polygon in body.data.polygons:
        center = body.matrix_world @ polygon.center
        vertex_hits = sum(
            predicate(body.matrix_world @ body.data.vertices[index].co)
            for index in polygon.vertices
        )
        required = max(2, math.ceil(len(polygon.vertices) * 0.5))
        if predicate(center) or vertex_hits >= required:
            selected.append(polygon)
    return selected


def _body_panel(
    name: str,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    predicate: Callable[[Vector], bool],
    *,
    offset: float = 0.012,
    thickness: float = 0.0012,
    bevel_width: float = 0.00030,
) -> bpy.types.Object:
    """Copy a fitted garment region directly from the target avatar topology."""
    selected = _selected_polygons(body, predicate)
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
                point += normal * offset
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
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True

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

    solidify = obj.modifiers.new("Fabric thickness", "SOLIDIFY")
    solidify.thickness = thickness
    solidify.offset = 1.0
    solidify.use_even_offset = True
    _move_modifier_before_armature(obj, solidify)
    bpy.ops.object.modifier_apply(modifier=solidify.name)

    bevel = obj.modifiers.new("Finished edge", "BEVEL")
    bevel.width = bevel_width
    bevel.segments = 2
    _move_modifier_before_armature(obj, bevel)
    bpy.ops.object.modifier_apply(modifier=bevel.name)

    triangulate = obj.modifiers.new("Export triangulation", "TRIANGULATE")
    _move_modifier_before_armature(obj, triangulate)
    bpy.ops.object.modifier_apply(modifier=triangulate.name)

    obj.select_set(False)
    return obj


def _panel_predicate(front: bool) -> Callable[[Vector], bool]:
    def selected(point: Vector) -> bool:
        side_ok = point.y <= 0.025 if front else point.y >= -0.025
        if not side_ok:
            return False

        x = abs(point.x)
        z = point.z
        if x > 0.245:
            return False

        neck_center = 0.992 if front else 1.010
        neck_side = 1.058 if front else 1.052
        neck_t = min(1.0, x / 0.225)
        neckline = neck_center + (neck_side - neck_center) * neck_t**1.65
        torso = 0.785 <= z <= neckline

        if 0.650 <= z < 0.825:
            t = (z - 0.650) / 0.175
            half_width = 0.048 + 0.132 * max(0.0, min(1.0, t)) ** 1.25
            highcut = x <= half_width
        else:
            highcut = False
        return torso or highcut

    return selected


def _sleeve_predicate(
    armature: bpy.types.Object,
    side: str,
) -> Callable[[Vector], bool]:
    upper_start, upper_end = bone_segment(armature, f"UpperArm_{side}")
    lower_start, lower_end = bone_segment(armature, f"LowerArm_{side}")

    def selected(point: Vector) -> bool:
        upper_distance, upper_t = _segment_distance(point, upper_start, upper_end)
        lower_distance, lower_t = _segment_distance(point, lower_start, lower_end)
        upper_radius = 0.084 - 0.012 * max(0.0, min(1.0, upper_t))
        return (upper_distance <= upper_radius and -0.16 <= upper_t <= 1.06) or (
            lower_distance <= 0.062 and -0.05 <= lower_t <= 1.02
        )

    return selected


def _cuff_predicate(
    armature: bpy.types.Object,
    side: str,
) -> Callable[[Vector], bool]:
    lower_start, lower_end = bone_segment(armature, f"LowerArm_{side}")

    def selected(point: Vector) -> bool:
        distance, t = _segment_distance(point, lower_start, lower_end)
        return distance <= 0.055 and 0.78 <= t <= 1.05

    return selected


def _sleeves_and_cuffs(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    fabric: bpy.types.Material,
    trim: bpy.types.Material,
) -> list[bpy.types.Object]:
    result: list[bpy.types.Object] = []
    for side in ("L", "R"):
        result.append(
            _body_panel(
                f"Heather_Long_Sleeve_{side}",
                body,
                armature,
                fabric,
                _sleeve_predicate(armature, side),
                offset=0.012,
                thickness=0.0013,
                bevel_width=0.00030,
            )
        )
        result.append(
            _body_panel(
                f"Heather_Rib_Cuff_{side}",
                body,
                armature,
                trim,
                _cuff_predicate(armature, side),
                offset=0.012,
                thickness=0.0015,
                bevel_width=0.00025,
            )
        )
    return result


def _hood_half(
    sampler: v9.SurfaceSampler,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    side: str,
) -> bpy.types.Object:
    profiles = [
        (1.030, 0.086, 0.010),
        (1.006, 0.102, 0.025),
        (0.976, 0.118, 0.047),
        (0.944, 0.132, 0.066),
        (0.912, 0.122, 0.055),
        (0.886, 0.092, 0.027),
    ]
    columns = 20
    sign = -1.0 if side == "L" else 1.0
    vertices: list[tuple[float, float, float]] = []
    for z, half_width, drape in profiles:
        for column in range(columns + 1):
            u = column / columns
            x = sign * half_width * u
            point = sampler.point(x, z, front=False, offset=0.012)
            edge_attachment = 1.0 - u**1.7
            point.y += drape * edge_attachment
            point.z += 0.005 * math.sin(math.pi * u)
            vertices.append((point.x, point.y, point.z))
    return v9._grid_object(
        f"Heather_Hood_Outer_{side}",
        vertices,
        len(profiles),
        columns,
        material,
        armature,
        sampler.body,
        thickness=0.0016,
        bevel=0.00035,
        subdivision=1,
    )


def _neck_band(
    sampler: v9.SurfaceSampler,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    points: list[tuple[float, float, float]] = []
    count = 72
    for index in range(count):
        angle = math.tau * index / count
        x = 0.092 * math.cos(angle)
        front = math.sin(angle) < 0.0
        normalized_x = min(1.0, abs(x) / 0.092)
        if front:
            z = 0.996 + 0.044 * normalized_x**1.65
        else:
            z = 1.010 + 0.028 * normalized_x**1.55
        point = sampler.point(x, z, front=front, offset=0.015)
        points.append((point.x, point.y, point.z))
    band = v9.base.curve_tube(
        "Heather_Hood_Neck_Band",
        points,
        0.0021,
        material,
        armature,
        "Chest",
        cyclic=True,
        resolution=3,
    )
    v9.base.transfer_nearest_body_weights(band, sampler.body)
    return band


def _cords_ties_seams(
    sampler: v9.SurfaceSampler,
    armature: bpy.types.Object,
    trim: bpy.types.Material,
) -> list[bpy.types.Object]:
    result: list[bpy.types.Object] = []

    for side, sign in (("L", -1.0), ("R", 1.0)):
        cord_points: list[tuple[float, float, float]] = []
        for x, z in (
            (sign * 0.046, 1.014),
            (sign * 0.050, 0.992),
            (sign * 0.052, 0.970),
            (sign * 0.048, 0.950),
        ):
            point = sampler.point(x, z, front=True, offset=0.020)
            cord_points.append((point.x, point.y, point.z))
        cord = v9.base.curve_tube(
            f"Heather_Hood_Drawcord_{side}",
            cord_points,
            0.00115,
            trim,
            armature,
            "Chest",
            resolution=3,
        )
        v9.base.transfer_nearest_body_weights(cord, sampler.body)
        result.append(cord)

        root_x = sign * 0.170
        root_z = 0.807
        tie = v9.base.curve_tube(
            f"Heather_Side_Tie_{side}",
            [
                (root_x, 0.0, root_z),
                (sign * 0.184, -0.002, root_z - 0.004),
                (sign * 0.198, 0.004, root_z - 0.018),
                (sign * 0.208, 0.010, root_z - 0.038),
            ],
            0.00125,
            trim,
            armature,
            "Hips",
            resolution=3,
        )
        v9.base.transfer_nearest_body_weights(tie, sampler.body)
        result.append(tie)

    front_points = [
        sampler.point(0.0, z, front=True, offset=0.018)
        for z in (0.674, 0.728, 0.786, 0.846, 0.906, 0.958)
    ]
    back_points = [
        sampler.point(0.0, z, front=False, offset=0.018)
        for z in (0.674, 0.728, 0.786, 0.846, 0.906, 0.958)
    ]
    hood_points = []
    for z, _half_width, drape in (
        (1.030, 0.086, 0.010),
        (1.006, 0.102, 0.025),
        (0.976, 0.118, 0.047),
        (0.944, 0.132, 0.066),
        (0.912, 0.122, 0.055),
        (0.886, 0.092, 0.027),
    ):
        point = sampler.point(0.0, z, front=False, offset=0.012)
        point.y += drape + 0.0015
        hood_points.append(point)

    for name, points, bone in (
        ("Heather_Center_Front_Seam", front_points, "Spine"),
        ("Heather_Center_Back_Seam", back_points, "Spine"),
        ("Heather_Hood_Center_Seam", hood_points, "Chest"),
    ):
        seam = v9.base.curve_tube(
            name,
            [(point.x, point.y, point.z) for point in points],
            0.00042,
            trim,
            armature,
            bone,
            resolution=2,
        )
        v9.base.transfer_nearest_body_weights(seam, sampler.body)
        result.append(seam)
    return result


def create_outfit(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    fabric: bpy.types.Material,
    trim: bpy.types.Material,
    button_material: bpy.types.Material,
) -> list[bpy.types.Object]:
    sampler = v9.SurfaceSampler(body)
    garments: list[bpy.types.Object] = [
        _body_panel(
            "Heather_Front_Body_Panel",
            body,
            armature,
            fabric,
            _panel_predicate(True),
        ),
        _body_panel(
            "Heather_Back_Body_Panel",
            body,
            armature,
            fabric,
            _panel_predicate(False),
        ),
    ]
    garments.extend(_sleeves_and_cuffs(body, armature, fabric, trim))
    garments.extend(
        [
            _hood_half(sampler, armature, fabric, "L"),
            _hood_half(sampler, armature, fabric, "R"),
            _neck_band(sampler, armature, fabric),
        ]
    )
    garments.extend(v9._placket_and_buttons(sampler, armature, trim, button_material))
    garments.extend(_cords_ties_seams(sampler, armature, trim))
    return garments
