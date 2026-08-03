#!/usr/bin/env python3
"""Bevel-safe v13 patch for the Siroino heather hooded bodysuit.

V12 proved that the connected source-topology shell was the correct structural
direction, but applying Blender's bevel modifier to its acute selection
boundary generated metre-scale miter vertices. This module keeps the v12
construction, replaces only the fitted-shell builder with a bounded variant,
reduces the underbody sag, and rejects implausible mesh edges before export.
"""

from __future__ import annotations

import math

import bpy

import siroino_heather_hooded_pattern_v10 as v12

DESIGN_REVISION = "v13-bevel-safe-continuous-shell"
clean_meshes = v12.clean_meshes
bone_segment = v12.bone_segment


def _body_panel(
    name: str,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    predicate,
    *,
    offset: float = 0.020,
    thickness: float = 0.0014,
    bevel_width: float = 0.0,
) -> bpy.types.Object:
    """Copy a fitted source shell without an unbounded bevel miter."""
    if bevel_width != 0.0:
        raise ValueError("The fitted source shell must not use a bevel modifier")
    selected = v12._selected_polygons(body, predicate)
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

    solidify = obj.modifiers.new("Fabric thickness", "SOLIDIFY")
    solidify.thickness = thickness
    solidify.offset = 0.0
    solidify.use_even_offset = True
    v12._move_modifier_before_armature(obj, solidify)
    bpy.ops.object.modifier_apply(modifier=solidify.name)

    triangulate = obj.modifiers.new("Export triangulation", "TRIANGULATE")
    v12._move_modifier_before_armature(obj, triangulate)
    bpy.ops.object.modifier_apply(modifier=triangulate.name)
    mesh.validate(verbose=False, clean_customdata=False)
    mesh.update(calc_edges=True)
    obj.select_set(False)
    return obj


def _crotch_bridge(
    sampler,
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
    return v12.v9._grid_object(
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


def _validate_geometry(objects: list[bpy.types.Object]) -> None:
    """Reject non-finite or metre-scale miter edges before save/export."""
    failures: list[str] = []
    for obj in objects:
        if obj.type != "MESH":
            continue
        vertices = obj.data.vertices
        for vertex in vertices:
            coordinate = vertex.co
            if not all(math.isfinite(value) for value in coordinate):
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


v12._body_panel = _body_panel
v12._crotch_bridge = _crotch_bridge


def create_outfit(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    fabric: bpy.types.Material,
    trim: bpy.types.Material,
    button_material: bpy.types.Material,
) -> list[bpy.types.Object]:
    garments = v12.create_outfit(body, armature, fabric, trim, button_material)
    _validate_geometry(garments)
    return garments
