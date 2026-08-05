#!/usr/bin/env python3
"""Generate the Siroino _Large military sheer-back romper checkpoint."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "siroino-military-sheer-romper-large"
PRODUCT_NAME = "Military Sheer-Back Romper for Siroino _Large"
REVISION = "panel-sewn-v3"
REFERENCE_SHA256 = "3f69a72daa79102c0af5679e2c54d4f078231bdab124314703e2626bcef0e460"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    return parser.parse_args(raw)


def repo_path(value: str) -> Path:
    path = (ROOT / value).resolve()
    if path != ROOT and ROOT not in path.parents:
        raise ValueError(f"path escapes repository: {value}")
    return path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def deterministic_guid(label: str) -> str:
    return hashlib.md5(f"image2outfit:{PRODUCT_ID}:{label}".encode()).hexdigest()


def load_job() -> tuple[Path, dict]:
    path = Path(parse_args().job).resolve()
    job = json.loads(path.read_text(encoding="utf-8-sig"))
    if job.get("id") != PRODUCT_ID:
        raise ValueError(f"unexpected job id: {job.get('id')!r}")
    return path, job


def prepare_directories(job: dict) -> dict[str, Path]:
    root = repo_path(job["productRoot"])
    paths = {
        "root": root,
        "source": root / "Source" / "Blender",
        "models": root / "Models",
        "textures": root / "Textures",
        "materials": root / "Materials",
        "prefab": root / "Prefab",
        "previews": root / "Previews",
        "poses": root / "Previews" / "Poses",
        "documentation": root / "Documentation",
        "evidence": root / "Evidence",
        "demo": root / "Demo",
        "editor": root / "Editor",
        "tests": root / "Tests",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def create_textures(directory: Path) -> dict[str, Path]:
    size = 256
    albedo = Image.new("RGB", (size, size), (13, 14, 17))
    draw = ImageDraw.Draw(albedo)
    for offset in range(-size, size * 2, 8):
        draw.line((offset, 0, offset - size, size), fill=(22, 23, 28), width=1)
    normal = Image.new("RGB", (size, size), (128, 128, 255))
    ndraw = ImageDraw.Draw(normal)
    for value in range(0, size, 10):
        ndraw.line((value, 0, value, size), fill=(136, 128, 252), width=1)
    roughness = Image.new("L", (size, size), 166)
    rdraw = ImageDraw.Draw(roughness)
    for value in range(0, size, 12):
        rdraw.line((0, value, size, value), fill=150, width=1)
    sheer = Image.new("RGBA", (size, size), (20, 21, 25, 54))
    sdraw = ImageDraw.Draw(sheer)
    for value in range(0, size, 9):
        sdraw.line((value, 0, value, size), fill=(46, 47, 52, 92), width=1)
        sdraw.line((0, value, size, value), fill=(46, 47, 52, 92), width=1)
    result = {
        "albedo": directory / "military_black_albedo.png",
        "normal": directory / "military_black_normal.png",
        "roughness": directory / "military_black_roughness.png",
        "sheer": directory / "sheer_mesh_albedo.png",
    }
    albedo.save(result["albedo"], optimize=True)
    normal.save(result["normal"], optimize=True)
    roughness.save(result["roughness"], optimize=True)
    sheer.save(result["sheer"], optimize=True)
    return result


def image_node(nodes, path: Path, non_color: bool = False):
    node = nodes.new("ShaderNodeTexImage")
    node.image = bpy.data.images.load(str(path), check_existing=True)
    if non_color:
        node.image.colorspace_settings.name = "Non-Color"
    return node


def fabric_material(textures: dict[str, Path]) -> bpy.types.Material:
    material = bpy.data.materials.new("MAT_Military_Black_Fabric")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Roughness"].default_value = 0.62
    if "Sheen Weight" in shader.inputs:
        shader.inputs["Sheen Weight"].default_value = 0.16
    color = image_node(nodes, textures["albedo"])
    rough = image_node(nodes, textures["roughness"], True)
    normal_image = image_node(nodes, textures["normal"], True)
    normal = nodes.new("ShaderNodeNormalMap")
    normal.inputs["Strength"].default_value = 0.2
    links.new(color.outputs["Color"], shader.inputs["Base Color"])
    links.new(rough.outputs["Color"], shader.inputs["Roughness"])
    links.new(normal_image.outputs["Color"], normal.inputs["Color"])
    links.new(normal.outputs["Normal"], shader.inputs["Normal"])
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    material.diffuse_color = (0.014, 0.015, 0.019, 1.0)
    return material


def simple_material(name: str, color, roughness: float, metallic: float = 0.0) -> bpy.types.Material:
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = color
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = metallic
    if metallic and "Coat Weight" in shader.inputs:
        shader.inputs["Coat Weight"].default_value = 0.25
        shader.inputs["Coat Roughness"].default_value = 0.12
    material.diffuse_color = color
    return material


def sheer_material(path: Path) -> bpy.types.Material:
    material = bpy.data.materials.new("MAT_Sheer_Back_Mesh")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    texture = image_node(nodes, path)
    shader.inputs["Base Color"].default_value = (0.02, 0.021, 0.026, 1.0)
    shader.inputs["Roughness"].default_value = 0.4
    shader.inputs["Alpha"].default_value = 0.28
    links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    links.new(texture.outputs["Alpha"], shader.inputs["Alpha"])
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    try:
        material.surface_render_method = "DITHERED"
    except (AttributeError, TypeError, ValueError):
        if hasattr(material, "blend_method"):
            material.blend_method = "BLEND"
    material.diffuse_color = (0.02, 0.021, 0.026, 0.28)
    return material


def create_armature() -> bpy.types.Object:
    data = bpy.data.armatures.new("SiroinoLarge_GarmentRig")
    armature = bpy.data.objects.new("Armature.1", data)
    bpy.context.collection.objects.link(armature)
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    definitions = [
        ("Hips.1", (0, 0, 0.66), (0, 0, 0.82), None),
        ("Spine.1", (0, 0, 0.82), (0, 0, 1.02), "Hips.1"),
        ("Chest.1", (0, 0, 1.02), (0, 0, 1.24), "Spine.1"),
        ("Neck.1", (0, 0, 1.24), (0, 0, 1.35), "Chest.1"),
        ("Head.1", (0, 0, 1.35), (0, 0, 1.57), "Neck.1"),
        ("UpperArm_L.1", (0.03, 0, 1.20), (0.34, 0, 1.15), "Chest.1"),
        ("LowerArm_L.1", (0.34, 0, 1.15), (0.61, 0, 1.12), "UpperArm_L.1"),
        ("UpperArm_R.1", (-0.03, 0, 1.20), (-0.34, 0, 1.15), "Chest.1"),
        ("LowerArm_R.1", (-0.34, 0, 1.15), (-0.61, 0, 1.12), "UpperArm_R.1"),
        ("UpperLeg_L.1", (0.075, 0, 0.66), (0.08, 0, 0.36), "Hips.1"),
        ("LowerLeg_L.1", (0.08, 0, 0.36), (0.08, 0, 0.05), "UpperLeg_L.1"),
        ("UpperLeg_R.1", (-0.075, 0, 0.66), (-0.08, 0, 0.36), "Hips.1"),
        ("LowerLeg_R.1", (-0.08, 0, 0.36), (-0.08, 0, 0.05), "UpperLeg_R.1"),
    ]
    bones = {}
    for name, head, tail, parent in definitions:
        bone = data.edit_bones.new(name)
        bone.head = head
        bone.tail = tail
        if parent:
            bone.parent = bones[parent]
        bones[name] = bone
    bpy.ops.object.mode_set(mode="OBJECT")
    armature.show_in_front = True
    armature.select_set(False)
    return armature


def add_material(obj: bpy.types.Object, material: bpy.types.Material) -> None:
    obj.data.materials.append(material)
    if obj.type == "MESH":
        for polygon in obj.data.polygons:
            polygon.use_smooth = True


def parent_to_bone(obj: bpy.types.Object, armature: bpy.types.Object, bone: str) -> None:
    matrix = obj.matrix_world.copy()
    obj.parent = armature
    obj.parent_type = "BONE"
    obj.parent_bone = bone
    obj.matrix_world = matrix


def finish_object(obj, material, armature=None, bone=None, role="garment"):
    add_material(obj, material)
    if armature and bone:
        parent_to_bone(obj, armature, bone)
    obj["image2outfit_role"] = role
    return obj


def cube(name, location, scale, material, armature=None, bone=None, bevel=0.008, role="garment"):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel:
        modifier = obj.modifiers.new("Tailored edge", "BEVEL")
        modifier.width = bevel
        modifier.segments = 2
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    return finish_object(obj, material, armature, bone, role)


def cylinder(name, location, radius, depth, material, rotation=(0, 0, 0), armature=None, bone=None, vertices=36, role="garment"):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=location, rotation=rotation)
    obj = bpy.context.object
    obj.name = name
    return finish_object(obj, material, armature, bone, role)


def sphere(name, location, radius, material, armature=None, bone=None, role="garment"):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = (radius, radius, radius)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return finish_object(obj, material, armature, bone, role)


def torus(name, location, major, minor, material, rotation=(0, 0, 0), scale=(1, 1, 1), armature=None, bone=None):
    bpy.ops.mesh.primitive_torus_add(major_radius=major, minor_radius=minor, major_segments=48, minor_segments=10, location=location, rotation=rotation)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return finish_object(obj, material, armature, bone)


def panel_object(name: str, vertices, faces, material, armature, bone, thickness=0.003):
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    finish_object(obj, material, armature, bone)
    modifier = obj.modifiers.new("Panel thickness", "SOLIDIFY")
    modifier.thickness = thickness
    modifier.offset = 0.0
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    return obj


def bodice(material, armature):
    vertices = [
        (-0.145, -0.085, 0.72), (0.145, -0.085, 0.72),
        (0.145, 0.076, 0.72), (-0.145, 0.076, 0.72),
        (-0.205, -0.102, 1.24), (0.205, -0.102, 1.24),
        (0.205, 0.091, 1.24), (-0.205, 0.091, 1.24),
    ]
    faces = [(0, 1, 5, 4), (0, 4, 7, 3), (1, 2, 6, 5), (0, 3, 2, 1), (4, 5, 6, 7)]
    return panel_object("Opaque_Military_Bodice", vertices, faces, material, armature, "Chest.1")


def sheer_back(material, armature):
    vertices = [(-0.19, 0.094, 0.79), (0.19, 0.094, 0.79), (0.19, 0.094, 1.22), (-0.19, 0.094, 1.22)]
    return panel_object("Sheer_Back_Panel", vertices, [(0, 1, 2, 3)], material, armature, "Chest.1", 0.0012)


def chain(name: str, points, material, armature):
    curve = bpy.data.curves.new(f"{name}_Curve", "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = 0.005
    curve.bevel_resolution = 2
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, value in zip(spline.points, points):
        point.co = (*value, 1.0)
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.convert(target="MESH")
    obj = bpy.context.object
    parent_to_bone(obj, armature, "Chest.1")
    obj["image2outfit_role"] = "garment"
    return obj


def build_garment(armature, fabric, sheer, gold):
    objects = [bodice(fabric, armature), sheer_back(sheer, armature)]
    objects.append(cube("Romper_Shorts", (0, 0.004, 0.60), (0.175, 0.105, 0.13), fabric, armature, "Hips.1", 0.018))
    objects.append(cube("Asymmetric_Front_Flap", (-0.044, -0.114, 0.59), (0.145, 0.012, 0.145), fabric, armature, "Hips.1", 0.012))
    objects.append(torus("Standing_Collar", (0, 0, 1.285), 0.092, 0.025, fabric, scale=(1.0, 0.76, 1.0), armature=armature, bone="Neck.1"))
    objects.append(torus("Waist_Belt", (0, 0, 0.755), 0.166, 0.018, fabric, scale=(1.0, 0.69, 1.0), armature=armature, bone="Hips.1"))
    for side, sign in (("L", 1), ("R", -1)):
        bone = f"UpperArm_{side}.1"
        objects.append(cylinder(f"Short_Sleeve_{side}", (sign * 0.255, 0, 1.115), 0.088, 0.26, fabric, (0, math.pi / 2, 0), armature, bone))
        objects.append(torus(f"Sleeve_Cuff_{side}", (sign * 0.375, 0, 1.10), 0.084, 0.012, fabric, (0, math.pi / 2, 0), (1, 0.78, 1), armature, bone))
        objects.append(cube(f"Epaulette_{side}", (sign * 0.18, -0.01, 1.235), (0.075, 0.06, 0.012), fabric, armature, "Chest.1", 0.008))
        objects.append(sphere(f"Epaulette_Button_{side}", (sign * 0.19, -0.075, 1.245), 0.018, gold, armature, "Chest.1"))
    objects.append(cube("Gold_Nameplate", (0.075, -0.116, 1.04), (0.058, 0.008, 0.017), gold, armature, "Chest.1", 0.006))
    objects.append(cube("Belt_Buckle", (0.035, -0.124, 0.755), (0.034, 0.010, 0.043), gold, armature, "Hips.1", 0.006))
    for index, (x, z) in enumerate(((-0.115, 1.19), (-0.115, 1.08), (-0.02, 0.91)), 1):
        objects.append(sphere(f"Front_Button_{index}", (x, -0.118, z), 0.016, gold, armature, "Chest.1" if z > 1 else "Hips.1"))
    for index, x in enumerate((-0.12, -0.075, -0.03, 0.015, 0.060, 0.105), 1):
        objects.append(torus(f"Belt_Eyelet_{index}", (x, -0.125, 0.755), 0.010, 0.003, gold, (math.pi / 2, 0, 0), armature=armature, bone="Hips.1"))
    paths = [
        [(0.185, -0.080, 1.225), (0.225, -0.115, 1.11), (0.175, -0.120, 1.00)],
        [(0.165, -0.084, 1.225), (0.205, -0.128, 1.08), (0.140, -0.122, 0.965)],
        [(0.145, -0.088, 1.225), (0.185, -0.134, 1.045), (0.105, -0.124, 0.94)],
    ]
    for index, points in enumerate(paths, 1):
        objects.append(chain(f"Shoulder_Chain_{index}", points, gold, armature))
    return objects


def build_preview_body(armature, skin):
    objects = [
        cube("Preview_Torso", (0, 0.015, 0.98), (0.13, 0.075, 0.27), skin, armature, "Chest.1", 0.06, "preview-body"),
        sphere("Preview_Head", (0, 0, 1.49), 0.11, skin, armature, "Head.1", "preview-body"),
        cube("Preview_Hips", (0, 0.015, 0.63), (0.14, 0.08, 0.12), skin, armature, "Hips.1", 0.06, "preview-body"),
    ]
    for side, sign in (("L", 1), ("R", -1)):
        objects.append(cylinder(f"Preview_Arm_{side}", (sign * 0.45, 0.015, 1.13), 0.055, 0.50, skin, (0, math.pi / 2, 0), armature, f"UpperArm_{side}.1", 28, "preview-body"))
        objects.append(cylinder(f"Preview_Leg_{side}", (sign * 0.08, 0.015, 0.29), 0.068, 0.58, skin, armature=armature, bone=f"UpperLeg_{side}.1", vertices=28, role="preview-body"))
    return objects


def clean_meshes(objects):
    for obj in objects:
        if obj.type != "MESH":
            continue
        mesh = bmesh.new()
        mesh.from_mesh(obj.data)
        bmesh.ops.remove_doubles(mesh, verts=list(mesh.verts), dist=1e-7)
        bmesh.ops.dissolve_degenerate(mesh, edges=list(mesh.edges), dist=1e-9)
        if mesh.faces:
            bmesh.ops.recalc_face_normals(mesh, faces=list(mesh.faces))
        mesh.to_mesh(obj.data)
        mesh.free()
        obj.data.update(calc_edges=True)


def look_at(obj: bpy.types.Object, target=(0, 0, 0.80)):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def configure_scene():
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 640
    scene.render.resolution_y = 640
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    if scene.world is None:
        scene.world = bpy.data.worlds.new("ReviewWorld")
    scene.world.color = (0.84, 0.85, 0.88)
    camera_data = bpy.data.cameras.new("ReviewCamera")
    camera_data.lens = 58
    camera = bpy.data.objects.new("ReviewCamera", camera_data)
    bpy.context.collection.objects.link(camera)
    scene.camera = camera
    for name, location, energy, size in (
        ("Key", (2.5, -3.1, 3.0), 1050, 3.0),
        ("Fill", (-2.7, -2.0, 2.2), 700, 2.8),
        ("Rim", (0.8, 2.8, 2.7), 900, 2.4),
    ):
        data = bpy.data.lights.new(name, "AREA")
        data.energy = energy
        data.shape = "DISK"
        data.size = size
        light = bpy.data.objects.new(name, data)
        light.location = location
        bpy.context.collection.objects.link(light)
        look_at(light)
    floor_material = simple_material("MAT_Review_Floor", (0.18, 0.19, 0.22, 1), 0.88)
    cube("Review_Floor", (0, 0, -0.035), (1.4, 1.4, 0.035), floor_material, bevel=0, role="review-stage")
    return camera


def render_views(camera, directory: Path):
    positions = {
        "front": (0.0, -3.0, 0.82),
        "back": (0.0, 3.0, 0.82),
        "left": (3.0, 0.0, 0.82),
        "right": (-3.0, 0.0, 0.82),
        "three-quarter": (2.15, -2.15, 0.88),
    }
    outputs = {}
    for name, position in positions.items():
        camera.location = position
        look_at(camera)
        path = directory / f"{name}.png"
        bpy.context.scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        outputs[name] = path
    return outputs


def compose_multiview(inputs, output: Path):
    cell = (400, 400)
    canvas = Image.new("RGB", (1200, 800), (238, 239, 242))
    draw = ImageDraw.Draw(canvas)
    for index, name in enumerate(("front", "three-quarter", "back", "left", "right")):
        image = Image.open(inputs[name]).convert("RGB")
        image.thumbnail(cell, Image.Resampling.LANCZOS)
        x = (index % 3) * cell[0]
        y = (index // 3) * cell[1]
        canvas.paste(image, (x + (cell[0] - image.width) // 2, y + (cell[1] - image.height) // 2))
        draw.text((x + 12, y + 12), name, fill=(34, 36, 42))
    canvas.save(output, "WEBP", quality=92, method=6)


def export_fbx(job, armature, garment):
    path = repo_path(job["fbxAssetPath"])
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    for obj in garment:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.export_scene.fbx(
        filepath=str(path), use_selection=True, object_types={"ARMATURE", "MESH"},
        apply_unit_scale=True, apply_scale_options="FBX_SCALE_UNITS", use_space_transform=True,
        add_leaf_bones=False, primary_bone_axis="Y", secondary_bone_axis="X",
        mesh_smooth_type="FACE", use_mesh_modifiers=True, bake_anim=False, path_mode="AUTO",
    )
    return path


def write_unity_prefabs(job):
    fbx = repo_path(job["fbxAssetPath"])
    prefab = repo_path(job["prefabAssetPath"])
    integrated = repo_path(job["integratedPrefabAssetPath"])
    fbx_guid = deterministic_guid("fbx")
    prefab_guid = deterministic_guid("prefab")
    integrated_guid = deterministic_guid("integrated-prefab")
    fbx.with_suffix(fbx.suffix + ".meta").write_text(
        f"""fileFormatVersion: 2
guid: {fbx_guid}
ModelImporter:
  serializedVersion: 22200
  internalIDToNameTable: []
  externalObjects: {{}}
  materials:
    materialImportMode: 1
    materialName: 0
    materialSearch: 1
    materialLocation: 1
  animations:
    legacyGenerateAnimations: 4
    bakeSimulation: 0
    resampleCurves: 1
    optimizeGameObjects: 0
  meshes:
    globalScale: 1
    meshCompression: 0
    addColliders: 0
    importBlendShapes: 1
    importCameras: 0
    importLights: 0
    fileIdsGeneration: 2
    generateSecondaryUV: 0
    useFileUnits: 1
    preserveHierarchy: 1
    skinWeightsMode: 0
    maxBonesPerVertex: 4
    minBoneWeight: 0.001
  tangentSpace:
    normalSmoothAngle: 60
    normalImportMode: 0
    tangentImportMode: 3
  importAnimation: 0
  animationType: 2
  userData: image2outfit {PRODUCT_ID}
  assetBundleName:
  assetBundleVariant:
""", encoding="utf-8")
    prefab.parent.mkdir(parents=True, exist_ok=True)
    prefab.write_text(
        f"""%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1001 &1001000000000000
PrefabInstance:
  m_ObjectHideFlags: 0
  serializedVersion: 2
  m_Modification:
    serializedVersion: 3
    m_TransformParent: {{fileID: 0}}
    m_Modifications:
    - target: {{fileID: 100000, guid: {fbx_guid}, type: 3}}
      propertyPath: m_Name
      value: {PRODUCT_NAME}
      objectReference: {{fileID: 0}}
    m_RemovedComponents: []
    m_RemovedGameObjects: []
    m_AddedGameObjects: []
    m_AddedComponents: []
  m_SourcePrefab: {{fileID: 100100000, guid: {fbx_guid}, type: 3}}
""", encoding="utf-8")
    prefab.with_suffix(prefab.suffix + ".meta").write_text(
        f"fileFormatVersion: 2\nguid: {prefab_guid}\nPrefabImporter:\n  externalObjects: {{}}\n  userData:\n  assetBundleName:\n  assetBundleVariant:\n", encoding="utf-8")
    integrated.write_text(
        f"""%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1001 &1001000000000000
PrefabInstance:
  m_ObjectHideFlags: 0
  serializedVersion: 2
  m_Modification:
    serializedVersion: 3
    m_TransformParent: {{fileID: 0}}
    m_Modifications:
    - target: {{fileID: 100000, guid: {prefab_guid}, type: 3}}
      propertyPath: m_Name
      value: Siroino_Large_MilitarySheerRomper
      objectReference: {{fileID: 0}}
    m_RemovedComponents: []
    m_RemovedGameObjects: []
    m_AddedGameObjects: []
    m_AddedComponents: []
  m_SourcePrefab: {{fileID: 100100000, guid: {prefab_guid}, type: 3}}
""", encoding="utf-8")
    integrated.with_suffix(integrated.suffix + ".meta").write_text(
        f"fileFormatVersion: 2\nguid: {integrated_guid}\nPrefabImporter:\n  externalObjects: {{}}\n  userData: Unity validation and Modular Avatar wiring pending\n  assetBundleName:\n  assetBundleVariant:\n", encoding="utf-8")


def mesh_metrics(objects):
    result = {"meshObjects": 0, "vertices": 0, "triangles": 0, "degenerateTriangles": 0, "boundaryEdges": 0, "maxBoneInfluences": 1, "unweightedVertices": 0}
    for obj in objects:
        if obj.type != "MESH":
            continue
        result["meshObjects"] += 1
        mesh = obj.data
        mesh.calc_loop_triangles()
        result["vertices"] += len(mesh.vertices)
        result["triangles"] += len(mesh.loop_triangles)
        edge_uses = {}
        for polygon in mesh.polygons:
            for index, vertex in enumerate(polygon.vertices):
                edge = tuple(sorted((vertex, polygon.vertices[(index + 1) % len(polygon.vertices)])))
                edge_uses[edge] = edge_uses.get(edge, 0) + 1
        result["boundaryEdges"] += sum(count == 1 for count in edge_uses.values())
        for triangle in mesh.loop_triangles:
            a, b, c = (mesh.vertices[index].co for index in triangle.vertices)
            if (b - a).cross(c - a).length_squared <= 1e-20:
                result["degenerateTriangles"] += 1
    return result


def write_contracts(job_path, job, directories, metrics, previews, fbx):
    manifest = {
        "schemaVersion": 1,
        "productId": PRODUCT_ID,
        "productName": PRODUCT_NAME,
        "status": "WORKING",
        "classification": "HOSTED_GENERATED_PREFAB_CHECKPOINT",
        "targetAdapterId": job["adapterId"],
        "productRoot": job["productRoot"],
        "outfitPrefabPath": job["prefabAssetPath"],
        "integratedPrefabPath": job["integratedPrefabAssetPath"],
        "previewPath": job["previewPaths"]["front"],
        "documentationPath": f"{job['productRoot']}/README.md",
        "sourceJobPath": job_path.relative_to(ROOT).as_posix(),
        "generatedAt": now_utc(),
        "blenderVersion": bpy.app.version_string,
        "constructionProfile": "panel-sewn",
        "designRevision": REVISION,
        "reference": {
            "sourceImageRedistributed": False,
            "sourceImageSha256": REFERENCE_SHA256,
            "sourceImageDimensions": [1200, 1022],
            "interpretation": "black military short romper with stand collar, asymmetric front, gold hardware, shoulder chains, belt, short sleeves, and sheer upper back",
        },
        "metrics": metrics,
        "technicalGates": {
            "blenderGeneration": "PASS", "fbxExport": "PASS", "fiveViewRender": "PASS",
            "unityPrefabYamlGenerated": "PASS", "unityImport": "PENDING", "prefabReload": "PENDING",
            "modularAvatar": "PENDING", "ndmf": "PENDING", "vrchatBuildAndTest": "PENDING",
            "humanVisualReview": "PENDING", "humanPoseReview": "PENDING", "humanRuntimeReview": "PENDING",
        },
        "handoff": {
            "resumable": True,
            "canonicalWorkspace": job["productRoot"],
            "resumeFrom": job["blendPath"],
            "doNotRebuildFromZero": True,
            "blockers": [
                "Import, save, and reload both generated Prefabs in Unity 2022.3.22f1.",
                "Wire and validate the Siroino _Large Modular Avatar/NDMF integration.",
                "Review actual target-avatar pose renders for fit, transparency, and hardware placement.",
                "Run VRChat Build & Test and capture runtime evidence before RELEASED status.",
            ],
        },
        "hashes": {"fbxSha256": digest(fbx), "frontPreviewSha256": digest(previews["front"])},
    }
    repo_path(job["productManifestPath"]).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pattern = {
        "schemaVersion": 1, "productId": PRODUCT_ID, "constructionProfile": "panel-sewn", "units": "m", "status": "GENERATED",
        "panels": [
            {"id": "bodice-opaque", "role": "opaque front and side shell"},
            {"id": "back-sheer", "role": "translucent upper-back inset"},
            {"id": "romper-lower", "role": "short lower-body coverage"},
            {"id": "front-flap", "role": "asymmetric front overlay"},
            {"id": "collar", "role": "standing collar"},
            {"id": "sleeve-left", "role": "short sleeve"},
            {"id": "sleeve-right", "role": "short sleeve"},
            {"id": "belt", "role": "waist belt"},
        ],
        "seams": [
            {"id": "back-left", "a": "bodice-opaque.back-left", "b": "back-sheer.left"},
            {"id": "back-right", "a": "bodice-opaque.back-right", "b": "back-sheer.right"},
            {"id": "waist", "a": "bodice-opaque.waist", "b": "romper-lower.waist"},
            {"id": "neckline", "a": "bodice-opaque.neckline", "b": "collar.lower"},
            {"id": "left-armhole", "a": "bodice-opaque.armhole-left", "b": "sleeve-left.cap"},
            {"id": "right-armhole", "a": "bodice-opaque.armhole-right", "b": "sleeve-right.cap"},
        ],
    }
    (directories["documentation"] / "pattern-spec.json").write_text(json.dumps(pattern, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    readme = f"""# {PRODUCT_NAME}

`WORKING` — generated Blend, FBX, Unity Prefab wrappers, PBR textures, five-view evidence, and pose evidence are tracked. Unity import/reload, Modular Avatar/NDMF integration, actual target-avatar review, VRChat Build & Test, and human approval remain pending.

The user-provided reference image is not redistributed. Its SHA-256 is `{REFERENCE_SHA256}` (1200×1022). The implementation preserves the defining visual grammar without claiming an exact commercial replica.

## Unity entry points

- Outfit Prefab: `{job['prefabAssetPath']}`
- Integration checkpoint: `{job['integratedPrefabAssetPath']}`
- FBX: `{job['fbxAssetPath']}`
- Blend: `{job['blendPath']}`
- Pattern/seam specification: `{job['productRoot']}/Documentation/pattern-spec.json`

The Prefab files are deterministic YAML wrappers. They are not Unity-validated until Unity 2022.3.22f1 imports, saves, and reloads them successfully.
"""
    (directories["root"] / "README.md").write_text(readme, encoding="utf-8")
    update_hashes(directories["root"])


def update_hashes(root: Path):
    lines = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "SOURCE_HASHES.txt":
            lines.append(f"{digest(path)}  {path.relative_to(root).as_posix()}")
    (root / "SOURCE_HASHES.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    job_path, job = load_job()
    directories = prepare_directories(job)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    textures = create_textures(directories["textures"])
    fabric = fabric_material(textures)
    sheer = sheer_material(textures["sheer"])
    gold = simple_material("MAT_Brushed_Gold", (0.61, 0.39, 0.09, 1), 0.22, 0.92)
    skin = simple_material("MAT_Preview_Skin", (0.78, 0.54, 0.41, 1), 0.56)
    armature = create_armature()
    garment = build_garment(armature, fabric, sheer, gold)
    build_preview_body(armature, skin)
    clean_meshes(garment)
    camera = configure_scene()
    previews = render_views(camera, directories["previews"])
    compose_multiview(previews, directories["previews"] / f"{PRODUCT_ID}-multiview.webp")
    fbx = export_fbx(job, armature, garment)
    write_unity_prefabs(job)
    blend = repo_path(job["blendPath"])
    blend.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend), compress=True)
    metrics = mesh_metrics(garment)
    if metrics["degenerateTriangles"]:
        raise RuntimeError(f"degenerate triangles remain: {metrics}")
    write_contracts(job_path, job, directories, metrics, previews, fbx)
    print(json.dumps({"productId": PRODUCT_ID, "status": "WORKING", "metrics": metrics}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
