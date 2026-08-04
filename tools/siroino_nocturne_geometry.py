"""Geometry, skinning, and cloth primitives for the Nocturne Angel set."""
from __future__ import annotations

from pathlib import Path
import sys

import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import siroino_strappy_knit_build as base

BONES = {
    "head": ("Head", "J_Bip_C_Head"),
    "neck": ("Neck", "J_Bip_C_Neck"),
    "chest": ("Chest", "UpperChest", "J_Bip_C_Chest"),
    "upper_arm_l": ("UpperArm_L", "LeftUpperArm"),
    "upper_arm_r": ("UpperArm_R", "RightUpperArm"),
    "lower_arm_l": ("LowerArm_L", "LeftLowerArm"),
    "lower_arm_r": ("LowerArm_R", "RightLowerArm"),
    "upper_leg_l": ("UpperLeg_L", "LeftUpperLeg"),
    "upper_leg_r": ("UpperLeg_R", "RightUpperLeg"),
    "lower_leg_l": ("LowerLeg_L", "LeftLowerLeg"),
    "lower_leg_r": ("LowerLeg_R", "RightLowerLeg"),
}


def bounds(body):
    points = [body.matrix_world @ vertex.co for vertex in body.data.vertices]
    return (
        Vector(tuple(min(point[index] for point in points) for index in range(3))),
        Vector(tuple(max(point[index] for point in points) for index in range(3))),
    )


def bone_segment(armature, semantic):
    aliases = BONES[semantic]
    bone = next(
        (
            armature.data.bones.get(name)
            for name in aliases
            if armature.data.bones.get(name)
        ),
        None,
    )
    if bone is None:
        raise RuntimeError(f"missing Siroino bone: {semantic}")
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


def cone(
    name, location, radius1, radius2, depth, mat, *, end_fill_type="NGON"
):
    bpy.ops.mesh.primitive_cone_add(
        vertices=64,
        radius1=radius1,
        radius2=radius2,
        depth=depth,
        location=location,
        end_fill_type=end_fill_type,
    )
    obj = finish(bpy.context.object, mat)
    obj.name = name
    return obj


def cube(name, location, scale, mat, rotation=(0.0, 0.0, 0.0)):
    bpy.ops.mesh.primitive_cube_add(location=location, rotation=rotation)
    obj = finish(bpy.context.object, mat)
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bevel = obj.modifiers.new("Finished edges", "BEVEL")
    bevel.width = min(scale) * 0.15
    bevel.segments = 2
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    return obj


def tube(name, start, end, radius_start, radius_end, mat):
    axis = end - start
    obj = cone(
        name,
        (start + end) * 0.5,
        radius_end,
        radius_start,
        axis.length,
        mat,
    )
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = Vector((0.0, 0.0, 1.0)).rotation_difference(
        axis.normalized()
    )
    return obj


def panel(name, points, mat, thickness):
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(points, [], [tuple(range(len(points)))])
    mesh.materials.append(mat)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    modifier = obj.modifiers.new("Panel thickness", "SOLIDIFY")
    modifier.thickness = thickness
    modifier.offset = 0.0
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    obj.select_set(False)
    obj["image2outfit_role"] = "garment"
    return obj


def transfer_weights(obj, body, armature):
    tree = KDTree(len(body.data.vertices))
    for vertex in body.data.vertices:
        tree.insert(body.matrix_world @ vertex.co, vertex.index)
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
    world = obj.matrix_world.copy()
    obj.parent = armature
    obj.matrix_world = world
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True


def bake_skirt(skirt, body):
    top = max(vertex.co.z for vertex in skirt.data.vertices)
    pinned = [
        vertex.index
        for vertex in skirt.data.vertices
        if abs(vertex.co.z - top) < 1e-5
    ]
    group = skirt.vertex_groups.new(name="Cloth_Pin")
    group.add(pinned, 1.0, "REPLACE")
    try:
        body.modifiers.new("Nocturne body collision", "COLLISION")
    except RuntimeError:
        pass
    cloth = skirt.modifiers.new("Nocturne cloth simulation", "CLOTH")
    cloth.settings.quality = 6
    cloth.settings.mass = 0.24
    cloth.settings.vertex_group_mass = group.name
    cloth.collision_settings.use_collision = True
    cloth.collision_settings.distance_min = 0.004
    cloth.collision_settings.use_self_collision = True
    cloth.collision_settings.self_distance_min = 0.004
    scene = bpy.context.scene
    scene.frame_end = 24
    for frame in range(1, 25):
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
    scene.frame_set(1)
    skirt["clothSimulationFrames"] = 24
    return {
        "object": skirt.name,
        "frames": 24,
        "pinVertices": len(pinned),
        "bodyCollision": True,
        "selfCollision": True,
        "baked": True,
    }
