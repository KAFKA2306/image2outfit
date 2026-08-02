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


def _ring_frame(points: list[Vector], index: int) -> tuple[Vector, Vector]:
    if index == 0:
        tangent = points[1] - points[0]
    elif index == len(points) - 1:
        tangent = points[-1] - points[-2]
    else:
        tangent = points[index + 1] - points[index - 1]
    tangent.normalize()
    reference = Vector((0.0, 0.0, 1.0))
    if abs(tangent.dot(reference)) > 0.92:
        reference = Vector((0.0, 1.0, 0.0))
    axis_u = tangent.cross(reference).normalized()
    axis_v = tangent.cross(axis_u).normalized()
    return axis_u, axis_v


def weighted_tube(
    name: str,
    points: list[Vector],
    radii: list[float],
    ring_weights: list[dict[str, float]],
    material: bpy.types.Material,
    armature: bpy.types.Object,
    *,
    segments: int = 36,
    thickness: float = 0.0015,
) -> bpy.types.Object:
    if not (len(points) == len(radii) == len(ring_weights)):
        raise ValueError(f"tube ring contract mismatch: {name}")
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    for ring_index, (point, radius) in enumerate(zip(points, radii)):
        axis_u, axis_v = _ring_frame(points, ring_index)
        for segment in range(segments):
            angle = math.tau * segment / segments
            coordinate = point + radius * (
                math.cos(angle) * axis_u + math.sin(angle) * axis_v
            )
            vertices.append(tuple(coordinate))
    for ring_index in range(len(points) - 1):
        for segment in range(segments):
            nxt = (segment + 1) % segments
            a = ring_index * segments + segment
            b = ring_index * segments + nxt
            c = (ring_index + 1) * segments + nxt
            d = (ring_index + 1) * segments + segment
            faces.append((a, b, c, d))
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    uv = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            ring_index, segment = divmod(vertex_index, segments)
            uv.data[loop_index].uv = (
                segment / segments,
                ring_index / max(1, len(points) - 1),
            )
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = armature
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True
    groups = {
        group_name: obj.vertex_groups.new(name=group_name)
        for weights in ring_weights
        for group_name in weights
    }
    for ring_index, weights in enumerate(ring_weights):
        total = sum(weights.values()) or 1.0
        indices = list(range(ring_index * segments, (ring_index + 1) * segments))
        for group_name, weight in weights.items():
            groups[group_name].add(indices, weight / total, "REPLACE")
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    solidify = obj.modifiers.new("Stretch jersey thickness", "SOLIDIFY")
    solidify.thickness = thickness
    solidify.offset = 0.0
    solidify.use_even_offset = True
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    bevel = obj.modifiers.new("Finished sleeve edge", "BEVEL")
    bevel.width = 0.0006
    bevel.segments = 2
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    obj.select_set(False)
    return obj


def sleeve_segments(
    armature: bpy.types.Object,
    side: str,
    fabric: bpy.types.Material,
    trim: bpy.types.Material,
) -> list[bpy.types.Object]:
    upper_start, upper_end = bone_segment(armature, f"UpperArm_{side}")
    lower_start, lower_end = bone_segment(armature, f"LowerArm_{side}")
    upper_direction = upper_end - upper_start
    lower_direction = lower_end - lower_start
    upper_points = [
        upper_start + upper_direction * 0.04,
        upper_start + upper_direction * 0.48,
        upper_start + upper_direction * 0.93,
        upper_end + lower_direction * 0.08,
    ]
    upper_weights = [
        {f"UpperArm_{side}": 1.0},
        {f"UpperArm_{side}": 1.0},
        {f"UpperArm_{side}": 0.82, f"LowerArm_{side}": 0.18},
        {f"UpperArm_{side}": 0.30, f"LowerArm_{side}": 0.70},
    ]
    lower_points = [
        lower_start - lower_direction * 0.05,
        lower_start + lower_direction * 0.36,
        lower_start + lower_direction * 0.76,
        lower_start + lower_direction * 0.94,
    ]
    lower_weights = [
        {f"UpperArm_{side}": 0.18, f"LowerArm_{side}": 0.82},
        {f"LowerArm_{side}": 1.0},
        {f"LowerArm_{side}": 1.0},
        {f"LowerArm_{side}": 1.0},
    ]
    cuff_points = [
        lower_start + lower_direction * 0.80,
        lower_start + lower_direction * 0.94,
        lower_end + lower_direction * 0.02,
    ]
    cuff_weights = [{f"LowerArm_{side}": 1.0}] * 3
    return [
        weighted_tube(
            f"Heather_Upper_Sleeve_{side}",
            upper_points,
            [0.052, 0.049, 0.045, 0.044],
            upper_weights,
            fabric,
            armature,
        ),
        weighted_tube(
            f"Heather_Lower_Sleeve_{side}",
            lower_points,
            [0.046, 0.041, 0.036, 0.034],
            lower_weights,
            fabric,
            armature,
        ),
        weighted_tube(
            f"Heather_Rib_Cuff_{side}",
            cuff_points,
            [0.037, 0.035, 0.034],
            cuff_weights,
            trim,
            armature,
            segments=32,
            thickness=0.0018,
        ),
    ]


def hood_shell(armature: bpy.types.Object, material: bpy.types.Material) -> bpy.types.Object:
    segments = 56
    rings = [
        (1.016, 0.056, 0.018, 0.030),
        (1.054, 0.095, 0.030, 0.050),
        (1.098, 0.104, 0.050, 0.070),
        (1.138, 0.078, 0.064, 0.058),
    ]
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    for z, radius_x, center_y, radius_y in rings:
        for segment in range(segments + 1):
            angle = math.pi * segment / segments
            x = radius_x * math.cos(angle)
            y = center_y + radius_y * math.sin(angle)
            vertices.append((x, y, z))
    stride = segments + 1
    for ring_index in range(len(rings) - 1):
        for segment in range(segments):
            a = ring_index * stride + segment
            faces.append((a, a + 1, a + stride + 1, a + stride))
    mesh = bpy.data.meshes.new("Heather_Hood_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    uv = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            ring_index, segment = divmod(vertex_index, stride)
            uv.data[loop_index].uv = (
                segment / segments,
                ring_index / (len(rings) - 1),
            )
    mesh.materials.append(material)
    obj = bpy.data.objects.new("Heather_Folded_Hood", mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = armature
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True
    neck = obj.vertex_groups.new(name="Neck")
    chest = obj.vertex_groups.new(name="Chest")
    for ring_index in range(len(rings)):
        indices = list(range(ring_index * stride, (ring_index + 1) * stride))
        neck_weight = 0.42 + 0.16 * ring_index
        neck.add(indices, neck_weight, "REPLACE")
        chest.add(indices, 1.0 - neck_weight, "REPLACE")
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    solidify = obj.modifiers.new("Hood fabric thickness", "SOLIDIFY")
    solidify.thickness = 0.0020
    solidify.offset = 0.0
    solidify.use_even_offset = True
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    bevel = obj.modifiers.new("Hood finished opening", "BEVEL")
    bevel.width = 0.0009
    bevel.segments = 2
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    obj.select_set(False)
    return obj


def neckline_binding(
    armature: bpy.types.Object,
    trim: bpy.types.Material,
) -> bpy.types.Object:
    points = []
    for index in range(65):
        angle = math.tau * index / 64
        points.append((
            0.057 * math.cos(angle),
            -0.002 + 0.039 * math.sin(angle),
            1.025 + 0.004 * math.cos(angle),
        ))
    return base.curve_tube(
        "Heather_Hood_Neck_Binding",
        points,
        0.0021,
        trim,
        armature,
        "Neck",
        cyclic=True,
        resolution=3,
    )


def create_outfit(body, armature, fabric, trim, button_material):
    garments = [
        base.extract_surface(
            body,
            armature,
            "Heather_Front_Upper_Panel",
            lambda c: 0.770 <= c.z <= 1.045
            and c.y < 0.006
            and abs(c.x) <= min(
                0.150,
                0.058 + max(0.0, c.z - 0.700) * 0.40,
            ),
            fabric,
            0.0080,
        ),
        base.extract_surface(
            body,
            armature,
            "Heather_Back_Upper_Panel",
            lambda c: 0.770 <= c.z <= 1.040
            and c.y >= -0.010
            and abs(c.x) <= min(
                0.150,
                0.062 + max(0.0, c.z - 0.700) * 0.38,
            ),
            fabric,
            0.0080,
        ),
        base.extract_surface(
            body,
            armature,
            "Heather_Highcut_Front_Panel",
            lambda c: 0.575 <= c.z <= 0.790
            and c.y < 0.002
            and abs(c.x) <= 0.025 + max(0.0, c.z - 0.575) * 0.31,
            fabric,
            0.0075,
        ),
        base.extract_surface(
            body,
            armature,
            "Heather_Highcut_Back_Panel",
            lambda c: 0.565 <= c.z <= 0.790
            and c.y >= -0.008
            and abs(c.x) <= 0.038 + max(0.0, c.z - 0.565) * 0.27,
            fabric,
            0.0075,
        ),
    ]
    for side in ("L", "R"):
        garments.extend(sleeve_segments(armature, side, fabric, trim))
    garments.extend([hood_shell(armature, fabric), neckline_binding(armature, trim)])

    front_y = base.body_front_y(body, 0.0, 0.970) - 0.012
    garments.append(
        rounded_box(
            "Heather_Henley_Placket",
            (0.0, front_y, 0.982),
            (0.0125, 0.0020, 0.045),
            trim,
            armature,
            "Chest",
            0.0010,
        )
    )
    for index, z in enumerate((1.012, 0.982, 0.952), start=1):
        bpy.ops.mesh.primitive_uv_sphere_add(
            segments=20,
            ring_count=10,
            radius=0.0042,
            location=(0.0, front_y - 0.0032, z),
        )
        button = bpy.context.active_object
        button.name = f"Heather_Henley_Button_{index:02d}"
        button.scale.y = 0.38
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        button.data.materials.append(button_material)
        base.rigid_mesh_weight(button, armature, "Chest")
        garments.append(button)

    cords = []
    for sign, label in ((-1.0, "L"), (1.0, "R")):
        x = sign * 0.031
        cords.append(
            base.curve_tube(
                f"Heather_Hood_Drawcord_{label}",
                [
                    (x, front_y - 0.001, 1.030),
                    (x * 1.08, front_y - 0.004, 0.975),
                    (x * 1.12, front_y - 0.006, 0.915),
                ],
                0.00135,
                trim,
                armature,
                "Chest",
                resolution=3,
            )
        )
        hip_x = sign * 0.118
        hip_y = base.body_front_y(body, hip_x, 0.760) - 0.010
        loop = [
            (
                hip_x + sign * 0.017 * math.sin(t),
                hip_y - 0.005 * math.sin(t) ** 2,
                0.760 + 0.013 * math.sin(2.0 * t),
            )
            for t in [math.tau * index / 48 for index in range(49)]
        ]
        cords.extend(
            [
                base.curve_tube(
                    f"Heather_Side_Bow_{label}",
                    loop,
                    0.00125,
                    trim,
                    armature,
                    "Hips",
                    cyclic=True,
                    resolution=3,
                ),
                base.curve_tube(
                    f"Heather_Side_Tie_Upper_{label}",
                    [
                        (sign * 0.092, hip_y, 0.779),
                        (hip_x, hip_y - 0.003, 0.760),
                        (hip_x + sign * 0.016, hip_y, 0.713),
                    ],
                    0.00125,
                    trim,
                    armature,
                    "Hips",
                ),
                base.curve_tube(
                    f"Heather_Side_Tie_Lower_{label}",
                    [
                        (hip_x, hip_y - 0.003, 0.760),
                        (hip_x + sign * 0.021, hip_y + 0.001, 0.727),
                        (hip_x + sign * 0.010, hip_y + 0.003, 0.682),
                    ],
                    0.00125,
                    trim,
                    armature,
                    "Hips",
                ),
            ]
        )
    joined_cords = base.join_objects("Heather_Drawcords_And_Side_Ties", cords)
    base.transfer_nearest_body_weights(joined_cords, body)
    garments.append(joined_cords)
    return garments


def clean_meshes(objects: Iterable[bpy.types.Object]) -> dict[str, int]:
    removed: dict[str, int] = {}
    for obj in objects:
        if obj.type != "MESH":
            continue
        mesh = obj.data
        before = len(mesh.polygons)
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-7)
        bmesh.ops.dissolve_degenerate(bm, dist=1e-7, edges=list(bm.edges))
        for _ in range(3):
            zero_faces = [face for face in bm.faces if face.calc_area() <= 1e-10]
            if not zero_faces:
                break
            bmesh.ops.delete(bm, geom=zero_faces, context="FACES")
        loose = [vertex for vertex in bm.verts if not vertex.link_faces]
        if loose:
            bmesh.ops.delete(bm, geom=loose, context="VERTS")
        if bm.faces:
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(mesh)
        bm.free()
        mesh.update(calc_edges=True)
        mesh.calc_loop_triangles()
        degenerate_polygons = {
            triangle.polygon_index
            for triangle in mesh.loop_triangles
            if (
                (
                    mesh.vertices[triangle.vertices[1]].co
                    - mesh.vertices[triangle.vertices[0]].co
                )
                .cross(
                    mesh.vertices[triangle.vertices[2]].co
                    - mesh.vertices[triangle.vertices[0]].co
                )
                .length_squared
                <= 1e-18
            )
        }
        if degenerate_polygons:
            cleanup = bmesh.new()
            cleanup.from_mesh(mesh)
            cleanup.faces.ensure_lookup_table()
            doomed = [
                cleanup.faces[index]
                for index in sorted(degenerate_polygons)
                if index < len(cleanup.faces)
            ]
            if doomed:
                bmesh.ops.delete(cleanup, geom=doomed, context="FACES")
            loose = [vertex for vertex in cleanup.verts if not vertex.link_faces]
            if loose:
                bmesh.ops.delete(cleanup, geom=loose, context="VERTS")
            cleanup.to_mesh(mesh)
            cleanup.free()
            mesh.update(calc_edges=True)
        removed[obj.name] = max(0, before - len(mesh.polygons))
    return removed
