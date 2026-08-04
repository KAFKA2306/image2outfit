#!/usr/bin/env python3
"""Bevel-safe source-topology shell for the Siroino heather bodysuit.

The fitted torso, high-cut lower body, shoulders, and sleeves are selected from
one SiroinoSotai_PC source mesh and copied as one connected shell. Smooth
accessories are generated separately. The build stops on disconnected primary
geometry, non-finite coordinates, or implausibly long edges.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import bpy
from mathutils import Vector

import siroino_heather_hooded_pattern as v9

DESIGN_REVISION = "v14-source-topology-highcut-shell"
clean_meshes = v9.clean_meshes
bone_segment = v9.bone_segment


PolygonPredicate = Callable[[bpy.types.MeshPolygon, Vector], bool]


def _move_modifier_before_armature(
    obj: bpy.types.Object,
    modifier: bpy.types.Modifier,
) -> None:
    while obj.modifiers.find(modifier.name) > 0:
        bpy.ops.object.modifier_move_up(modifier=modifier.name)


def _selected_polygons(
    body: bpy.types.Object,
    predicate: PolygonPredicate,
) -> list[bpy.types.MeshPolygon]:
    return [
        polygon
        for polygon in body.data.polygons
        if predicate(polygon, body.matrix_world @ polygon.center)
    ]


def _body_panel(
    name: str,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    predicate: PolygonPredicate,
    *,
    offset: float = 0.0065,
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
    for polygon, polygon_uvs in zip(mesh.polygons, face_uvs, strict=True):
        for loop_index, uv in zip(
            polygon.loop_indices,
            polygon_uvs,
            strict=True,
        ):
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


def _torso_width(z: float) -> float:
    if z < 0.835:
        return 0.122
    if z < 0.910:
        return 0.154
    if z < 0.985:
        return 0.184
    return max(0.082, 0.184 - (z - 0.985) * 1.65)


def _torso_top(x: float) -> float:
    return 1.008 + min(abs(x), 0.13) * 0.23


def _highcut_width(z: float) -> float:
    t = max(0.0, min(1.0, (z - 0.625) / (0.835 - 0.625)))
    return 0.032 + 0.100 * t**0.86


def _body_shell_predicate(
    body: bpy.types.Object,
) -> PolygonPredicate:
    arm_groups = {
        side: (
            v9._group_index(body, f"UpperArm_{side}"),
            v9._group_index(body, f"LowerArm_{side}"),
            v9._group_index(body, f"Hand_{side}"),
        )
        for side in ("L", "R")
    }

    def selected(
        polygon: bpy.types.MeshPolygon,
        center: Vector,
    ) -> bool:
        x = abs(center.x)
        torso = 0.790 <= center.z <= _torso_top(center.x) and x <= _torso_width(
            center.z
        )
        highcut = 0.625 <= center.z <= 0.840 and x <= _highcut_width(center.z)
        if torso or highcut:
            return True

        for upper, lower, hand in arm_groups.values():
            arm_weight = v9._polygon_average_weight(
                body,
                polygon,
                (upper, lower),
            )
            hand_weight = v9._polygon_average_weight(body, polygon, (hand,))
            if arm_weight >= 0.025 and hand_weight <= 0.48:
                return True
        return False

    return selected


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
    return max(0.043, min(0.060, distances[index] + 0.012))


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
        t = 0.79 + 0.22 * row / (rows - 1)
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
        thickness=0.0012,
        bevel=0.00020,
        subdivision=0,
    )


def _hood_profile(t: float) -> tuple[float, float, float, float]:
    z = 1.035 + 0.345 * t
    radius_x = 0.105 + 0.070 * math.sin(math.pi * t) - 0.070 * t**4
    radius_y = 0.085 + 0.072 * math.sin(math.pi * t) - 0.050 * t**4
    center_y = 0.018 + 0.040 * t
    return z, radius_x, radius_y, center_y


def _hood_shell(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    rows = 18
    columns = 32
    vertices: list[tuple[float, float, float]] = []
    start_angle = math.radians(-122.0)
    end_angle = math.radians(122.0)
    for row in range(rows):
        t = row / (rows - 1)
        z, radius_x, radius_y, center_y = _hood_profile(t)
        for column in range(columns + 1):
            u = column / columns
            angle = start_angle + (end_angle - start_angle) * u
            x = radius_x * math.sin(angle)
            y = center_y + radius_y * math.cos(angle)
            vertices.append((x, y, z))
    return v9._grid_object(
        "Heather_Hood_Shell",
        vertices,
        rows,
        columns,
        material,
        armature,
        body,
        thickness=0.0014,
        bevel=0.00025,
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
        x = 0.100 * math.cos(angle)
        z = 1.036 + 0.004 * abs(math.cos(angle))
        front_point = sampler.point(x, z, front=True, offset=0.011)
        back_point = sampler.point(x, z, front=False, offset=0.011)
        back_weight = 0.5 * (math.sin(angle) + 1.0)
        point = front_point.lerp(back_point, back_weight)
        points.append((point.x, point.y, point.z))
    band = v9.base.curve_tube(
        "Heather_Hood_Neck_Band",
        points,
        0.0022,
        material,
        armature,
        "Chest",
        cyclic=True,
        resolution=3,
    )
    v9.base.transfer_nearest_body_weights(band, sampler.body)
    return band


def _cords_and_seams(
    sampler: v9.SurfaceSampler,
    armature: bpy.types.Object,
    trim: bpy.types.Material,
) -> list[bpy.types.Object]:
    result: list[bpy.types.Object] = []

    for side, sign in (("L", -1.0), ("R", 1.0)):
        cord_points: list[tuple[float, float, float]] = []
        for x, z in (
            (sign * 0.078, 1.040),
            (sign * 0.082, 1.016),
            (sign * 0.080, 0.992),
            (sign * 0.074, 0.970),
        ):
            point = sampler.point(x, z, front=True, offset=0.014)
            cord_points.append((point.x, point.y, point.z))
        cord = v9.base.curve_tube(
            f"Heather_Hood_Drawcord_{side}",
            cord_points,
            0.00105,
            trim,
            armature,
            "Chest",
            resolution=3,
        )
        v9.base.transfer_nearest_body_weights(cord, sampler.body)
        result.append(cord)

    front_points = [
        sampler.point(0.0, z, front=True, offset=0.012)
        for z in (0.655, 0.710, 0.770, 0.830, 0.895, 0.958, 1.010)
    ]
    back_points = [
        sampler.point(0.0, z, front=False, offset=0.012)
        for z in (0.655, 0.710, 0.770, 0.830, 0.895, 0.958, 1.010)
    ]
    hood_points: list[Vector] = []
    for index in range(13):
        t = index / 12
        z, _radius_x, radius_y, center_y = _hood_profile(t)
        hood_points.append(Vector((0.0, center_y + radius_y + 0.0015, z)))

    for name, points, bone in (
        ("Heather_Center_Front_Seam", front_points, "Spine"),
        ("Heather_Center_Back_Seam", back_points, "Spine"),
        ("Heather_Hood_Center_Seam", hood_points, "Head"),
    ):
        seam = v9.base.curve_tube(
            name,
            [(point.x, point.y, point.z) for point in points],
            0.00038,
            trim,
            armature,
            bone,
            resolution=2,
        )
        v9.base.transfer_nearest_body_weights(seam, sampler.body)
        result.append(seam)
    return result


def _component_count(obj: bpy.types.Object) -> int:
    adjacency: dict[int, set[int]] = {
        vertex.index: set() for vertex in obj.data.vertices
    }
    for edge in obj.data.edges:
        left, right = edge.vertices
        adjacency[left].add(right)
        adjacency[right].add(left)

    remaining = set(adjacency)
    components = 0
    while remaining:
        components += 1
        stack = [remaining.pop()]
        while stack:
            current = stack.pop()
            neighbours = adjacency[current] & remaining
            remaining.difference_update(neighbours)
            stack.extend(neighbours)
    return components


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
        if obj.name == "Heather_Body_Shell":
            components = _component_count(obj)
            if components != 1:
                failures.append(
                    f"{obj.name}: disconnected source shell has {components} components"
                )
    if failures:
        raise RuntimeError(
            "Garment geometry sanity gate failed: " + "; ".join(failures)
        )


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
            _body_shell_predicate(body),
        ),
        _cuff_tube(body, armature, trim, "L"),
        _cuff_tube(body, armature, trim, "R"),
        _hood_shell(body, armature, fabric),
        _neck_band(sampler, armature, fabric),
    ]
    garments.extend(
        v9._placket_and_buttons(
            sampler,
            armature,
            trim,
            button_material,
        )
    )
    garments.extend(_cords_and_seams(sampler, armature, trim))
    _validate_geometry(garments)
    return garments
