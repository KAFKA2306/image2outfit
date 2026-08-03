#!/usr/bin/env python3
"""Body-topology v10 pattern for the Siroino heather hooded bodysuit.

The v9 interpolated grids produced disconnected shoulder, waist and crotch edges.
This revision derives the torso and high-cut panels from the tracked
SiroinoSotai_PC body topology, retaining source UVs and skin weights.
"""
from __future__ import annotations

from collections.abc import Callable

import bpy
from mathutils import Vector

import siroino_heather_hooded_pattern as v9

# Preserve the geometry-module interface expected by the generic product build.
clean_meshes = v9.clean_meshes
bone_segment = v9.bone_segment


def _body_panel(
    name: str,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    predicate: Callable[[Vector], bool],
    *,
    offset: float = 0.008,
) -> bpy.types.Object:
    selected = [
        polygon
        for polygon in body.data.polygons
        if predicate(body.matrix_world @ polygon.center)
    ]
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
                        [new_index], float(item.weight) / total, "REPLACE"
                    )

    for polygon in mesh.polygons:
        polygon.use_smooth = True

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    solidify = obj.modifiers.new("Fabric thickness", "SOLIDIFY")
    solidify.thickness = 0.0012
    solidify.offset = 1.0
    solidify.use_even_offset = True
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    bevel = obj.modifiers.new("Finished edge", "BEVEL")
    bevel.width = 0.00025
    bevel.segments = 2
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    obj.select_set(False)
    return obj


def _panel_predicate(front: bool) -> Callable[[Vector], bool]:
    def selected(point: Vector) -> bool:
        side_ok = point.y <= 0.0 if front else point.y >= 0.0
        if not side_ok:
            return False
        torso = 0.795 <= point.z <= 1.035 and abs(point.x) <= 0.215
        if 0.650 <= point.z < 0.795:
            t = (point.z - 0.650) / 0.145
            half_width = 0.020 + 0.145 * max(0.0, min(1.0, t)) ** 1.35
            highcut = abs(point.x) <= half_width
        else:
            highcut = False
        return torso or highcut

    return selected


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
    garments.extend(v9._sleeves_and_cuffs(body, armature, fabric, trim))
    garments.extend(
        [
            v9._hood_half(body, armature, fabric, "L"),
            v9._hood_half(body, armature, fabric, "R"),
            v9._neck_band(body, armature, fabric),
        ]
    )
    garments.extend(v9._placket_and_buttons(sampler, armature, trim, button_material))
    garments.extend(v9._cords_ties_seams(sampler, armature, trim))
    return garments
