#!/usr/bin/env python3
"""Semantic five-opening weighted shell for the Siroino hooded bodysuit.

The neutral SiroinoSotai_PC shape is baked from the evaluated dependency graph
and subdivided twice. Torso, crotch bridge and sleeves are extracted as one
source-topology shell. Adjacent unselected face components are classified as
the neck, two wrist and two leg openings by their world-space positions; every
other component is restored from source topology. Rendering is blocked unless
the shell is one connected component with exactly five boundary loops.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Callable

import bpy
from mathutils import Vector

import siroino_heather_hooded_pattern as v9

DESIGN_REVISION = "v20-semantic-five-opening-highcut-shell"
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
    """Bake the neutral target shape without retaining a Shape Key datablock."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = body.evaluated_get(depsgraph)
    mesh = bpy.data.meshes.new_from_object(
        evaluated,
        preserve_all_data_layers=True,
        depsgraph=depsgraph,
    )
    if len(mesh.vertices) != len(body.data.vertices):
        evaluated_count = len(mesh.vertices)
        source_count = len(body.data.vertices)
        bpy.data.meshes.remove(mesh)
        raise RuntimeError(
            "Evaluated Siroino source changed topology before refinement: "
            f"{source_count} -> {evaluated_count} vertices"
        )
    if mesh.shape_keys is not None:
        bpy.data.meshes.remove(mesh)
        raise RuntimeError("Evaluated source unexpectedly retained Shape Keys")

    source = body.copy()
    source.data = mesh
    source.name = "Heather_Temporary_Evaluated_Source"
    source.data.name = "Heather_Temporary_Evaluated_Source_Mesh"
    bpy.context.collection.objects.link(source)
    source.matrix_world = body.matrix_world.copy()
    source.hide_render = True

    for modifier in list(source.modifiers):
        source.modifiers.remove(modifier)

    bpy.ops.object.select_all(action="DESELECT")
    source.select_set(True)
    bpy.context.view_layer.objects.active = source
    subdivision = source.modifiers.new("Boundary refinement", "SUBSURF")
    subdivision.subdivision_type = "CATMULL_CLARK"
    subdivision.levels = 2
    subdivision.render_levels = 2
    bpy.ops.object.modifier_apply(modifier=subdivision.name)
    source.data.update(calc_edges=True)
    source.select_set(False)
    return source


def _remove_temporary_source(source: bpy.types.Object) -> None:
    mesh = source.data
    bpy.data.objects.remove(source, do_unlink=True)
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def _purge_orphan_shape_keys() -> None:
    for shape_keys in list(bpy.data.shape_keys):
        if shape_keys.users == 0:
            bpy.data.shape_keys.remove(shape_keys)


def _polygon_adjacency(mesh: bpy.types.Mesh) -> dict[int, set[int]]:
    edge_faces: defaultdict[tuple[int, int], list[int]] = defaultdict(list)
    for polygon in mesh.polygons:
        for edge in polygon.edge_keys:
            edge_faces[tuple(sorted(edge))].append(polygon.index)

    adjacency = {polygon.index: set() for polygon in mesh.polygons}
    for faces in edge_faces.values():
        for left in faces:
            adjacency[left].update(right for right in faces if right != left)
    return adjacency


def _component_center(
    body: bpy.types.Object,
    component: set[int],
) -> Vector:
    weighted = Vector((0.0, 0.0, 0.0))
    total_area = 0.0
    for index in component:
        polygon = body.data.polygons[index]
        area = max(float(polygon.area), 1e-12)
        weighted += (body.matrix_world @ polygon.center) * area
        total_area += area
    return weighted / max(total_area, 1e-12)


def _opening_components(
    body: bpy.types.Object,
    selected_indices: set[int],
) -> list[dict[str, object]]:
    adjacency = _polygon_adjacency(body.data)
    remaining = set(adjacency) - selected_indices
    components: list[dict[str, object]] = []

    while remaining:
        component = {remaining.pop()}
        stack = list(component)
        while stack:
            current = stack.pop()
            neighbours = adjacency[current] & remaining
            remaining.difference_update(neighbours)
            component.update(neighbours)
            stack.extend(neighbours)

        boundary_links = sum(
            len(adjacency[index] & selected_indices) for index in component
        )
        if boundary_links == 0:
            continue
        components.append(
            {
                "faces": component,
                "area": sum(body.data.polygons[index].area for index in component),
                "boundaryLinks": boundary_links,
                "center": _component_center(body, component),
            }
        )
    return components


def _pick_side_component(
    components: list[dict[str, object]],
    excluded: set[int],
    *,
    sign: float,
    role: str,
) -> int:
    candidates: list[tuple[float, int]] = []
    for index, component in enumerate(components):
        if index in excluded:
            continue
        center = component["center"]
        assert isinstance(center, Vector)
        signed_x = sign * center.x
        if role == "wrist" and signed_x >= 0.18:
            candidates.append((signed_x, index))
        elif role == "leg" and signed_x >= 0.015 and center.z <= 0.72:
            candidates.append((-center.z, index))
    if not candidates:
        raise RuntimeError(
            f"Semantic opening classification could not find {role} on x-sign {sign:+.0f}"
        )
    candidates.sort(reverse=True)
    return candidates[0][1]


def _close_unintended_openings(
    body: bpy.types.Object,
    selected: list[bpy.types.MeshPolygon],
    intended_openings: int = 5,
) -> list[bpy.types.MeshPolygon]:
    """Retain neck, two wrists and two legs; restore every other complement."""
    if intended_openings != 5:
        raise ValueError("The bodysuit contract requires exactly five openings")

    selected_indices = {polygon.index for polygon in selected}
    components = _opening_components(body, selected_indices)
    if len(components) < intended_openings:
        raise RuntimeError(
            "Semantic opening classification requires at least five adjacent "
            f"complement components, found {len(components)}"
        )

    neck_candidates = [
        (component["center"].z, index)
        for index, component in enumerate(components)
        if isinstance(component["center"], Vector)
        and component["center"].z >= 0.95
    ]
    if not neck_candidates:
        raise RuntimeError("Semantic opening classification could not find the neck")
    neck_index = max(neck_candidates)[1]

    retained = {neck_index}
    retained.add(
        _pick_side_component(components, retained, sign=-1.0, role="wrist")
    )
    retained.add(
        _pick_side_component(components, retained, sign=1.0, role="wrist")
    )
    retained.add(_pick_side_component(components, retained, sign=-1.0, role="leg"))
    retained.add(_pick_side_component(components, retained, sign=1.0, role="leg"))

    if len(retained) != intended_openings:
        raise RuntimeError(
            "Semantic opening classification did not produce five unique components"
        )

    restored_indices = {
        face
        for index, component in enumerate(components)
        if index not in retained
        for face in component["faces"]
    }
    selected_indices.update(restored_indices)

    summary = []
    for index, component in enumerate(components):
        center = component["center"]
        assert isinstance(center, Vector)
        summary.append(
            f"{index}:x={center.x:.3f},z={center.z:.3f},"
            f"area={float(component['area']):.4f},"
            f"links={int(component['boundaryLinks'])},"
            f"retained={index in retained}"
        )
    print(
        "Healed unintended garment openings semantically: "
        f"retained={len(retained)}, closed={len(components) - len(retained)}, "
        f"restoredFaces={len(restored_indices)}; " + " | ".join(summary)
    )
    return [body.data.polygons[index] for index in sorted(selected_indices)]


def _selected_polygons(
    body: bpy.types.Object,
    predicate: PolygonPredicate,
) -> list[bpy.types.MeshPolygon]:
    selected = [
        polygon
        for polygon in body.data.polygons
        if predicate(polygon, body.matrix_world @ polygon.center)
    ]
    return _close_unintended_openings(body, selected)


def _source_preserve_volume(body: bpy.types.Object) -> bool:
    for modifier in body.modifiers:
        if modifier.type == "ARMATURE":
            return bool(modifier.use_deform_preserve_volume)
    return False


def _boundary_vertex_weights(mesh: bpy.types.Mesh) -> dict[int, float]:
    edge_use: Counter[tuple[int, int]] = Counter()
    adjacency: dict[int, set[int]] = {vertex.index: set() for vertex in mesh.vertices}
    for polygon in mesh.polygons:
        vertices = list(polygon.vertices)
        for index, left in enumerate(vertices):
            right = vertices[(index + 1) % len(vertices)]
            edge = tuple(sorted((left, right)))
            edge_use[edge] += 1
            adjacency[left].add(right)
            adjacency[right].add(left)

    boundary = {
        vertex for edge, count in edge_use.items() if count == 1 for vertex in edge
    }
    weights = {index: 1.0 for index in boundary}
    frontier = set(boundary)
    visited = set(boundary)
    for ring_weight in (0.55, 0.25):
        next_frontier = {
            neighbour
            for index in frontier
            for neighbour in adjacency[index]
            if neighbour not in visited
        }
        for index in next_frontier:
            weights[index] = ring_weight
        visited.update(next_frontier)
        frontier = next_frontier
    return weights


def _smooth_and_project_boundaries(
    obj: bpy.types.Object,
    source: bpy.types.Object,
    offset: float,
) -> None:
    weights = _boundary_vertex_weights(obj.data)
    if not weights:
        return
    group = obj.vertex_groups.new(name="Temporary_Boundary_Smoothing")
    group_name = group.name
    for index, weight in weights.items():
        group.add([index], weight, "REPLACE")

    smooth = obj.modifiers.new("Opening boundary smoothing", "SMOOTH")
    smooth.vertex_group = group_name
    smooth.factor = 0.62
    smooth.iterations = 7
    _move_modifier_before_armature(obj, smooth)
    bpy.ops.object.modifier_apply(modifier=smooth.name)

    shrinkwrap = obj.modifiers.new("Evaluated target reprojection", "SHRINKWRAP")
    shrinkwrap.target = source
    shrinkwrap.wrap_method = "NEAREST_SURFACEPOINT"
    shrinkwrap.offset = offset
    _move_modifier_before_armature(obj, shrinkwrap)
    bpy.ops.object.modifier_apply(modifier=shrinkwrap.name)

    temporary_group = obj.vertex_groups.get(group_name)
    if temporary_group is not None:
        obj.vertex_groups.remove(temporary_group)


def _body_panel(
    name: str,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    predicate: PolygonPredicate,
    *,
    offset: float = 0.012,
    bevel_width: float = 0.0,
    preserve_volume: bool = False,
) -> bpy.types.Object:
    """Copy and surface-project one fitted shell without miter modifiers."""
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
    _smooth_and_project_boundaries(obj, body, offset)
    triangulate = obj.modifiers.new("Export triangulation", "TRIANGULATE")
    _move_modifier_before_armature(obj, triangulate)
    bpy.ops.object.modifier_apply(modifier=triangulate.name)
    mesh.validate(verbose=False, clean_customdata=False)
    mesh.update(calc_edges=True)
    obj.select_set(False)
    return obj


def _torso_width(z: float) -> float:
    if z < 0.880:
        return 0.165
    if z < 0.960:
        return 0.195
    return max(0.090, 0.195 - (z - 0.960) * 1.35)


def _torso_top(x: float) -> float:
    return 1.018 + min(abs(x), 0.150) * 0.29


def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def _highcut_width(z: float) -> float:
    """Join a narrow crotch bridge continuously into the lower torso shell."""
    t = (z - 0.600) / (0.850 - 0.600)
    return 0.032 + 0.133 * _smoothstep(t)


def _body_shell_predicate(body: bpy.types.Object) -> PolygonPredicate:
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
        torso = 0.815 <= center.z <= _torso_top(center.x) and x <= _torso_width(
            center.z
        )
        highcut = 0.600 <= center.z <= 0.850 and x <= _highcut_width(center.z)
        if torso or highcut:
            return True

        for upper, lower, hand in arm_groups.values():
            upper_weight = v9._polygon_average_weight(body, polygon, (upper,))
            lower_weight = v9._polygon_average_weight(body, polygon, (lower,))
            hand_weight = v9._polygon_average_weight(body, polygon, (hand,))
            arm_weight = upper_weight + lower_weight
            if hand_weight <= 0.52 and arm_weight >= 0.008:
                return True
            if center.z >= 0.900 and upper_weight >= 0.002:
                return True
        return False

    return selected


def _hood_folded_roll(
    sampler: v9.SurfaceSampler,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    points: list[tuple[float, float, float]] = []
    count = 33
    for index in range(count):
        lateral = 2.0 * index / (count - 1) - 1.0
        x = 0.095 * lateral
        center_weight = 1.0 - lateral * lateral
        z = 1.022 - 0.030 * center_weight
        offset = 0.046 + 0.010 * center_weight
        point = sampler.point(x, z, front=False, offset=offset)
        points.append((point.x, point.y, point.z))
    roll = v9.base.curve_tube(
        "Heather_Hood_Folded_Roll",
        points,
        0.0095,
        material,
        armature,
        "Chest",
        resolution=5,
    )
    v9.base.transfer_nearest_body_weights(roll, sampler.body)
    return roll


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
            if boundary_loops != 5:
                failures.append(
                    f"{obj.name}: expected exactly 5 anatomical garment openings, "
                    f"found {boundary_loops} boundary loops ({boundary_edges} edges)"
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
            _body_shell_predicate(refined),
            preserve_volume=_source_preserve_volume(body),
        )
    finally:
        _remove_temporary_source(refined)
        _purge_orphan_shape_keys()

    garments: list[bpy.types.Object] = [
        shell,
        _hood_folded_roll(sampler, armature, fabric),
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
