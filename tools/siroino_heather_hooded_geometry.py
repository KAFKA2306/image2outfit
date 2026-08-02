#!/usr/bin/env python3
"""Editable garment geometry for the Siroino heather hooded bodysuit."""
from __future__ import annotations

import math
from typing import Iterable

import bmesh
import bpy
from mathutils import Vector

import siroino_strappy_knit_build as base


def bone_segment(armature: bpy.types.Object, name: str) -> tuple[Vector, Vector]:
    bone = armature.data.bones.get(name)
    if bone is None:
        raise RuntimeError(f"Required Siroino bone missing: {name}")
    return armature.matrix_world @ bone.head_local, armature.matrix_world @ bone.tail_local


def near_segment(point: Vector, start: Vector, end: Vector, t0: float, t1: float, radius: float) -> bool:
    direction = end - start
    length_squared = direction.length_squared
    if length_squared <= 1e-12:
        return False
    t = (point - start).dot(direction) / length_squared
    return t0 <= t <= t1 and (point - (start + direction * t)).length <= radius


def rounded_box(name, center, scale, material, armature, group, bevel=0.0015):
    bpy.ops.mesh.primitive_cube_add(location=center, scale=scale)
    obj = bpy.context.active_object
    obj.name = name
    obj.data.materials.append(material)
    modifier = obj.modifiers.new("Soft fabric edge", "BEVEL")
    modifier.width = bevel
    modifier.segments = 3
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    base.rigid_mesh_weight(obj, armature, group)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    return obj


def hood_shell(body, armature, material):
    segments_theta, segments_phi = 60, 28
    theta_start, theta_end = -0.10, math.pi + 0.10
    phi_start, phi_end = math.radians(18), math.radians(151)
    center, radii = Vector((0.0, 0.012, 1.165)), Vector((0.115, 0.100, 0.155))
    vertices, faces = [], []
    for j in range(segments_phi + 1):
        phi = phi_start + (phi_end - phi_start) * j / segments_phi
        for i in range(segments_theta + 1):
            theta = theta_start + (theta_end - theta_start) * i / segments_theta
            lower = max(0.0, (j / segments_phi - 0.65) / 0.35)
            vertices.append((
                center.x + radii.x * math.sin(phi) * math.cos(theta),
                center.y + radii.y * math.sin(phi) * math.sin(theta) + 0.030 * lower,
                center.z + radii.z * math.cos(phi) - 0.018 * lower,
            ))
    stride = segments_theta + 1
    for j in range(segments_phi):
        for i in range(segments_theta):
            a = j * stride + i
            faces.append((a, a + 1, a + stride + 1, a + stride))
    mesh = bpy.data.meshes.new("Heather_Hood_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    uv = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            j, i = divmod(vertex_index, stride)
            uv.data[loop_index].uv = (i / segments_theta, 1.0 - j / segments_phi)
    mesh.materials.append(material)
    obj = bpy.data.objects.new("Heather_Sculpted_Hood", mesh)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    solidify = obj.modifiers.new("Hood fabric thickness", "SOLIDIFY")
    solidify.thickness, solidify.offset, solidify.use_even_offset = 0.0022, 0.0, True
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    bevel = obj.modifiers.new("Hood finished opening", "BEVEL")
    bevel.width, bevel.segments = 0.0010, 2
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    base.transfer_nearest_body_weights(obj, body)
    obj.parent = armature
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object, modifier.use_deform_preserve_volume = armature, True
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    obj.select_set(False)
    return obj


def create_outfit(body, armature, fabric, trim, button_material):
    garments = [
        base.extract_surface(body, armature, "Heather_Front_Upper_Panel", lambda c: 0.775 <= c.z <= 1.040 and c.y < 0.006 and abs(c.x) <= min(0.154, 0.060 + max(0.0, c.z - 0.705) * 0.42), fabric, 0.0080),
        base.extract_surface(body, armature, "Heather_Back_Upper_Panel", lambda c: 0.775 <= c.z <= 1.035 and c.y >= -0.010 and abs(c.x) <= min(0.154, 0.064 + max(0.0, c.z - 0.705) * 0.40), fabric, 0.0080),
        base.extract_surface(body, armature, "Heather_Highcut_Front_Panel", lambda c: 0.575 <= c.z <= 0.800 and c.y < 0.002 and abs(c.x) <= 0.026 + max(0.0, c.z - 0.575) * 0.70, fabric, 0.0075),
        base.extract_surface(body, armature, "Heather_Highcut_Back_Panel", lambda c: 0.565 <= c.z <= 0.800 and c.y >= -0.008 and abs(c.x) <= 0.046 + max(0.0, c.z - 0.565) * 0.56, fabric, 0.0075),
    ]
    for side in ("L", "R"):
        upper_start, upper_end = bone_segment(armature, f"UpperArm_{side}")
        lower_start, lower_end = bone_segment(armature, f"LowerArm_{side}")
        garments.extend([
            base.extract_surface(body, armature, f"Heather_Upper_Sleeve_{side}", lambda c, a=upper_start, b=upper_end: near_segment(c, a, b, 0.00, 1.04, 0.072), fabric, 0.0085),
            base.extract_surface(body, armature, f"Heather_Lower_Sleeve_{side}", lambda c, a=lower_start, b=lower_end: near_segment(c, a, b, -0.04, 1.02, 0.061), fabric, 0.0080),
            base.extract_surface(body, armature, f"Heather_Rib_Cuff_{side}", lambda c, a=lower_start, b=lower_end: near_segment(c, a, b, 0.79, 1.08, 0.058), trim, 0.0090),
        ])
    garments.append(hood_shell(body, armature, fabric))
    front_y = base.body_front_y(body, 0.0, 0.955) - 0.012
    garments.append(rounded_box("Heather_Henley_Placket", (0.0, front_y, 0.970), (0.018, 0.0024, 0.064), trim, armature, "Chest", 0.0012))
    for index, z in enumerate((1.010, 0.970, 0.930), start=1):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=0.0060, location=(0.0, front_y - 0.0040, z))
        button = bpy.context.active_object
        button.name = f"Heather_Henley_Button_{index:02d}"
        button.scale.y = 0.40
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        button.data.materials.append(button_material)
        base.rigid_mesh_weight(button, armature, "Chest")
        garments.append(button)
    cords = []
    for sign, label in ((-1.0, "L"), (1.0, "R")):
        x = sign * 0.032
        cords.append(base.curve_tube(f"Heather_Hood_Drawcord_{label}", [(x, front_y - 0.001, 1.040), (x * 1.08, front_y - 0.004, 0.965), (x * 1.12, front_y - 0.006, 0.885)], 0.00155, trim, armature, "Chest", resolution=3))
        hip_x = sign * 0.132
        hip_y = base.body_front_y(body, hip_x, 0.760) - 0.010
        loop = [(hip_x + sign * 0.020 * math.sin(t), hip_y - 0.006 * math.sin(t) ** 2, 0.760 + 0.015 * math.sin(2.0 * t)) for t in [math.tau * i / 48 for i in range(49)]]
        cords.extend([
            base.curve_tube(f"Heather_Side_Bow_{label}", loop, 0.00145, trim, armature, "Hips", cyclic=True, resolution=3),
            base.curve_tube(f"Heather_Side_Tie_Upper_{label}", [(sign * 0.102, hip_y, 0.778), (hip_x, hip_y - 0.003, 0.760), (hip_x + sign * 0.018, hip_y, 0.707)], 0.00140, trim, armature, "Hips"),
            base.curve_tube(f"Heather_Side_Tie_Lower_{label}", [(hip_x, hip_y - 0.003, 0.760), (hip_x + sign * 0.025, hip_y + 0.001, 0.724), (hip_x + sign * 0.012, hip_y + 0.003, 0.665)], 0.00140, trim, armature, "Hips"),
        ])
    joined_cords = base.join_objects("Heather_Drawcords_And_Side_Ties", cords)
    base.transfer_nearest_body_weights(joined_cords, body)
    garments.append(joined_cords)
    for obj in garments:
        base.add_nearest_shape_keys(obj, body)
    return garments


def clean_meshes(objects: Iterable[bpy.types.Object]) -> None:
    for obj in objects:
        if obj.type != "MESH":
            continue
        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.dissolve_degenerate(bm, dist=1e-8, edges=list(bm.edges))
        zero_faces = [face for face in bm.faces if face.calc_area() <= 1e-12]
        if zero_faces:
            bmesh.ops.delete(bm, geom=zero_faces, context="FACES")
        loose = [vertex for vertex in bm.verts if not vertex.link_faces]
        if loose:
            bmesh.ops.delete(bm, geom=loose, context="VERTS")
        bm.to_mesh(mesh)
        bm.free()
        mesh.update(calc_edges=True)
