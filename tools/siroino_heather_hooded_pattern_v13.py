#!/usr/bin/env python3
"""Standalone bevel-safe v13 Siroino heather bodysuit pattern.

The torso and sleeves are copied once from connected SiroinoSotai_PC topology.
The acute fitted-shell boundary is exported as a single surface: v12 proved
that bevel mitering was unstable, and the first v13 run proved that Solidify's
even-offset miter was equally unstable. Smooth auxiliary panels overlap the
shell and a geometry sanity gate rejects non-finite or implausibly long edges.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import bpy
from mathutils import Vector

import siroino_heather_hooded_pattern as v9

DESIGN_REVISION = "v13-bevel-safe-continuous-shell"
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
    offset: float = 0.020,
    bevel_width: float = 0.0,
) -> bpy.types.Object:
    """Copy a fitted source shell without miter-generating modifiers."""
    if bevel_width != 0.0:
        raise ValueError("The fitted source shell must not use a bevel modifier")
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
            continue
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
    triangulate = obj.modifiers.new("Export triangulation", "TRIANGULATE")
    _move_modifier_before_armature(obj, triangulate)
    bpy.ops.object.modifier_apply(modifier=triangulate.name)
    mesh.validate(verbose=False, clean_customdata=False)
    mesh.update(calc_edges=True)
    obj.select_set(False)
    return obj


def _body_shell_predicate(
    armature: bpy.types.Object,
) -> Callable[[Vector], bool]:
    segments = {
        side: (
            bone_segment(armature, f"UpperArm_{side}"),
            bone_segment(armature, f"LowerArm_{side}"),
        )
        for side in ("L", "R")
    }

    def selected(point: Vector) -> bool:
        torso = abs(point.x) <= 0.265 and 0.775 <= point.z <= 1.038
        if torso:
            return True
        for upper, lower in segments.values():
            upper_distance, upper_t = _segment_distance(point, *upper)
            if upper_distance <= 0.108 and -0.30 <= upper_t <= 1.18:
                return True
            lower_distance, lower_t = _segment_distance(point, *lower)
            if lower_distance <= 0.082 and -0.20 <= lower_t <= 0.94:
                return True
        return False

    return selected


def _highcut_panel(
    sampler: v9.SurfaceSampler,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    *,
    front: bool,
) -> bpy.types.Object:
    rows = 18
    columns = 24
    vertices: list[tuple[float, float, float]] = []
    for row in range(rows):
        t = row / (rows - 1)
        z = 0.640 + 0.205 * t
        half_width = 0.046 + 0.145 * t**1.32
        for column in range(columns + 1):
            u = column / columns
            x = -half_width + 2.0 * half_width * u
            point = sampler.point(x, z, front=front, offset=0.025)
            vertices.append((point.x, point.y, point.z))
    side = "Front" if front else "Back"
    return v9._grid_object(
        f"Heather_Highcut_{side}_Panel",
        vertices,
        rows,
        columns,
        material,
        armature,
        sampler.body,
        thickness=0.0014,
        bevel=0.00030,
        subdivision=1,
    )


def _crotch_bridge(
    sampler: v9.SurfaceSampler,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    rows = 13
    columns = 12
    z = 0.640
    half_width = 0.047
    vertices: list[tuple[float, float, float]] = []
    for row in range(rows):
        depth_t = row / (rows - 1)
        for column in range(columns + 1):
            x = -half_width + 2.0 * half_width * column / columns
            front = sampler.point(x, z, front=True, offset=0.026)
            back = sampler.point(x, z, front=False, offset=0.026)
            point = front.lerp(back, depth_t)
            point.z -= 0.018 * math.sin(math.pi * depth_t)
            vertices.append((point.x, point.y, point.z))
    return v9._grid_object(
        "Heather_Crotch_Bridge",
        vertices,
        rows,
        columns,
        material,
        armature,
        sampler.body,
        thickness=0.0014,
        bevel=0.00030,
        subdivision=1,
    )


def _forearm_radius(
    body: bpy.types.Object,
    start: Vector,
    end: Vector,
    t: float,
) -> float:
    vector = end - start
    length_squared = vector.length_squared
    distances: list[float] = []
    for vertex in body.data.vertices:
        point = body.matrix_world @ vertex.co
        projection = (point - start).dot(vector) / max(length_squared, 1e-12)
        if abs(projection - t) > 0.075:
            continue
        radial = (point - (start + vector * projection)).length
        if radial <= 0.10:
            distances.append(radial)
    if not distances:
        return 0.052
    distances.sort()
    index = min(len(distances) - 1, int(0.82 * len(distances)))
    return max(0.043, min(0.060, distances[index] + 0.020))


def _cuff_tube(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    side: str,
) -> bpy.types.Object:
    start, end = bone_segment(armature, f"LowerArm_{side}")
    tangent = (end - start).normalized()
    reference = Vector((0.0, 0.0, 1.0))
    if abs(tangent.dot(reference)) > 0.92:
        reference = Vector((0.0, 1.0, 0.0))
    axis_a = tangent.cross(reference).normalized()
    axis_b = tangent.cross(axis_a).normalized()
    rows = 8
    columns = 24
    vertices: list[tuple[float, float, float]] = []
    for row in range(rows):
        t = 0.74 + 0.27 * row / (rows - 1)
        center = start.lerp(end, t)
        radius = _forearm_radius(body, start, end, min(t, 0.98))
        for column in range(columns + 1):
            angle = math.tau * column / columns
            radial = axis_a * math.cos(angle) + axis_b * math.sin(angle)
            point = center + radial * radius
            vertices.append((point.x, point.y, point.z))
    return v9._grid_object(
        f"Heather_Rib_Cuff_{side}",
        vertices,
        rows,
        columns,
        material,
        armature,
        body,
        thickness=0.0015,
        bevel=0.00025,
        subdivision=0,
    )


def _hood_half(
    sampler: v9.SurfaceSampler,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    side: str,
) -> bpy.types.Object:
    profiles = [
        (1.045, 0.068, 0.010),
        (1.015, 0.086, 0.020),
        (0.985, 0.105, 0.030),
        (0.955, 0.122, 0.036),
        (0.925, 0.132, 0.030),
        (0.900, 0.116, 0.018),
    ]
    columns = 20
    sign = -1.0 if side == "L" else 1.0
    vertices: list[tuple[float, float, float]] = []
    for z, half_width, drape in profiles:
        for column in range(columns + 1):
            u = column / columns
            x = sign * half_width * u
            point = sampler.point(x, z, front=False, offset=0.030)
            point.y += drape * (1.0 - 0.55 * u)
            point.z += 0.003 * math.sin(math.pi * u)
            vertices.append((point.x, point.y, point.z))
    return v9._grid_object(
        f"Heather_Hood_Outer_{side}",
        vertices,
        len(profiles),
        columns,
        material,
        armature,
        sampler.body,
        thickness=0.0015,
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
        x = 0.098 * math.cos(angle)
        z = 1.038 + 0.004 * abs(math.cos(angle))
        front_point = sampler.point(x, z, front=True, offset=0.024)
        back_point = sampler.point(x, z, front=False, offset=0.024)
        back_weight = 0.5 * (math.sin(angle) + 1.0)
        point = front_point.lerp(back_point, back_weight)
        points.append((point.x, point.y, point.z))
    band = v9.base.curve_tube(
        "Heather_Hood_Neck_Band",
        points,
        0.0024,
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
            (sign * 0.046, 1.026),
            (sign * 0.050, 1.004),
            (sign * 0.052, 0.982),
            (sign * 0.048, 0.962),
        ):
            point = sampler.point(x, z, front=True, offset=0.027)
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

        root_x = sign * 0.205
        root_z = 0.810
        tie = v9.base.curve_tube(
            f"Heather_Side_Tie_{side}",
            [
                (root_x, 0.0, root_z),
                (sign * 0.218, -0.002, root_z - 0.006),
                (sign * 0.229, 0.004, root_z - 0.020),
                (sign * 0.238, 0.010, root_z - 0.038),
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
        sampler.point(0.0, z, front=True, offset=0.028)
        for z in (0.655, 0.710, 0.770, 0.830, 0.895, 0.958, 1.010)
    ]
    back_points = [
        sampler.point(0.0, z, front=False, offset=0.028)
        for z in (0.655, 0.710, 0.770, 0.830, 0.895, 0.958, 1.010)
    ]
    hood_points = []
    for z, _half_width, drape in (
        (1.045, 0.068, 0.010),
        (1.015, 0.086, 0.020),
        (0.985, 0.105, 0.030),
        (0.955, 0.122, 0.036),
        (0.925, 0.132, 0.030),
        (0.900, 0.116, 0.018),
    ):
        point = sampler.point(0.0, z, front=False, offset=0.030)
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


def _validate_geometry(objects: list[bpy.types.Object]) -> None:
    failures: list[str] = []
    for obj in objects:
        if obj.type != "MESH":
            continue
        vertices = obj.data.vertices
        for vertex in vertices:
            if not all(math.isfinite(value) for value in vertex.co):
                failures.append(f"{obj.name}: non-finite vertex {vertex.index}")
                break
        max_edge = max(
            (
                (vertices[edge.vertices[0]].co - vertices[edge.vertices[1]].co).length
                for edge in obj.data.edges
            ),
            default=0.0,
        )
        if max_edge > 0.20:
            failures.append(f"{obj.name}: implausible edge {max_edge:.6f} m")
    if failures:
        raise RuntimeError("Garment geometry sanity gate failed: " + "; ".join(failures))


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
            "Heather_Body_Shell",
            body,
            armature,
            fabric,
            _body_shell_predicate(armature),
        ),
        _highcut_panel(sampler, armature, fabric, front=True),
        _highcut_panel(sampler, armature, fabric, front=False),
        _crotch_bridge(sampler, armature, fabric),
        _cuff_tube(body, armature, trim, "L"),
        _cuff_tube(body, armature, trim, "R"),
        _hood_half(sampler, armature, fabric, "L"),
        _hood_half(sampler, armature, fabric, "R"),
        _neck_band(sampler, armature, fabric),
    ]
    garments.extend(v9._placket_and_buttons(sampler, armature, trim, button_material))
    garments.extend(_cords_ties_seams(sampler, armature, trim))
    _validate_geometry(garments)
    return garments
