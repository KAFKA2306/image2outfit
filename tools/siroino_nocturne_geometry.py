"""Geometry, skinning, and cloth primitives for the Nocturne Angel set."""

from __future__ import annotations

import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import siroino_strappy_knit_build as base

BONES = {
    "head": ("Head", "J_Bip_C_Head"),
    "neck": ("Neck", "J_Bip_C_Neck"),
    "chest": ("Chest", "UpperChest", "J_Bip_C_Chest"),
    "hips": ("Hips", "J_Bip_C_Hips"),
    "upper_arm_l": ("UpperArm_L", "LeftUpperArm"),
    "upper_arm_r": ("UpperArm_R", "RightUpperArm"),
    "lower_arm_l": ("LowerArm_L", "LeftLowerArm"),
    "lower_arm_r": ("LowerArm_R", "RightLowerArm"),
    "upper_leg_l": ("UpperLeg_L", "LeftUpperLeg"),
    "upper_leg_r": ("UpperLeg_R", "RightUpperLeg"),
    "lower_leg_l": ("LowerLeg_L", "LeftLowerLeg"),
    "lower_leg_r": ("LowerLeg_R", "RightLowerLeg"),
    "foot_l": ("Foot_L", "LeftFoot"),
    "foot_r": ("Foot_R", "RightFoot"),
}


def bounds(body):
    points = [body.matrix_world @ vertex.co for vertex in body.data.vertices]
    return (
        Vector(tuple(min(point[index] for point in points) for index in range(3))),
        Vector(tuple(max(point[index] for point in points) for index in range(3))),
    )


def resolve_bone_name(armature, semantic):
    for name in BONES[semantic]:
        if armature.data.bones.get(name) is not None:
            return name
    raise RuntimeError(f"missing Siroino bone: {semantic}")


def bone_segment(armature, semantic):
    bone = armature.data.bones[resolve_bone_name(armature, semantic)]
    return (
        armature.matrix_world @ bone.head_local,
        armature.matrix_world @ bone.tail_local,
    )


def material(name, colour, roughness, metallic=0.0):
    return base.plain_material(
        name,
        (*colour, 1.0),
        roughness=roughness,
        metallic=metallic,
    )


def finish(obj, mat):
    obj.data.materials.append(mat)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    obj["image2outfit_role"] = "garment"
    return obj


def _cylindrical_uv(mesh, segments, rings):
    uv = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            ring_index, segment_index = divmod(vertex_index, segments)
            uv.data[loop_index].uv = (
                segment_index / segments,
                ring_index / max(1, rings - 1),
            )


def sphere(name, location, scale, mat, rotation=(0.0, 0.0, 0.0)):
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=32,
        ring_count=16,
        location=location,
        rotation=rotation,
    )
    obj = finish(bpy.context.object, mat)
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return obj


def ellipsoid_between(name, root, tip, width, depth, mat):
    axis = tip - root
    length = axis.length
    if length <= 1e-8:
        raise ValueError("ellipsoid endpoints must be distinct")
    obj = sphere(
        name,
        root.lerp(tip, 0.5),
        (width, depth, length * 0.5),
        mat,
    )
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = Vector((0.0, 0.0, 1.0)).rotation_difference(
        axis.normalized()
    )
    return obj


def frustum_shell(name, center, rings, mat, *, segments=64, scallops=0):
    """Create an open multi-ring elliptical garment shell."""
    vertices = []
    for ring_index, (z, radius_x, radius_y, y_offset) in enumerate(rings):
        for segment in range(segments):
            angle = math.tau * segment / segments
            wave = 1.0
            if scallops and ring_index == 0:
                wave += 0.035 * math.sin(scallops * angle)
            vertices.append(
                (
                    center.x + radius_x * wave * math.cos(angle),
                    center.y + y_offset + radius_y * wave * math.sin(angle),
                    z,
                )
            )
    faces = []
    for ring_index in range(len(rings) - 1):
        for segment in range(segments):
            next_segment = (segment + 1) % segments
            first = ring_index * segments + segment
            second = ring_index * segments + next_segment
            third = (ring_index + 1) * segments + next_segment
            fourth = (ring_index + 1) * segments + segment
            faces.append((first, second, third, fourth))
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    _cylindrical_uv(mesh, segments, len(rings))
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return finish(obj, mat)


def pleated_shell(
    name,
    center,
    rings,
    mat,
    *,
    segments=96,
    pleats=12,
    fold=0.075,
):
    """Create a short A-line shell with radial pleats strongest at the hem."""
    vertices = []
    ring_count = len(rings)
    for ring_index, (z, radius_x, radius_y, y_offset) in enumerate(rings):
        hem_fraction = 1.0 - ring_index / max(1, ring_count - 1)
        for segment in range(segments):
            angle = math.tau * segment / segments
            wave = 1.0 + fold * hem_fraction * math.cos(pleats * angle)
            vertices.append(
                (
                    center.x + radius_x * wave * math.cos(angle),
                    center.y + y_offset + radius_y * wave * math.sin(angle),
                    z,
                )
            )
    faces = []
    for ring_index in range(ring_count - 1):
        for segment in range(segments):
            next_segment = (segment + 1) % segments
            first = ring_index * segments + segment
            second = ring_index * segments + next_segment
            third = (ring_index + 1) * segments + next_segment
            fourth = (ring_index + 1) * segments + segment
            faces.append((first, second, third, fourth))
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    _cylindrical_uv(mesh, segments, ring_count)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj["pleatCount"] = pleats
    obj["pleatFold"] = fold
    return finish(obj, mat)


def axis_shell(name, start, end, radii, mat, *, segments=40):
    """Create an open sleeve-like shell around an arbitrary bone segment."""
    axis = end - start
    direction = axis.normalized()
    reference = Vector((0.0, 0.0, 1.0))
    if abs(direction.dot(reference)) > 0.92:
        reference = Vector((1.0, 0.0, 0.0))
    first_basis = direction.cross(reference).normalized()
    second_basis = direction.cross(first_basis).normalized()
    vertices = []
    for ring_index, radius in enumerate(radii):
        t = ring_index / max(1, len(radii) - 1)
        center = start.lerp(end, t)
        for segment in range(segments):
            angle = math.tau * segment / segments
            vertices.append(
                center
                + first_basis * radius * math.cos(angle)
                + second_basis * radius * math.sin(angle)
            )
    faces = []
    for ring_index in range(len(radii) - 1):
        for segment in range(segments):
            next_segment = (segment + 1) % segments
            first = ring_index * segments + segment
            second = ring_index * segments + next_segment
            third = (ring_index + 1) * segments + next_segment
            fourth = (ring_index + 1) * segments + segment
            faces.append((first, second, third, fourth))
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    _cylindrical_uv(mesh, segments, len(radii))
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return finish(obj, mat)


def _apply_modifier(obj, name):
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=name)
    obj.select_set(False)


def triangulate(obj):
    modifier = obj.modifiers.new("Explicit triangle export", "TRIANGULATE")
    modifier.quad_method = "BEAUTY"
    modifier.ngon_method = "BEAUTY"
    _apply_modifier(obj, modifier.name)
    return obj


def panel(name, points, mat, thickness):
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(points, [], [tuple(range(len(points)))])
    mesh.materials.append(mat)
    uv = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for order, loop_index in enumerate(polygon.loop_indices):
            uv.data[loop_index].uv = (
                1.0 if order in (1, 2) else 0.0,
                1.0 if order in (2, 3) else 0.0,
            )
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    modifier = obj.modifiers.new("Panel thickness", "SOLIDIFY")
    modifier.thickness = thickness
    modifier.offset = 0.0
    _apply_modifier(obj, modifier.name)
    triangulate(obj)
    obj["image2outfit_role"] = "garment"
    return obj


def _parent_with_armature(obj, armature):
    world = obj.matrix_world.copy()
    obj.parent = armature
    obj.matrix_world = world
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True


def rigid_weight(obj, armature, semantic):
    group_name = resolve_bone_name(armature, semantic)
    group = obj.vertex_groups.new(name=group_name)
    group.add(range(len(obj.data.vertices)), 1.0, "REPLACE")
    _parent_with_armature(obj, armature)


def transfer_weights(obj, body, armature):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = body.evaluated_get(depsgraph)
    evaluated_mesh = evaluated.to_mesh()
    try:
        tree = KDTree(len(evaluated_mesh.vertices))
        for vertex in evaluated_mesh.vertices:
            tree.insert(evaluated.matrix_world @ vertex.co, vertex.index)
        tree.balance()
        groups = {
            group.name: obj.vertex_groups.new(name=group.name)
            for group in body.vertex_groups
        }
        for vertex in obj.data.vertices:
            _, index, _ = tree.find(obj.matrix_world @ vertex.co)
            source = body.data.vertices[index]
            weights = sorted(
                (
                    (body.vertex_groups[item.group].name, item.weight)
                    for item in source.groups
                    if item.weight > 1e-8
                ),
                key=lambda item: item[1],
                reverse=True,
            )[:4]
            if not weights:
                fallback = "Hips" if "Hips" in groups else next(iter(groups))
                weights = [(fallback, 1.0)]
            total = sum(value for _, value in weights) or 1.0
            for group, value in weights:
                groups[group].add([vertex.index], value / total, "REPLACE")
        _parent_with_armature(obj, armature)
    finally:
        evaluated.to_mesh_clear()


def enforce_body_clearance(
    obj,
    body,
    clearance,
    *,
    only_above=None,
    maximum_search=None,
):
    """Project under-clearance vertices outward without copying body topology."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = body.evaluated_get(depsgraph)
    body_mesh = evaluated.to_mesh()
    try:
        body_vertices = [
            evaluated.matrix_world @ vertex.co for vertex in body_mesh.vertices
        ]
        polygons = [tuple(polygon.vertices) for polygon in body_mesh.polygons]
        tree = BVHTree.FromPolygons(body_vertices, polygons, all_triangles=False)
        body_center = sum(body_vertices, Vector()) / max(1, len(body_vertices))
        inverse = obj.matrix_world.inverted()
        moved = 0
        maximum_move = 0.0
        for vertex in obj.data.vertices:
            world = obj.matrix_world @ vertex.co
            if only_above is not None and world.z < only_above:
                continue
            nearest = tree.find_nearest(world)
            if nearest is None:
                continue
            location, normal, _, distance = nearest
            outward = location - body_center
            if normal.dot(outward) < 0.0:
                normal = -normal
            signed = (world - location).dot(normal)
            if signed >= clearance:
                continue
            if (
                maximum_search is not None
                and distance > maximum_search
                and signed >= 0.0
            ):
                continue
            corrected = location + normal * clearance
            move = (corrected - world).length
            vertex.co = inverse @ corrected
            moved += 1
            maximum_move = max(maximum_move, move)
        obj.data.update(calc_edges=True)
        return {
            "object": obj.name,
            "movedVertices": moved,
            "maximumMove": maximum_move,
            "clearance": clearance,
            "onlyAbove": only_above,
        }
    finally:
        evaluated.to_mesh_clear()


def _set_if_available(settings, name, value):
    if hasattr(settings, name):
        setattr(settings, name, value)


def bake_skirt(skirt, body):
    top = max(vertex.co.z for vertex in skirt.data.vertices)
    pinned = [
        vertex.index for vertex in skirt.data.vertices if abs(vertex.co.z - top) < 1e-5
    ]
    group = skirt.vertex_groups.new(name="Cloth_Pin")
    group.add(pinned, 1.0, "REPLACE")
    try:
        body.modifiers.new("Nocturne body collision", "COLLISION")
    except RuntimeError:
        pass
    cloth = skirt.modifiers.new("Nocturne cloth simulation", "CLOTH")
    cloth.settings.quality = 8
    cloth.settings.mass = 0.16
    cloth.settings.vertex_group_mass = group.name
    _set_if_available(cloth.settings, "tension_stiffness", 28.0)
    _set_if_available(cloth.settings, "compression_stiffness", 28.0)
    _set_if_available(cloth.settings, "shear_stiffness", 18.0)
    _set_if_available(cloth.settings, "bending_stiffness", 4.0)
    _set_if_available(cloth.settings, "air_damping", 4.0)
    if hasattr(cloth.settings, "effector_weights"):
        cloth.settings.effector_weights.gravity = 0.18
    cloth.collision_settings.use_collision = True
    cloth.collision_settings.distance_min = 0.004
    cloth.collision_settings.use_self_collision = True
    cloth.collision_settings.self_distance_min = 0.004
    scene = bpy.context.scene
    scene.frame_end = 32
    for frame in range(1, 33):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = skirt.evaluated_get(depsgraph)
    baked = bpy.data.meshes.new_from_object(
        evaluated,
        preserve_all_data_layers=True,
        depsgraph=depsgraph,
    )
    previous = skirt.data
    skirt.data = baked
    bpy.data.meshes.remove(previous)
    skirt.modifiers.clear()
    pin_group = skirt.vertex_groups.get("Cloth_Pin")
    if pin_group is not None:
        skirt.vertex_groups.remove(pin_group)
    scene.frame_set(1)
    skirt["clothSimulationFrames"] = 32
    return {
        "object": skirt.name,
        "frames": 32,
        "pinVertices": len(pinned),
        "bodyCollision": True,
        "selfCollision": True,
        "gravityWeight": 0.18,
        "shapePreservingStiffness": True,
        "baked": True,
    }
