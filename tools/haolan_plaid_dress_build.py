import hashlib
import json
import math
import os
import sys
from array import array
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


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_plaid_image(path, size=512):
    path.parent.mkdir(parents=True, exist_ok=True)
    image = bpy.data.images.new("PinkPlaidTexture", width=size, height=size, alpha=True)
    pixels = array("f")
    base = (0.93, 0.49, 0.64)
    period = size // 4

    def stripe_distance(value, offset):
        wrapped = (value - offset) % period
        return min(wrapped, period - wrapped)

    for y in range(size):
        for x in range(size):
            color = list(base)
            vertical_wide = stripe_distance(x, 0) < 9
            horizontal_wide = stripe_distance(y, 0) < 9
            vertical_thin = stripe_distance(x, period // 2) < 3
            horizontal_thin = stripe_distance(y, period // 2) < 3
            vertical_highlight = stripe_distance(x, period // 4) < 2
            horizontal_highlight = stripe_distance(y, period // 4) < 2

            if vertical_wide:
                color = [channel * factor for channel, factor in zip(color, (0.68, 0.50, 0.58))]
            if horizontal_wide:
                color = [channel * factor for channel, factor in zip(color, (0.72, 0.54, 0.60))]
            if vertical_thin or horizontal_thin:
                color = [channel * factor for channel, factor in zip(color, (0.82, 0.62, 0.68))]
            if vertical_highlight or horizontal_highlight:
                color = [min(1.0, channel * 1.12 + 0.05) for channel in color]
            if vertical_wide and horizontal_wide:
                color = [channel * 0.80 for channel in color]
            pixels.extend((*color, 1.0))

    image.pixels.foreach_set(pixels)
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.colorspace_settings.name = "sRGB"
    image.save()
    return image


def create_material(name, color, metallic=0.0, roughness=0.58, image=None):
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
    if image is not None:
        texture = nodes.new("ShaderNodeTexImage")
        texture.image = image
        texture.interpolation = "Linear"
        texture.extension = "REPEAT"
        result.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    return result


def normalized_weights(entries):
    positive = [(name, max(0.0, weight)) for name, weight in entries if weight > 1e-8]
    total = sum(weight for _, weight in positive)
    if total <= 1e-8:
        raise ValueError("weight function returned no positive weights")
    return [(name, weight / total) for name, weight in positive]


def apply_uvs(mesh, uv_spec):
    if not uv_spec:
        return
    layer = mesh.uv_layers.new(name="UVMap")
    mode = uv_spec.get("mode", "planar")
    u_repeat = float(uv_spec.get("uRepeat", 1.0))
    v_repeat = float(uv_spec.get("vRepeat", 1.0))
    center_x = float(uv_spec.get("centerX", 0.0))
    center_y = float(uv_spec.get("centerY", 0.0))
    z_min = float(uv_spec.get("zMin", 0.0))
    z_max = float(uv_spec.get("zMax", 1.0))
    z_range = max(1e-6, z_max - z_min)
    scale = float(uv_spec.get("scale", 5.0))

    for polygon in mesh.polygons:
        raw = []
        for loop_index in polygon.loop_indices:
            point = mesh.vertices[mesh.loops[loop_index].vertex_index].co
            if mode == "cylinder":
                angle = math.atan2(point.y - center_y, point.x - center_x)
                raw.append(((angle / (2.0 * math.pi)) % 1.0, (point.z - z_min) / z_range))
            elif mode == "xy":
                raw.append(((point.x - center_x) * scale, (point.y - center_y) * scale))
            else:
                raw.append(((point.x - center_x) * scale, (point.z - z_min) * scale))

        if mode == "cylinder":
            u_values = [value[0] for value in raw]
            if max(u_values) - min(u_values) > 0.5:
                raw = [(u + 1.0 if u < 0.25 else u, v) for u, v in raw]

        for loop_index, (u, v) in zip(polygon.loop_indices, raw):
            layer.data[loop_index].uv = (u * u_repeat, v * v_repeat)


def create_mesh(name, vertices, faces, armature, weight_function, material, uv_spec=None):
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata([tuple(vertex) for vertex in vertices], [], faces)
    mesh.validate(clean_customdata=False)
    mesh.update(calc_edges=True)
    apply_uvs(mesh, uv_spec)
    for polygon in mesh.polygons:
        polygon.use_smooth = True

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = armature
    obj.matrix_parent_inverse = Matrix.Identity(4)
    obj.data.materials.append(material)
    obj["image2outfitDelivery"] = True
    obj["sourceReference"] = "user supplied pink plaid dress image"

    groups = {}
    for vertex in mesh.vertices:
        for bone_name, weight in normalized_weights(weight_function(vertex.co.copy())):
            group = groups.get(bone_name)
            if group is None:
                group = obj.vertex_groups.new(name=bone_name)
                groups[bone_name] = group
            group.add([vertex.index], weight, "REPLACE")

    modifier = obj.modifiers.new("Armature", "ARMATURE")
    modifier.object = armature
    return obj


def radial_shell(
    name,
    rings,
    center_x,
    center_y,
    segments,
    thickness,
    armature,
    weight_function,
    material,
    uv_spec=None,
):
    vertices = []
    for inner in (False, True):
        for ring in rings:
            for segment in range(segments):
                angle = 2.0 * math.pi * segment / segments
                frontness = max(0.0, -math.sin(angle))
                backness = max(0.0, math.sin(angle))
                radius_factor = 1.0 + ring.get("pleat", 0.0) * math.cos(
                    ring.get("pleatCount", 16) * angle
                )
                radius_factor += ring.get("ripple", 0.0) * math.cos(
                    ring.get("rippleCount", 32) * angle
                )
                inset = thickness if inner else 0.0
                rx = max(0.001, ring["rx"] * radius_factor - inset)
                ry = max(0.001, ring["ry"] * radius_factor - inset)
                z = ring["z"]
                z -= ring.get("frontDip", 0.0) * (frontness ** ring.get("frontPower", 1.7))
                z += ring.get("backRise", 0.0) * (backness ** 2.0)
                z += ring.get("zWave", 0.0) * math.cos(ring.get("zWaveCount", 16) * angle)
                vertices.append(
                    Vector(
                        (
                            center_x + rx * math.cos(angle),
                            center_y + ry * math.sin(angle),
                            z,
                        )
                    )
                )

    ring_count = len(rings)
    surface_size = ring_count * segments
    faces = []
    for ring_index in range(ring_count - 1):
        for segment in range(segments):
            next_segment = (segment + 1) % segments
            a = ring_index * segments + segment
            b = ring_index * segments + next_segment
            c = (ring_index + 1) * segments + next_segment
            d = (ring_index + 1) * segments + segment
            faces.append((a, b, c, d))
            ia, ib, ic, id_ = (
                surface_size + a,
                surface_size + b,
                surface_size + c,
                surface_size + d,
            )
            faces.append((ia, id_, ic, ib))

    for segment in range(segments):
        next_segment = (segment + 1) % segments
        bottom_outer = segment
        bottom_next = next_segment
        bottom_inner = surface_size + segment
        bottom_inner_next = surface_size + next_segment
        faces.append((bottom_outer, bottom_inner, bottom_inner_next, bottom_next))

        top = (ring_count - 1) * segments
        top_outer = top + segment
        top_next = top + next_segment
        top_inner = surface_size + top + segment
        top_inner_next = surface_size + top + next_segment
        faces.append((top_outer, top_next, top_inner_next, top_inner))

    return create_mesh(
        name,
        vertices,
        faces,
        armature,
        weight_function,
        material,
        uv_spec,
    )


def tube_shell_between(
    name,
    start,
    end,
    radii,
    segments,
    thickness,
    armature,
    weight_function,
    material,
    uv_spec=None,
):
    axis = (end - start).normalized()
    reference = Vector((0.0, 0.0, 1.0)) if abs(axis.z) < 0.9 else Vector((0.0, 1.0, 0.0))
    side = axis.cross(reference).normalized()
    up = axis.cross(side).normalized()
    vertices = []
    ring_count = len(radii)
    for inner in (False, True):
        for ring_index, radius in enumerate(radii):
            t = ring_index / max(1, ring_count - 1)
            center = start.lerp(end, t)
            use_radius = max(0.001, radius - (thickness if inner else 0.0))
            for segment in range(segments):
                angle = 2.0 * math.pi * segment / segments
                puff = 1.0 + 0.025 * math.cos(8.0 * angle)
                vertices.append(
                    center
                    + side * math.cos(angle) * use_radius * puff
                    + up * math.sin(angle) * use_radius * puff
                )

    surface_size = ring_count * segments
    faces = []
    for ring_index in range(ring_count - 1):
        for segment in range(segments):
            next_segment = (segment + 1) % segments
            a = ring_index * segments + segment
            b = ring_index * segments + next_segment
            c = (ring_index + 1) * segments + next_segment
            d = (ring_index + 1) * segments + segment
            faces.append((a, b, c, d))
            ia, ib, ic, id_ = (
                surface_size + a,
                surface_size + b,
                surface_size + c,
                surface_size + d,
            )
            faces.append((ia, id_, ic, ib))

    for segment in range(segments):
        next_segment = (segment + 1) % segments
        faces.append((segment, surface_size + segment, surface_size + next_segment, next_segment))
        top = (ring_count - 1) * segments
        faces.append(
            (
                top + segment,
                top + next_segment,
                surface_size + top + next_segment,
                surface_size + top + segment,
            )
        )

    return create_mesh(
        name,
        vertices,
        faces,
        armature,
        weight_function,
        material,
        uv_spec,
    )


def ellipsoid(
    name,
    center,
    radii,
    armature,
    weight_function,
    material,
    longitude_segments=24,
    latitude_segments=12,
    basis=None,
    uv_spec=None,
):
    basis = basis or (
        Vector((1.0, 0.0, 0.0)),
        Vector((0.0, 1.0, 0.0)),
        Vector((0.0, 0.0, 1.0)),
    )
    bx, by, bz = basis
    rx, ry, rz = radii
    vertices = [center + bz * rz]
    for latitude in range(1, latitude_segments):
        theta = math.pi * latitude / latitude_segments
        radial = math.sin(theta)
        height = math.cos(theta)
        for longitude in range(longitude_segments):
            phi = 2.0 * math.pi * longitude / longitude_segments
            vertices.append(
                center
                + bx * (rx * radial * math.cos(phi))
                + by * (ry * radial * math.sin(phi))
                + bz * (rz * height)
            )
    bottom_index = len(vertices)
    vertices.append(center - bz * rz)

    faces = []
    for longitude in range(longitude_segments):
        next_longitude = (longitude + 1) % longitude_segments
        faces.append((0, 1 + longitude, 1 + next_longitude))
    for latitude in range(latitude_segments - 2):
        start = 1 + latitude * longitude_segments
        next_start = start + longitude_segments
        for longitude in range(longitude_segments):
            next_longitude = (longitude + 1) % longitude_segments
            faces.append(
                (
                    start + longitude,
                    next_start + longitude,
                    next_start + next_longitude,
                    start + next_longitude,
                )
            )
    last_ring = 1 + (latitude_segments - 2) * longitude_segments
    for longitude in range(longitude_segments):
        next_longitude = (longitude + 1) % longitude_segments
        faces.append((last_ring + longitude, bottom_index, last_ring + next_longitude))

    return create_mesh(
        name,
        vertices,
        faces,
        armature,
        weight_function,
        material,
        uv_spec,
    )


def torus(
    name,
    center,
    axis,
    major_x,
    major_z,
    minor,
    armature,
    weight_function,
    material,
    major_segments=32,
    minor_segments=8,
):
    axis = axis.normalized()
    reference = Vector((0.0, 0.0, 1.0)) if abs(axis.z) < 0.9 else Vector((0.0, 1.0, 0.0))
    side = axis.cross(reference).normalized()
    up = axis.cross(side).normalized()
    vertices = []
    faces = []
    for major_index in range(major_segments):
        major_angle = 2.0 * math.pi * major_index / major_segments
        radial = side * (major_x * math.cos(major_angle)) + up * (
            major_z * math.sin(major_angle)
        )
        ring_center = center + radial
        normal = radial.normalized()
        for minor_index in range(minor_segments):
            minor_angle = 2.0 * math.pi * minor_index / minor_segments
            vertices.append(
                ring_center
                + normal * math.cos(minor_angle) * minor
                + axis * math.sin(minor_angle) * minor
            )
    for major_index in range(major_segments):
        next_major = (major_index + 1) % major_segments
        for minor_index in range(minor_segments):
            next_minor = (minor_index + 1) % minor_segments
            a = major_index * minor_segments + minor_index
            b = next_major * minor_segments + minor_index
            c = next_major * minor_segments + next_minor
            d = major_index * minor_segments + next_minor
            faces.append((a, b, c, d))
    return create_mesh(name, vertices, faces, armature, weight_function, material)


def ribbon_box(
    name,
    start,
    end,
    half_width,
    half_depth,
    armature,
    weight_function,
    material,
):
    axis = (end - start).normalized()
    depth = Vector((0.0, 1.0, 0.0))
    side = depth.cross(axis)
    if side.length_squared < 1e-8:
        depth = Vector((0.0, 0.0, 1.0))
        side = depth.cross(axis)
    side.normalize()
    depth = axis.cross(side).normalized()
    vertices = []
    for point in (start, end):
        vertices.extend(
            (
                point - side * half_width - depth * half_depth,
                point + side * half_width - depth * half_depth,
                point + side * half_width + depth * half_depth,
                point - side * half_width + depth * half_depth,
            )
        )
    faces = [
        (0, 1, 2, 3),
        (4, 7, 6, 5),
        (0, 4, 5, 1),
        (1, 5, 6, 2),
        (2, 6, 7, 3),
        (3, 7, 4, 0),
    ]
    return create_mesh(name, vertices, faces, armature, weight_function, material)


def add_bow(prefix, center, size, armature, weight_function, material):
    ellipsoid(
        f"{prefix}_LeftLoop",
        center + Vector((-size * 0.65, 0.0, 0.0)),
        (size * 0.75, size * 0.22, size * 0.45),
        armature,
        weight_function,
        material,
        longitude_segments=16,
        latitude_segments=8,
    )
    ellipsoid(
        f"{prefix}_RightLoop",
        center + Vector((size * 0.65, 0.0, 0.0)),
        (size * 0.75, size * 0.22, size * 0.45),
        armature,
        weight_function,
        material,
        longitude_segments=16,
        latitude_segments=8,
    )
    ellipsoid(
        f"{prefix}_Knot",
        center + Vector((0.0, -size * 0.08, 0.0)),
        (size * 0.35, size * 0.28, size * 0.35),
        armature,
        weight_function,
        material,
        longitude_segments=16,
        latitude_segments=8,
    )


def add_area_light(name, location, energy, size, color):
    data = bpy.data.lights.new(name=name, type="AREA")
    data.energy = energy
    data.shape = "DISK"
    data.size = size
    data.color = color
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    return obj


def point_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def render_preview(path, target_z):
    path.parent.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 1024
    scene.render.resolution_y = 1024
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.render.filepath = str(path)
    if scene.world is None:
        scene.world = bpy.data.worlds.new("DeliveryPreviewWorld")
    scene.world.color = (0.035, 0.045, 0.075)

    camera_data = bpy.data.cameras.new("DeliveryPreviewCamera")
    camera = bpy.data.objects.new("DeliveryPreviewCamera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = (0.92, -2.35, target_z + 0.30)
    camera_data.lens = 72
    point_at(camera, (0.0, -0.015, target_z))
    scene.camera = camera

    key = add_area_light(
        "PreviewKey", (1.2, -1.6, target_z + 1.0), 900.0, 1.8, (1.0, 0.70, 0.82)
    )
    fill = add_area_light(
        "PreviewFill", (-1.3, -0.8, target_z + 0.35), 650.0, 1.5, (0.60, 0.72, 1.0)
    )
    rim = add_area_light(
        "PreviewRim", (0.0, 1.0, target_z + 0.75), 1000.0, 1.4, (0.82, 0.62, 1.0)
    )
    for light in (key, fill, rim):
        point_at(light, (0.0, 0.0, target_z))

    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass
    bpy.ops.render.render(write_still=True)


bpy.ops.wm.read_factory_settings(use_empty=True)
target_source = resolve(job["targetSourcePath"])
bpy.ops.import_scene.fbx(filepath=str(target_source))
armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
for obj in list(bpy.context.scene.objects):
    if obj != armature:
        bpy.data.objects.remove(obj, do_unlink=True)
bpy.context.view_layer.objects.active = armature
armature.select_set(True)
bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
armature.select_set(False)
armature.name = "Armature"
armature["targetAvatar"] = "HAOLAN v1.6"


def bone_point(name):
    if name not in armature.data.bones:
        raise KeyError(f"required HAOLAN bone is missing: {name}")
    return armature.data.bones[name].head_local.copy()


bones = {
    "hips": bone_point("Hips"),
    "spine": bone_point("Spine"),
    "chest": bone_point("Chest"),
    "neck": bone_point("Neck"),
    "head": bone_point("Head"),
    "shoulder_L": bone_point("Shoulder_L"),
    "upper_arm_L": bone_point("UpperArm_L"),
    "lower_arm_L": bone_point("LowerArm_L"),
    "hand_L": bone_point("Hand_L"),
    "shoulder_R": bone_point("Shoulder_R"),
    "upper_arm_R": bone_point("UpperArm_R"),
    "lower_arm_R": bone_point("LowerArm_R"),
    "hand_R": bone_point("Hand_R"),
    "upper_leg_L": bone_point("UpperLeg_L"),
    "lower_leg_L": bone_point("LowerLeg_L"),
    "foot_L": bone_point("Foot_L"),
    "upper_leg_R": bone_point("UpperLeg_R"),
    "lower_leg_R": bone_point("LowerLeg_R"),
    "foot_R": bone_point("Foot_R"),
}

scale = max(0.75, min(1.35, (bones["neck"].z - bones["hips"].z) / 0.309562))
hips_z = bones["hips"].z
spine_z = bones["spine"].z
chest_z = bones["chest"].z
neck_z = bones["neck"].z


def s(value):
    return value * scale


def torso_weights(point):
    z = point.z
    if z <= hips_z:
        return [("Hips", 1.0)]
    if z < spine_z:
        t = (z - hips_z) / max(1e-6, spine_z - hips_z)
        return [("Hips", 1.0 - t), ("Spine", t)]
    if z < chest_z:
        t = (z - spine_z) / max(1e-6, chest_z - spine_z)
        return [("Spine", 1.0 - t), ("Chest", t)]
    if z < neck_z:
        t = min(1.0, (z - chest_z) / max(1e-6, neck_z - chest_z))
        return [("Chest", 1.0 - 0.25 * t), ("Neck", 0.25 * t)]
    return [("Neck", 1.0)]


def skirt_weights(point):
    lower = hips_z - s(0.16)
    t = max(0.0, min(1.0, (hips_z + s(0.06) - point.z) / max(1e-6, hips_z + s(0.06) - lower)))
    if abs(point.x) < s(0.035):
        return [("Hips", 1.0)]
    side = "L" if point.x >= 0.0 else "R"
    return [("Hips", 1.0 - 0.58 * t), (f"UpperLeg_{side}", 0.58 * t)]


def arm_weights(point, side):
    upper = bones[f"upper_arm_{side}"]
    lower = bones[f"lower_arm_{side}"]
    axis = lower - upper
    t = max(0.0, min(1.0, (point - upper).dot(axis) / max(1e-8, axis.length_squared)))
    return [(f"UpperArm_{side}", 1.0 - 0.15 * t), (f"LowerArm_{side}", 0.15 * t)]


def boot_weights(point, side):
    foot = bones[f"foot_{side}"]
    lower = bones[f"lower_leg_{side}"]
    z_range = max(1e-6, lower.z - foot.z)
    t = max(0.0, min(1.0, (point.z - foot.z) / z_range))
    return [(f"Foot_{side}", 1.0 - 0.75 * t), (f"LowerLeg_{side}", 0.75 * t)]


generated_dir = resolve(job["fbxAssetPath"]).parent
plaid_path = resolve(
    job.get(
        "plaidTextureAssetPath",
        str(Path(job["fbxAssetPath"]).parent / "HAOLAN_PinkPlaid.png"),
    )
)
preview_path = resolve(
    job.get(
        "previewPath",
        str(Path(job["fbxAssetPath"]).parent / "HAOLAN_PinkPlaidDress_preview.png"),
    )
)
plaid_image = create_plaid_image(plaid_path)
plaid = create_material("Pink_Plaid", (0.93, 0.49, 0.64), roughness=0.58, image=plaid_image)
black = create_material("Black_Lace_and_Ribbon", (0.012, 0.015, 0.028), roughness=0.48)
navy = create_material("Boot_NavyBlack", (0.018, 0.025, 0.055), roughness=0.34)
gold = create_material("Antique_Gold", (0.63, 0.34, 0.08), metallic=0.88, roughness=0.26)
rose = create_material("Rose_Gem", (0.56, 0.018, 0.08), metallic=0.16, roughness=0.30)

bodice_bottom = hips_z + s(0.045)
bodice_top = chest_z + s(0.105)
bodice_rings = [
    {"z": bodice_bottom, "rx": s(0.142), "ry": s(0.108)},
    {"z": spine_z + s(0.020), "rx": s(0.134), "ry": s(0.108)},
    {"z": chest_z + s(0.010), "rx": s(0.146), "ry": s(0.126)},
    {
        "z": bodice_top,
        "rx": s(0.142),
        "ry": s(0.119),
        "frontDip": s(0.060),
        "frontPower": 1.75,
        "backRise": s(0.005),
    },
]
radial_shell(
    "PlaidBustierBodice",
    bodice_rings,
    0.0,
    -s(0.006),
    72,
    s(0.0035),
    armature,
    torso_weights,
    plaid,
    {
        "mode": "cylinder",
        "centerY": -s(0.006),
        "zMin": bodice_bottom,
        "zMax": bodice_top,
        "uRepeat": 3.0,
        "vRepeat": 2.5,
    },
)

for side in ("L", "R"):
    sign = 1.0 if side == "L" else -1.0
    cup_center = Vector((sign * s(0.068), -s(0.103), chest_z + s(0.025)))
    ellipsoid(
        f"{side}StructuredBustCup",
        cup_center,
        (s(0.078), s(0.044), s(0.068)),
        armature,
        lambda point: [("Chest", 1.0)],
        plaid,
        longitude_segments=28,
        latitude_segments=14,
        uv_spec={"mode": "planar", "zMin": chest_z - s(0.06), "scale": 8.0},
    )

neckline_lace = [
    {
        "z": bodice_top - s(0.018),
        "rx": s(0.148),
        "ry": s(0.126),
        "frontDip": s(0.060),
        "frontPower": 1.75,
        "ripple": 0.018,
        "rippleCount": 36,
    },
    {
        "z": bodice_top + s(0.002),
        "rx": s(0.150),
        "ry": s(0.128),
        "frontDip": s(0.060),
        "frontPower": 1.75,
        "ripple": 0.028,
        "rippleCount": 36,
        "zWave": s(0.004),
        "zWaveCount": 36,
    },
]
radial_shell(
    "BlackLaceNeckline",
    neckline_lace,
    0.0,
    -s(0.007),
    96,
    s(0.0025),
    armature,
    torso_weights,
    black,
)

for side in ("L", "R"):
    sign = 1.0 if side == "L" else -1.0
    upper_arm = bones[f"upper_arm_{side}"]
    lower_arm = bones[f"lower_arm_{side}"]
    start = upper_arm + Vector((sign * s(0.010), -s(0.002), -s(0.006)))
    end = upper_arm.lerp(lower_arm, 0.42)
    tube_shell_between(
        f"{side}PlaidPuffSleeve",
        start,
        end,
        [s(0.042), s(0.061), s(0.070), s(0.064), s(0.043)],
        48,
        s(0.003),
        armature,
        lambda point, arm_side=side: arm_weights(point, arm_side),
        plaid,
        {"mode": "planar", "zMin": hips_z, "scale": 9.0},
    )
    tube_shell_between(
        f"{side}SleeveLaceCuff",
        end - (end - start).normalized() * s(0.012),
        end + (end - start).normalized() * s(0.012),
        [s(0.047), s(0.051), s(0.047)],
        40,
        s(0.0025),
        armature,
        lambda point, arm_side=side: arm_weights(point, arm_side),
        black,
    )

    strap_bottom = Vector(
        (
            sign * s(0.100),
            -s(0.105),
            chest_z + s(0.050),
        )
    )
    strap_top = bones[f"shoulder_{side}"] + Vector(
        (-sign * s(0.004), -s(0.050), -s(0.005))
    )
    tube_shell_between(
        f"{side}ShoulderStrap",
        strap_bottom,
        strap_top,
        [s(0.006), s(0.006)],
        12,
        s(0.002),
        armature,
        lambda point: [("Chest", 0.85), (f"Shoulder_{side}", 0.15)],
        black,
    )

waist_z = hips_z + s(0.060)
skirt_bottom = bones["upper_leg_L"].z - s(0.115)
skirt_rings = [
    {"z": waist_z, "rx": s(0.143), "ry": s(0.111), "pleat": 0.012},
    {"z": hips_z + s(0.020), "rx": s(0.158), "ry": s(0.126), "pleat": 0.025},
    {"z": hips_z - s(0.050), "rx": s(0.195), "ry": s(0.155), "pleat": 0.055},
    {"z": skirt_bottom + s(0.050), "rx": s(0.238), "ry": s(0.192), "pleat": 0.080},
    {
        "z": skirt_bottom,
        "rx": s(0.264),
        "ry": s(0.215),
        "pleat": 0.095,
        "zWave": s(0.008),
        "zWaveCount": 16,
    },
]
radial_shell(
    "PleatedPlaidMiniSkirt",
    skirt_rings,
    0.0,
    -s(0.002),
    96,
    s(0.0035),
    armature,
    skirt_weights,
    plaid,
    {
        "mode": "cylinder",
        "centerY": -s(0.002),
        "zMin": skirt_bottom,
        "zMax": waist_z,
        "uRepeat": 4.0,
        "vRepeat": 3.0,
    },
)

radial_shell(
    "BlackLaceSkirtHem",
    [
        {
            "z": skirt_bottom - s(0.020),
            "rx": s(0.274),
            "ry": s(0.224),
            "pleat": 0.085,
            "ripple": 0.022,
            "rippleCount": 40,
            "zWave": s(0.012),
            "zWaveCount": 32,
        },
        {
            "z": skirt_bottom + s(0.018),
            "rx": s(0.266),
            "ry": s(0.217),
            "pleat": 0.080,
            "ripple": 0.012,
            "rippleCount": 40,
        },
    ],
    0.0,
    -s(0.002),
    120,
    s(0.0025),
    armature,
    skirt_weights,
    black,
)

radial_shell(
    "BlackWaistBelt",
    [
        {"z": waist_z - s(0.020), "rx": s(0.150), "ry": s(0.116)},
        {"z": waist_z + s(0.018), "rx": s(0.148), "ry": s(0.114)},
    ],
    0.0,
    -s(0.004),
    64,
    s(0.003),
    armature,
    lambda point: [("Hips", 0.8), ("Spine", 0.2)],
    black,
)

front_y = -s(0.128)
for index, z_offset in enumerate((s(0.014), s(0.044))):
    add_bow(
        f"FrontBodiceBow{index + 1}",
        Vector((0.0, -s(0.137), chest_z - z_offset)),
        s(0.018),
        armature,
        lambda point: [("Chest", 1.0)],
        black,
    )

buckle_center = Vector((s(0.105), -s(0.129), waist_z))
torus(
    "GoldRoseBuckle",
    buckle_center,
    Vector((0.0, 1.0, 0.0)),
    s(0.031),
    s(0.031),
    s(0.006),
    armature,
    lambda point: [("Hips", 0.85), ("Spine", 0.15)],
    gold,
)
ellipsoid(
    "RoseBuckleGem",
    buckle_center + Vector((0.0, -s(0.007), 0.0)),
    (s(0.020), s(0.008), s(0.020)),
    armature,
    lambda point: [("Hips", 0.85), ("Spine", 0.15)],
    rose,
    longitude_segments=20,
    latitude_segments=10,
)
add_bow(
    "WaistRibbonBow",
    buckle_center + Vector((s(0.045), s(0.004), 0.0)),
    s(0.032),
    armature,
    lambda point: [("Hips", 0.9), ("Spine", 0.1)],
    black,
)
ribbon_box(
    "WaistRibbonTailLong",
    buckle_center + Vector((s(0.045), s(0.004), -s(0.008))),
    Vector((s(0.130), -s(0.126), skirt_bottom + s(0.020))),
    s(0.014),
    s(0.0025),
    armature,
    skirt_weights,
    black,
)
ribbon_box(
    "WaistRibbonTailShort",
    buckle_center + Vector((s(0.025), s(0.004), -s(0.006))),
    Vector((s(0.065), -s(0.128), skirt_bottom + s(0.080))),
    s(0.012),
    s(0.0025),
    armature,
    skirt_weights,
    black,
)

for side in ("L", "R"):
    leg_x = bones[f"lower_leg_{side}"].x
    foot = bones[f"foot_{side}"]
    lower = bones[f"lower_leg_{side}"]
    shaft_bottom = foot + Vector((0.0, 0.0, -s(0.018)))
    shaft_top = foot.lerp(lower, 0.48)
    tube_shell_between(
        f"{side}AnkleBootShaft",
        shaft_bottom,
        shaft_top,
        [s(0.052), s(0.060), s(0.068), s(0.066)],
        40,
        s(0.004),
        armature,
        lambda point, leg_side=side: boot_weights(point, leg_side),
        navy,
    )
    ellipsoid(
        f"{side}BootFoot",
        Vector((leg_x, -s(0.058), foot.z - s(0.020))),
        (s(0.061), s(0.125), s(0.048)),
        armature,
        lambda point, leg_side=side: [(f"Foot_{leg_side}", 1.0)],
        navy,
        longitude_segments=28,
        latitude_segments=12,
    )
    ellipsoid(
        f"{side}BootSole",
        Vector((leg_x, -s(0.060), foot.z - s(0.058))),
        (s(0.064), s(0.128), s(0.018)),
        armature,
        lambda point, leg_side=side: [(f"Foot_{leg_side}", 1.0)],
        black,
        longitude_segments=24,
        latitude_segments=10,
    )
    radial_shell(
        f"{side}BootBuckleBand",
        [
            {"z": foot.z + s(0.060), "rx": s(0.070), "ry": s(0.066)},
            {"z": foot.z + s(0.078), "rx": s(0.070), "ry": s(0.066)},
        ],
        leg_x,
        0.0,
        40,
        s(0.0025),
        armature,
        lambda point, leg_side=side: boot_weights(point, leg_side),
        gold,
    )

if os.environ.get("IMAGE2OUTFIT_SKIP_RENDER") == "1":
    preview_path.parent.mkdir(parents=True, exist_ok=True)
else:
    render_preview(preview_path, hips_z - s(0.005))

fbx_path = resolve(job["fbxAssetPath"])
blend_path = resolve(job["blendPath"])
artifact_dir = resolve(job["artifactDir"])
fbx_path.parent.mkdir(parents=True, exist_ok=True)
blend_path.parent.mkdir(parents=True, exist_ok=True)
artifact_dir.mkdir(parents=True, exist_ok=True)

readme_path = generated_dir / "README.md"
readme_path.write_text(
    "\n".join(
        [
            "# HAOLAN Pink Plaid Dress",
            "",
            "Target: HAOLAN v1.6.",
            "",
            "Contents: fitted plaid bustier, structured cups, black lace neckline, "
            "off-shoulder puff sleeves, shoulder straps, pleated mini skirt, black lace hem, "
            "waist belt and rose buckle, ribbon tails, and ankle boots.",
            "",
            "Import the entire UnityAssets folder into one Unity 2022.3.22f1 VRChat Avatar project. "
            "Keep all .meta files beside their assets. Place the outfit prefab under the HAOLAN avatar root; "
            "Modular Avatar Merge Armature performs the bone merge.",
            "",
            "HAOLAN avatar data is not included. Credit: HAOLAN by かなﾘぁさんち.",
            "Official source and terms: https://booth.pm/en/items/3818504",
            "",
        ]
    ),
    encoding="utf-8",
)

build_metadata = {
    "jobId": job["id"],
    "target": "HAOLAN v1.6",
    "targetSourceSha256": sha256(target_source),
    "targetSourceRedistributed": False,
    "referenceInterpretation": [
        "pink plaid fitted bustier",
        "black lace low neckline",
        "off-shoulder puff sleeves",
        "black shoulder straps and waist belt",
        "gold rose buckle and ribbon tails",
        "pleated mini skirt with black lace hem",
        "navy-black ankle boots with gold bands",
    ],
    "scaleFactorFromHAOLANSkeleton": scale,
    "requiredBoneNames": sorted(
        {
            "Hips",
            "Spine",
            "Chest",
            "Neck",
            "Shoulder_L",
            "Shoulder_R",
            "UpperArm_L",
            "UpperArm_R",
            "LowerArm_L",
            "LowerArm_R",
            "UpperLeg_L",
            "UpperLeg_R",
            "LowerLeg_L",
            "LowerLeg_R",
            "Foot_L",
            "Foot_R",
        }
    ),
    "generatedMeshObjects": sum(
        1
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.get("image2outfitDelivery")
    ),
    "plaidTexture": str(plaid_path.relative_to(root)).replace("\\", "/"),
    "preview": str(preview_path.relative_to(root)).replace("\\", "/"),
}
(artifact_dir / "build-metadata.json").write_text(
    json.dumps(build_metadata, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
bpy.ops.object.select_all(action="DESELECT")
armature.select_set(True)
for obj in bpy.context.scene.objects:
    if obj.type == "MESH" and obj.get("image2outfitDelivery"):
        obj.select_set(True)
bpy.context.view_layer.objects.active = armature
bpy.ops.export_scene.fbx(
    filepath=str(fbx_path),
    use_selection=True,
    object_types={"ARMATURE", "MESH"},
    add_leaf_bones=False,
    bake_anim=False,
    axis_forward="-Z",
    axis_up="Y",
    apply_unit_scale=True,
    use_armature_deform_only=True,
    mesh_smooth_type="FACE",
    path_mode="RELATIVE",
)
