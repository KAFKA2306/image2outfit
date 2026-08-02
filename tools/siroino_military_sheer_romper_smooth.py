#!/usr/bin/env python3
"""Smooth tailored geometry override for the military sheer-back romper build."""
from __future__ import annotations

import math

import bpy
from mathutils import Vector

import siroino_military_sheer_romper_build as base

TAU = math.tau
base.REVISION = "smooth-tailored-v4"


def parent(obj, armature, bone, role="garment"):
    world = obj.matrix_world.copy()
    obj.parent = armature
    obj.parent_type = "BONE"
    obj.parent_bone = bone
    obj.matrix_world = world
    obj["image2outfit_role"] = role
    return obj


def mesh_object(name, vertices, faces, materials, armature, bone, indices=None, thickness=0.0, bevel=0.0):
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    for material in materials:
        obj.data.materials.append(material)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    if indices:
        for polygon, index in zip(obj.data.polygons, indices):
            polygon.material_index = index
    if thickness:
        modifier = obj.modifiers.new("Fabric thickness", "SOLIDIFY")
        modifier.thickness = thickness
        modifier.offset = 0.0
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    if bevel:
        modifier = obj.modifiers.new("Soft tailored edge", "BEVEL")
        modifier.width = bevel
        modifier.segments = 2
        modifier.limit_method = "ANGLE"
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    return parent(obj, armature, bone)


def scaled_sphere(name, location, scale, material, armature, bone, role="garment"):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=40, ring_count=24, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    base.add_material(obj, material)
    return parent(obj, armature, bone, role)


def smooth_cylinder(name, location, radius, depth, material, armature, bone, rotation=(0, 0, 0), role="garment"):
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=radius, depth=depth, location=location, rotation=rotation)
    obj = bpy.context.object
    obj.name = name
    modifier = obj.modifiers.new("Rounded edge", "BEVEL")
    modifier.width = min(0.012, radius * 0.20)
    modifier.segments = 3
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    base.add_material(obj, material)
    return parent(obj, armature, bone, role)


def bodice(fabric, sheer, armature):
    segments = 56
    sections = [
        (0.74, 0.175, 0.105),
        (0.86, 0.195, 0.115),
        (1.02, 0.225, 0.132),
        (1.15, 0.235, 0.128),
        (1.235, 0.275, 0.115),
    ]
    vertices = []
    for z, rx, ry in sections:
        for index in range(segments):
            angle = TAU * index / segments
            vertices.append((rx * math.cos(angle), ry * math.sin(angle), z))
    faces, indices = [], []
    for ring in range(len(sections) - 1):
        zmid = (sections[ring][0] + sections[ring + 1][0]) * 0.5
        for index in range(segments):
            nxt = (index + 1) % segments
            faces.append((ring * segments + index, ring * segments + nxt, (ring + 1) * segments + nxt, (ring + 1) * segments + index))
            angle = TAU * (index + 0.5) / segments
            indices.append(1 if math.sin(angle) > 0.32 and abs(math.cos(angle)) < 0.92 and zmid > 0.82 else 0)
    outer = (len(sections) - 1) * segments
    inner = len(vertices)
    for index in range(segments):
        angle = TAU * index / segments
        vertices.append((0.092 * math.cos(angle), 0.074 * math.sin(angle), 1.245))
    for index in range(segments):
        nxt = (index + 1) % segments
        faces.append((outer + index, outer + nxt, inner + nxt, inner + index))
        indices.append(0)
    return mesh_object("Tailored_Bodice", vertices, faces, [fabric, sheer], armature, "Chest.1", indices, 0.0035, 0.003)


def short_leg(name, center_x, fabric, armature):
    segments = 40
    sections = [(0.75, 0.115, 0.125), (0.66, 0.128, 0.138), (0.48, 0.122, 0.132)]
    vertices = []
    for z, rx, ry in sections:
        for index in range(segments):
            angle = TAU * index / segments
            vertices.append((center_x + rx * math.cos(angle), ry * math.sin(angle), z))
    faces = []
    for ring in range(len(sections) - 1):
        for index in range(segments):
            nxt = (index + 1) % segments
            faces.append((ring * segments + index, ring * segments + nxt, (ring + 1) * segments + nxt, (ring + 1) * segments + index))
    return mesh_object(name, vertices, faces, [fabric], armature, "Hips.1", thickness=0.0035, bevel=0.004)


def wrap_panel(fabric, armature):
    rows, cols = 6, 9
    vertices = []
    for row in range(rows):
        v = row / (rows - 1)
        z = 0.765 - 0.305 * v
        left, right = -0.205 + 0.015 * v, 0.175 - 0.105 * v
        for col in range(cols):
            x = left + (right - left) * col / (cols - 1)
            normalized = min(0.98, abs(x) / 0.225)
            y = -0.142 * math.sqrt(max(0.02, 1.0 - normalized * normalized)) - 0.008
            vertices.append((x, y, z))
    faces = []
    for row in range(rows - 1):
        for col in range(cols - 1):
            a = row * cols + col
            faces.append((a, a + 1, a + cols + 1, a + cols))
    return mesh_object("Asymmetric_Wrap_Front", vertices, faces, [fabric], armature, "Hips.1", thickness=0.003, bevel=0.003)


def elliptical_band(name, z0, z1, rx, ry, material, armature, bone, gap=0.0):
    segments = 56
    count = segments + 1 if gap else segments
    start, end = -math.pi / 2 + gap, -math.pi / 2 + TAU - gap
    vertices = []
    for z in (z0, z1):
        for index in range(count):
            angle = start + (end - start) * index / (count - 1) if gap else TAU * index / count
            vertices.append((rx * math.cos(angle), ry * math.sin(angle), z))
    faces = []
    for index in range(count - 1 if gap else count):
        nxt = index + 1 if gap else (index + 1) % count
        faces.append((index, nxt, count + nxt, count + index))
    return mesh_object(name, vertices, faces, [material], armature, bone, thickness=0.004, bevel=0.0025)


def sleeve(name, sign, fabric, armature, cuff=False):
    segments = 40
    if cuff:
        sections = [(0.395 * sign, 0.082, 0.084), (0.455 * sign, 0.080, 0.082)]
    else:
        sections = [(0.205 * sign, 0.105, 0.105), (0.315 * sign, 0.095, 0.095), (0.425 * sign, 0.078, 0.080)]
    vertices = []
    for x, ry, rz in sections:
        for index in range(segments):
            angle = TAU * index / segments
            vertices.append((x, ry * math.cos(angle), 1.16 + rz * math.sin(angle)))
    faces = []
    for ring in range(len(sections) - 1):
        for index in range(segments):
            nxt = (index + 1) % segments
            face = (ring * segments + index, ring * segments + nxt, (ring + 1) * segments + nxt, (ring + 1) * segments + index)
            faces.append(face if sign > 0 else tuple(reversed(face)))
    bone = f"UpperArm_{'L' if sign > 0 else 'R'}.1"
    return mesh_object(name, vertices, faces, [fabric], armature, bone, thickness=0.0035 if cuff else 0.003, bevel=0.0025)


def chain(name, points, gold, armature):
    curve = bpy.data.curves.new(f"{name}_Curve", "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = 0.0042
    curve.bevel_resolution = 3
    spline = curve.splines.new("BEZIER")
    spline.bezier_points.add(len(points) - 1)
    for point, co in zip(spline.bezier_points, points):
        point.co = co
        point.handle_left_type = "AUTO"
        point.handle_right_type = "AUTO"
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(gold)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.convert(target="MESH")
    return parent(bpy.context.object, armature, "Chest.1")


def build_garment(armature, fabric, sheer, gold):
    objects = [bodice(fabric, sheer, armature)]
    objects += [short_leg("Romper_Short_L", 0.09, fabric, armature), short_leg("Romper_Short_R", -0.09, fabric, armature)]
    objects.append(wrap_panel(fabric, armature))
    objects.append(elliptical_band("Standing_Collar", 1.235, 1.335, 0.094, 0.074, fabric, armature, "Neck.1", 0.22))
    objects.append(elliptical_band("Waist_Belt", 0.735, 0.775, 0.188, 0.118, fabric, armature, "Hips.1"))
    for side, sign in (("L", 1), ("R", -1)):
        objects.append(sleeve(f"Tailored_Sleeve_{side}", sign, fabric, armature))
        objects.append(sleeve(f"Sleeve_Cuff_{side}", sign, fabric, armature, True))
        objects.append(base.box(f"Epaulette_{side}", (sign * 0.205, -0.002, 1.245), (0.092, 0.052, 0.009), fabric, armature, "Chest.1", 0.009))
        objects.append(scaled_sphere(f"Epaulette_Button_{side}", (sign * 0.215, -0.057, 1.255), (0.014, 0.008, 0.014), gold, armature, "Chest.1"))
    objects.append(base.box("Asymmetric_Closure_Piping", (-0.055, -0.137, 1.02), (0.006, 0.005, 0.205), fabric, armature, "Chest.1", 0.002))
    objects.append(base.box("Gold_Nameplate", (0.085, -0.143, 1.055), (0.054, 0.007, 0.016), gold, armature, "Chest.1", 0.006))
    objects.append(base.box("Belt_Buckle", (0.042, -0.137, 0.755), (0.032, 0.008, 0.034), gold, armature, "Hips.1", 0.005))
    for index, (x, z) in enumerate(((-0.12, 1.19), (-0.105, 1.08), (-0.078, 0.93)), 1):
        objects.append(scaled_sphere(f"Front_Button_{index}", (x, -0.14, z), (0.012, 0.007, 0.012), gold, armature, "Chest.1"))
    for index, x in enumerate((-0.13, -0.09, -0.05, -0.01, 0.03, 0.075, 0.12), 1):
        bpy.ops.mesh.primitive_torus_add(major_radius=0.008, minor_radius=0.0025, major_segments=24, minor_segments=8, location=(x, -0.136, 0.755), rotation=(math.pi / 2, 0, 0))
        eyelet = bpy.context.object
        eyelet.name = f"Belt_Eyelet_{index}"
        base.add_material(eyelet, gold)
        objects.append(parent(eyelet, armature, "Hips.1"))
    chain_sets = [
        [(0.205, -0.065, 1.245), (0.245, -0.145, 1.13), (0.195, -0.148, 1.00)],
        [(0.185, -0.064, 1.245), (0.225, -0.151, 1.10), (0.155, -0.150, 0.975)],
        [(0.165, -0.063, 1.245), (0.205, -0.155, 1.075), (0.115, -0.151, 0.955)],
    ]
    for index, points in enumerate(chain_sets, 1):
        objects.append(chain(f"Shoulder_Chain_{index}", points, gold, armature))
    return objects


def build_preview_body(armature, skin):
    objects = [
        scaled_sphere("Preview_Torso", (0, 0.014, 1.00), (0.165, 0.103, 0.30), skin, armature, "Chest.1", "preview-body"),
        scaled_sphere("Preview_Hips", (0, 0.012, 0.68), (0.185, 0.125, 0.16), skin, armature, "Hips.1", "preview-body"),
        smooth_cylinder("Preview_Neck", (0, 0, 1.31), 0.052, 0.16, skin, armature, "Neck.1", role="preview-body"),
        scaled_sphere("Preview_Head", (0, 0, 1.51), (0.105, 0.10, 0.135), skin, armature, "Head.1", "preview-body"),
    ]
    for side, sign in (("L", 1), ("R", -1)):
        upper, lower = f"UpperArm_{side}.1", f"LowerArm_{side}.1"
        objects += [
            scaled_sphere(f"Preview_Shoulder_{side}", (sign * 0.205, 0, 1.19), (0.075, 0.075, 0.075), skin, armature, upper, "preview-body"),
            smooth_cylinder(f"Preview_UpperArm_{side}", (sign * 0.325, 0, 1.17), 0.055, 0.27, skin, armature, upper, (0, math.pi / 2, 0), "preview-body"),
            smooth_cylinder(f"Preview_LowerArm_{side}", (sign * 0.555, 0, 1.135), 0.048, 0.26, skin, armature, lower, (0, math.pi / 2, 0), "preview-body"),
            scaled_sphere(f"Preview_Hand_{side}", (sign * 0.70, 0, 1.12), (0.055, 0.045, 0.065), skin, armature, lower, "preview-body"),
            smooth_cylinder(f"Preview_Thigh_{side}", (sign * 0.09, 0.005, 0.49), 0.073, 0.39, skin, armature, f"UpperLeg_{side}.1", role="preview-body"),
            smooth_cylinder(f"Preview_Shin_{side}", (sign * 0.09, 0.005, 0.17), 0.062, 0.32, skin, armature, f"LowerLeg_{side}.1", role="preview-body"),
        ]
    return objects


def look_at(obj, target=(0, 0, 0.80)):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def configure_scene():
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 720
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.view_settings.look = "AgX - Medium High Contrast"
    if scene.world is None:
        scene.world = bpy.data.worlds.new("ReviewWorld")
    scene.world.color = (0.055, 0.060, 0.072)
    camera_data = bpy.data.cameras.new("ReviewCamera")
    camera_data.lens = 63
    camera = bpy.data.objects.new("ReviewCamera", camera_data)
    bpy.context.collection.objects.link(camera)
    scene.camera = camera
    for name, location, energy, size in (
        ("Key", (2.7, -3.2, 3.1), 1250, 3.2),
        ("Fill", (-2.8, -2.2, 2.3), 720, 3.0),
        ("Rim", (1.3, 2.8, 2.8), 1050, 2.5),
    ):
        data = bpy.data.lights.new(name, "AREA")
        data.energy = energy
        data.shape = "DISK"
        data.size = size
        light = bpy.data.objects.new(name, data)
        light.location = location
        bpy.context.collection.objects.link(light)
        look_at(light)
    floor_mat = base.plain_material("MAT_Review_Floor", (0.12, 0.13, 0.16, 1.0), 0.78)
    floor = base.box("Review_Floor", (0, 0, -0.035), (1.7, 1.7, 0.035), floor_mat, bevel=0.0)
    floor["image2outfit_role"] = "review-stage"
    return camera


base.build_garment = build_garment
base.preview_body = build_preview_body
base.configure_scene = configure_scene

if __name__ == "__main__":
    raise SystemExit(base.main())
