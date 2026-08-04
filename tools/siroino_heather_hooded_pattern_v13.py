#!/usr/bin/env python3
"""Topology-refined fitted shell for the Siroino heather hooded bodysuit.

The source body is subdivided once before garment extraction so implicit cut
boundaries no longer follow coarse source polygons. Torso, high-cut pelvis,
shoulders and sleeves are copied as one shell. An explicit shoulder bridge joins
the torso and arm capsules. A compact hood-down cowl replaces the rejected
inflated hood. The build stops on disconnected primary geometry, unexpected
boundary loops, non-finite coordinates, or implausibly long edges.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable

import bpy
from mathutils import Vector

import siroino_heather_hooded_pattern as v9

DESIGN_REVISION = "v16-shoulder-bridged-refined-shell"
clean_meshes = v9.clean_meshes
bone_segment = v9.bone_segment


PolygonPredicate = Callable[[bpy.types.MeshPolygon, Vector], bool]


def _move_modifier_before_armature(
    obj: bpy.types.Object,
    modifier: bpy.types.Modifier,
) -> None:
    while obj.modifiers.find(modifier.name) > 0:
        bpy.ops.object.modifier_move_up(modifier=modifier.name)


def _refined_body_source(body: bpy.types.Object) -> bpy.types.Object:
    """Create a temporary shape-key-free source with interpolated UVs and weights."""
    source = body.copy()
    source.data = body.data.copy()
    source.name = "Heather_Temporary_Refined_Source"
    source.data.name = "Heather_Temporary_Refined_Source_Mesh"
    bpy.context.collection.objects.link(source)
    source.matrix_world = body.matrix_world.copy()
    source.hide_render = True

    for modifier in list(source.modifiers):
        source.modifiers.remove(modifier)
    if source.data.shape_keys is not None:
        source.shape_key_clear()

    bpy.ops.object.select_all(action="DESELECT")
    source.select_set(True)
    bpy.context.view_layer.objects.active = source
    subdivision = source.modifiers.new("Boundary refinement", "SUBSURF")
    subdivision.subdivision_type = "CATMULL_CLARK"
    subdivision.levels = 1
    subdivision.render_levels = 1
    bpy.ops.object.modifier_apply(modifier=subdivision.name)
    source.data.update(calc_edges=True)
    source.select_set(False)
    return source


def _remove_temporary_source(source: bpy.types.Object) -> None:
    mesh = source.data
    bpy.data.objects.remove(source, do_unlink=True)
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def _selected_polygons(
    body: bpy.types.Object,
    predicate: PolygonPredicate,
) -> list[bpy.types.MeshPolygon]:
    return [
        polygon
        for polygon in body.data.polygons
        if predicate(polygon, body.matrix_world @ polygon.center)
    ]


def _source_preserve_volume(body: bpy.types.Object) -> bool:
    for modifier in body.modifiers:
        if modifier.type == "ARMATURE":
            return bool(modifier.use_deform_preserve_volume)
    return False


def _body_panel(
    name: str,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    predicate: PolygonPredicate,
    *,
    offset: float = 0.010,
    bevel_width: float = 0.0,
    preserve_volume: bool = False,
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
    modifier.use_deform_preserve_volume = preserve_volume

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
        return 0.126
    if z < 0.910:
        return 0.160
    if z < 0.985:
        return 0.194
    return max(0.088, 0.194 - (z - 0.985) * 1.45)


def _torso_top(x: float) -> float:
    return 1.012 + min(abs(x), 0.145) * 0.27


def _highcut_width(z: float) -> float:
    t = max(0.0, min(1.0, (z - 0.620) / (0.842 - 0.620)))
    return 0.040 + 0.102 * t**0.78


def _segment_coordinates(
    point: Vector,
    start: Vector,
    end: Vector,
) -> tuple[float, float]:
    vector = end - start
    length_squared = max(vector.length_squared, 1e-12)
    t = (point - start).dot(vector) / length_squared
    closest = start + vector * max(0.0, min(1.0, t))
    return t, (point - closest).length


def _body_shell_predicate(
    armature: bpy.types.Object,
) -> PolygonPredicate:
    arm_segments = {
        side: (
            bone_segment(armature, f"UpperArm_{side}"),
            bone_segment(armature, f"LowerArm_{side}"),
        )
        for side in ("L", "R")
    }

    def selected(
        _polygon: bpy.types.MeshPolygon,
        center: Vector,
    ) -> bool:
        x = abs(center.x)
        torso = 0.785 <= center.z <= _torso_top(center.x) and x <= _torso_width(
            center.z
        )
        highcut = 0.615 <= center.z <= 0.850 and x <= _highcut_width(center.z)
        shoulder_bridge = 0.105 <= x <= 0.360 and 0.925 <= center.z <= 1.090
        if torso or highcut or shoulder_bridge:
            return True

        for upper_segment, lower_segment in arm_segments.values():
            upper_t, upper_distance = _segment_coordinates(center, *upper_segment)
            lower_t, lower_distance = _segment_coordinates(center, *lower_segment)
            if -0.25 <= upper_t <= 1.10 and upper_distance <= 0.110:
                return True
            if -0.10 <= lower_t <= 0.92 and lower_distance <= 0.080:
                return True
        return False

    return selected


def _hood_down_cowl(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    rows = 9
    columns = 32
    vertices: list[tuple[float, float, float]] = []
    start_angle = math.radians(-118.0)
    end_angle = math.radians(118.0)
    for row in range(rows):
        v = row / (rows - 1)
        radius = 0.092 + 0.048 * v
        for column in range(columns + 1):
            u = column / columns
            angle = start_angle + (end_angle - start_angle) * u
            back_arch = max(0.0, math.cos(angle))
            x = radius * math.sin(angle)
            y = 0.018 + radius * 0.58 * math.cos(angle)
            z = 1.042 - 0.052 * v + 0.012 * back_arch**2
            vertices.append((x, y, z))
    return v9._grid_object(
        "Heather_Hood_Down_Cowl",
        vertices,
        rows,
        columns,
        material,
        armature,
        body,
        thickness=0.0012,
        bevel=0.00018,
        subdivision=1,
    )


def _cords(
    sampler: v9.SurfaceSampler,
    armature: bpy.types.Object,
    trim: bpy.types.Material,
) -> list[bpy.types.Object]:
    result: list[bpy.types.Object] = []
    for side, sign in (("L", -1.0), ("R", 1.0)):
        points: list[tuple[float, float, float]] = []
        for x, z in (
            (sign * 0.072, 1.026),
            (sign * 0.074, 1.004),
            (sign * 0.070, 0.982),
        ):
            point = sampler.point(x, z, front=True, offset=0.014)
            points.append((point.x, point.y, point.z))
        cord = v9.base.curve_tube(
            f"Heather_Hood_Drawcord_{side}",
            points,
            0.00085,
            trim,
            armature,
            "Chest",
            resolution=2,
        )
        v9.base.transfer_nearest_body_weights(cord, sampler.body)
        result.append(cord)
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


def _boundary_metrics(obj: bpy.types.Object) -> tuple[int, int]:
    edge_use: Counter[tuple[int, int]] = Counter()
    for polygon in obj.data.polygons:
        vertices = list(polygon.vertices)
        for index, left in enumerate(vertices):
            right = vertices[(index + 1) % len(vertices)]
            edge_use[tuple(sorted((left, right)))] += 1
    boundary_edges = [edge for edge, count in edge_use.items() if count == 1]
    adjacency: dict[int, set[int]] = {}
    for left, right in boundary_edges:
        adjacency.setdefault(left, set()).add(right)
        adjacency.setdefault(right, set()).add(left)
    remaining = set(adjacency)
    loops = 0
    while remaining:
        loops += 1
        stack = [remaining.pop()]
        while stack:
            current = stack.pop()
            neighbours = adjacency[current] & remaining
            remaining.difference_update(neighbours)
            stack.extend(neighbours)
    return loops, len(boundary_edges)


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
            boundary_loops, boundary_edges = _boundary_metrics(obj)
            if components != 1:
                failures.append(
                    f"{obj.name}: disconnected source shell has {components} components"
                )
            if boundary_loops > 5:
                failures.append(
                    f"{obj.name}: expected at most 5 garment openings, found "
                    f"{boundary_loops} boundary loops ({boundary_edges} edges)"
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
    refined = _refined_body_source(body)
    try:
        shell = _body_panel(
            "Heather_Body_Shell",
            refined,
            armature,
            fabric,
            _body_shell_predicate(armature),
            preserve_volume=_source_preserve_volume(body),
        )
    finally:
        _remove_temporary_source(refined)

    garments: list[bpy.types.Object] = [
        shell,
        _hood_down_cowl(body, armature, fabric),
    ]
    garments.extend(
        v9._placket_and_buttons(
            sampler,
            armature,
            trim,
            button_material,
        )
    )
    garments.extend(_cords(sampler, armature, trim))
    _validate_geometry(garments)
    return garments
