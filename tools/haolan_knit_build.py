import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


args = sys.argv[sys.argv.index("--") + 1 :]
job_path = Path(args[args.index("--job") + 1]).resolve()
job = json.loads(job_path.read_text(encoding="utf-8"))
root = job_path.parents[4]


def resolve(value):
    path = Path(value)
    return path if path.is_absolute() else root / path


def material(name, color, metallic=0.0, roughness=0.62):
    result = bpy.data.materials.new(name)
    result.diffuse_color = (*color, 1.0)
    result.use_nodes = True
    nodes = result.node_tree.nodes
    nodes.clear()
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    output = nodes.new("ShaderNodeOutputMaterial")
    result.node_tree.links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    shader.inputs["Base Color"].default_value = (*color, 1.0)
    shader.inputs["Metallic"].default_value = metallic
    shader.inputs["Roughness"].default_value = roughness
    return result


def weights_for_torso(point, bones):
    z = point.z
    if z < bones["hips"].z:
        return [("Hips", 1.0)]
    if z < bones["spine"].z:
        t = (z - bones["hips"].z) / (bones["spine"].z - bones["hips"].z)
        return [("Hips", 1.0 - t), ("Spine", t)]
    if z < bones["chest"].z:
        t = (z - bones["spine"].z) / (bones["chest"].z - bones["spine"].z)
        return [("Spine", 1.0 - t), ("Chest", t)]
    if z < bones["neck"].z:
        t = (z - bones["chest"].z) / (bones["neck"].z - bones["chest"].z)
        return [("Chest", 1.0 - t), ("Neck", t)]
    return [("Neck", 1.0)]


def weights_for_hip(point, bones):
    side = "L" if point.x >= 0.0 else "R"
    return [("Hips", 0.62), (f"UpperLeg_{side}", 0.38)]


def weights_for_leg(point, bones, side):
    return [(f"UpperLeg_{side}", 1.0)]


def weights_for_arm(point, bones, side):
    upper = bones[f"upper_arm_{side}"]
    lower = bones[f"lower_arm_{side}"]
    axis = lower - upper
    t = max(0.0, min(1.0, (point - upper).dot(axis) / axis.length_squared))
    return [(f"UpperArm_{side}", 1.0 - t), (f"LowerArm_{side}", t)]


def create_mesh(name, vertices, faces, armature, weight_function, mat):
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = armature
    obj.matrix_parent_inverse = Matrix.Identity(4)
    obj.data.materials.append(mat)
    group_cache = {}
    for vertex in mesh.vertices:
        for bone_name, weight in weight_function(vertex.co):
            group = group_cache.get(bone_name)
            if group is None:
                group = obj.vertex_groups.new(name=bone_name)
                group_cache[bone_name] = group
            group.add([vertex.index], weight, "REPLACE")
    modifier = obj.modifiers.new("Armature", "ARMATURE")
    modifier.object = armature
    return obj


def ring_mesh(name, z_values, rx_values, ry_values, center_x, center_y, segments, rib, armature, weight_function, mat):
    vertices = []
    faces = []
    for ring_index, z in enumerate(z_values):
        t = ring_index / (len(z_values) - 1)
        rx = rx_values[0] * (1.0 - t) + rx_values[1] * t
        ry = ry_values[0] * (1.0 - t) + ry_values[1] * t
        for segment in range(segments):
            angle = 2.0 * math.pi * segment / segments
            rib_factor = 1.0 + rib * math.cos(32.0 * angle)
            vertices.append(
                (
                    center_x + rx * rib_factor * math.cos(angle),
                    center_y + ry * rib_factor * math.sin(angle),
                    z,
                )
            )
    for ring_index in range(len(z_values) - 1):
        for segment in range(segments):
            next_segment = (segment + 1) % segments
            a = ring_index * segments + segment
            b = ring_index * segments + next_segment
            c = (ring_index + 1) * segments + next_segment
            d = (ring_index + 1) * segments + segment
            faces.append((a, b, c, d))
    bottom_center = len(vertices)
    vertices.append((center_x, center_y, z_values[0]))
    top_center = len(vertices)
    vertices.append((center_x, center_y, z_values[-1]))
    for segment in range(segments):
        next_segment = (segment + 1) % segments
        faces.append((bottom_center, next_segment, segment))
        top = (len(z_values) - 1) * segments
        faces.append((top_center, top + segment, top + next_segment))
    return create_mesh(name, vertices, faces, armature, weight_function, mat)


def tube_between(name, start, end, radius_start, radius_end, segments, rings, armature, weight_function, mat):
    axis = (end - start).normalized()
    reference = Vector((0.0, 0.0, 1.0)) if abs(axis.z) < 0.9 else Vector((0.0, 1.0, 0.0))
    side = axis.cross(reference).normalized()
    up = axis.cross(side).normalized()
    vertices = []
    faces = []
    for ring_index in range(rings + 1):
        t = ring_index / rings
        center = start.lerp(end, t)
        radius = radius_start * (1.0 - t) + radius_end * t
        for segment in range(segments):
            angle = 2.0 * math.pi * segment / segments
            vertices.append(center + side * math.cos(angle) * radius + up * math.sin(angle) * radius)
    for ring_index in range(rings):
        for segment in range(segments):
            next_segment = (segment + 1) % segments
            a = ring_index * segments + segment
            b = ring_index * segments + next_segment
            c = (ring_index + 1) * segments + next_segment
            d = (ring_index + 1) * segments + segment
            faces.append((a, b, c, d))
    return create_mesh(name, vertices, faces, armature, weight_function, mat)


def torus(name, center, axis, major, minor, armature, weight_function, mat):
    axis = axis.normalized()
    reference = Vector((0.0, 0.0, 1.0)) if abs(axis.z) < 0.9 else Vector((0.0, 1.0, 0.0))
    side = axis.cross(reference).normalized()
    up = axis.cross(side).normalized()
    vertices = []
    faces = []
    major_segments = 24
    minor_segments = 8
    for major_index in range(major_segments):
        major_angle = 2.0 * math.pi * major_index / major_segments
        ring_center = center + side * math.cos(major_angle) * major + up * math.sin(major_angle) * major
        normal = (ring_center - center).normalized()
        for minor_index in range(minor_segments):
            minor_angle = 2.0 * math.pi * minor_index / minor_segments
            vertices.append(ring_center + normal * math.cos(minor_angle) * minor + axis * math.sin(minor_angle) * minor)
    for major_index in range(major_segments):
        next_major = (major_index + 1) % major_segments
        for minor_index in range(minor_segments):
            next_minor = (minor_index + 1) % minor_segments
            a = major_index * minor_segments + minor_index
            b = next_major * minor_segments + minor_index
            c = next_major * minor_segments + next_minor
            d = major_index * minor_segments + next_minor
            faces.append((a, b, c, d))
    return create_mesh(name, vertices, faces, armature, weight_function, mat)


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=str(resolve(job["targetSourcePath"])))
armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
for obj in list(bpy.context.scene.objects):
    if obj != armature:
        bpy.data.objects.remove(obj, do_unlink=True)
bpy.context.view_layer.objects.active = armature
armature.select_set(True)
bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
armature.select_set(False)


def bone_point(name):
    return armature.data.bones[name].head_local.copy()


bones = {
    "hips": bone_point("Hips"),
    "spine": bone_point("Spine"),
    "chest": bone_point("Chest"),
    "neck": bone_point("Neck"),
    "upper_arm_L": bone_point("UpperArm_L"),
    "lower_arm_L": bone_point("LowerArm_L"),
    "upper_arm_R": bone_point("UpperArm_R"),
    "lower_arm_R": bone_point("LowerArm_R"),
    "upper_leg_L": bone_point("UpperLeg_L"),
    "upper_leg_R": bone_point("UpperLeg_R"),
    "lower_leg_L": bone_point("LowerLeg_L"),
    "lower_leg_R": bone_point("LowerLeg_R"),
}

burgundy = material("Knit_Burgundy", (0.24, 0.012, 0.045), roughness=0.72)
metal = material("Metal", (0.18, 0.2, 0.22), metallic=0.9, roughness=0.28)
hips_z = bones["hips"].z
chest_z = bones["chest"].z
neck_z = bones["neck"].z

ring_mesh(
    "CroppedTurtleneck",
    [chest_z - 0.105, chest_z - 0.035, neck_z - 0.08, neck_z + 0.015],
    [0.125, 0.14],
    [0.09, 0.102],
    0.0,
    -0.008,
    64,
    0.012,
    armature,
    lambda p: weights_for_torso(p, bones),
    burgundy,
)
ring_mesh(
    "TurtleneckCollar",
    [neck_z - 0.035, neck_z + 0.075],
    [0.116, 0.108],
    [0.09, 0.082],
    0.0,
    -0.006,
    64,
    0.014,
    armature,
    lambda p: weights_for_torso(p, bones),
    burgundy,
)
ring_mesh(
    "KnitBriefWaistband",
    [hips_z - 0.025, hips_z + 0.035],
    [0.145, 0.132],
    [0.112, 0.102],
    0.0,
    -0.005,
    64,
    0.014,
    armature,
    lambda p: weights_for_hip(p, bones),
    burgundy,
)

brief_profile = [
    (-0.145, hips_z + 0.03),
    (0.145, hips_z + 0.03),
    (0.11, hips_z - 0.045),
    (0.0, hips_z - 0.105),
    (-0.11, hips_z - 0.045),
]
brief_vertices = []
for y in (-0.128, -0.078):
    brief_vertices.extend((x, y, z) for x, z in brief_profile)
brief_faces = [(0, 1, 2), (0, 2, 4), (2, 3, 4), (5, 7, 6), (5, 9, 7), (7, 9, 8)]
for index in range(5):
    next_index = (index + 1) % 5
    brief_faces.append((index, 5 + index, 5 + next_index, next_index))
create_mesh(
    "KnitBriefFront",
    brief_vertices,
    brief_faces,
    armature,
    lambda p: weights_for_hip(p, bones),
    burgundy,
)

for side in ("L", "R"):
    sign = 1.0 if side == "L" else -1.0
    leg = bones[f"upper_leg_{side}"]
    lower = bones[f"lower_leg_{side}"]
    ring_mesh(
        f"{side}LegWarmer",
        [lower.z - 0.04, leg.z + 0.01],
        [0.058, 0.064],
        [0.072, 0.078],
        leg.x,
        -0.004,
        56,
        0.015,
        armature,
        lambda p, s=side: weights_for_leg(p, bones, s),
        burgundy,
    )
    upper_arm = bones[f"upper_arm_{side}"]
    lower_arm = bones[f"lower_arm_{side}"]
    tube_between(
        f"{side}ArmWarmer",
        upper_arm.lerp(lower_arm, 0.34),
        upper_arm.lerp(lower_arm, 0.98),
        0.05,
        0.055,
        48,
        8,
        armature,
        lambda p, s=side: weights_for_arm(p, bones, s),
        burgundy,
    )
    strap_start = Vector((sign * 0.115, -0.112, hips_z - 0.005))
    strap_end = Vector((sign * 0.11, -0.115, leg.z - 0.10))
    tube_between(
        f"{side}GarterStrap",
        strap_start,
        strap_end,
        0.012,
        0.012,
        10,
        2,
        armature,
        lambda p: weights_for_hip(p, bones),
        burgundy,
    )
    torus(
        f"{side}MetalClip",
        Vector((sign * 0.11, -0.121, leg.z - 0.095)),
        Vector((1.0, 0.0, 0.0)),
        0.026,
        0.006,
        armature,
        lambda p: weights_for_hip(p, bones),
        metal,
    )
    for bow_sign in (-1.0, 1.0):
        torus(
            f"{side}HipBow{bow_sign}",
            Vector((sign * (0.17 + bow_sign * 0.035), -0.115, hips_z - 0.015)),
            Vector((0.0, 0.0, 1.0)),
            0.036,
            0.012,
            armature,
            lambda p: weights_for_hip(p, bones),
            burgundy,
        )

for side_sign in (-1.0, 1.0):
    for index, x in enumerate((0.08, 0.13, 0.18)):
        tube_between(
            f"CableKnit_{'L' if side_sign < 0 else 'R'}_{index}",
            Vector((side_sign * x, -0.112, chest_z - 0.07)),
            Vector((side_sign * x, -0.112, neck_z - 0.07)),
            0.008,
            0.008,
            10,
            3,
            armature,
            lambda p: weights_for_torso(p, bones),
            burgundy,
        )

fbx_path = resolve(job["fbxAssetPath"])
blend_path = resolve(job["blendPath"])
fbx_path.parent.mkdir(parents=True, exist_ok=True)
blend_path.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
bpy.ops.object.select_all(action="DESELECT")
armature.select_set(True)
for obj in bpy.context.scene.objects:
    if obj.type == "MESH":
        obj.select_set(True)
bpy.context.view_layer.objects.active = armature
bpy.ops.export_scene.fbx(
    filepath=str(fbx_path),
    use_selection=True,
    add_leaf_bones=False,
    bake_anim=False,
    axis_forward="-Z",
    axis_up="Y",
    apply_unit_scale=True,
)
