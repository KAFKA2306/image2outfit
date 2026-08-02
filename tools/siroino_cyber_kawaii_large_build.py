#!/usr/bin/env python3
"""Build the Cyber Kawaii Layered Set for the Siroino _Large body profile.

The reference image is interpreted as a design brief rather than copied as a
brand product: white cropped blouse, detached sleeves, black/pink harness
accents, plaid pleated mini skirt, white ruffle underlayer, thigh-high legwear,
and small metallic hardware. All geometry is original and logo-free.
"""
from __future__ import annotations

import json
import math
import uuid
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector
from PIL import Image

import genworks_product_common as g
import siroino_strappy_knit_build as base

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "siroino-cyber-kawaii-large"


def repo_path(value: str) -> Path:
    return base.repo_path(value)


def image_node(nodes, path: Path, *, non_color: bool = False):
    node = nodes.new("ShaderNodeTexImage")
    node.image = bpy.data.images.load(str(path), check_existing=True)
    if non_color:
        node.image.colorspace_settings.name = "Non-Color"
    node.interpolation = "Linear"
    return node


def texture_material(name: str, albedo: Path, normal: Path, roughness: Path, *, sheen: float = 0.0):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Metallic"].default_value = 0.0
    shader.inputs["IOR"].default_value = 1.45
    if "Sheen Weight" in shader.inputs:
        shader.inputs["Sheen Weight"].default_value = sheen
        shader.inputs["Sheen Roughness"].default_value = 0.58
    color = image_node(nodes, albedo)
    rough = image_node(nodes, roughness, non_color=True)
    normal_image = image_node(nodes, normal, non_color=True)
    normal_map = nodes.new("ShaderNodeNormalMap")
    normal_map.inputs["Strength"].default_value = 0.45
    links.new(color.outputs["Color"], shader.inputs["Base Color"])
    links.new(rough.outputs["Color"], shader.inputs["Roughness"])
    links.new(normal_image.outputs["Color"], normal_map.inputs["Color"])
    links.new(normal_map.outputs["Normal"], shader.inputs["Normal"])
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    return material


def make_textures(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    size = 512
    white_albedo = Image.new("RGB", (size, size))
    white_normal = Image.new("RGB", (size, size))
    white_rough = Image.new("L", (size, size))
    plaid_albedo = Image.new("RGB", (size, size))
    plaid_normal = Image.new("RGB", (size, size))
    plaid_rough = Image.new("L", (size, size))
    pink_albedo = Image.new("RGB", (size, size))
    pink_normal = Image.new("RGB", (size, size))
    pink_rough = Image.new("L", (size, size))

    for y in range(size):
        for x in range(size):
            weave = math.sin(x * math.tau / 10.0) + math.sin(y * math.tau / 12.0)
            micro = math.sin(x * 0.43 + y * 0.31)
            white_value = max(205, min(255, int(240 + 4 * weave + 2 * micro)))
            white_albedo.putpixel((x, y), (white_value, white_value - 1, min(255, white_value + 3)))
            white_normal.putpixel((x, y), (int(128 + 8 * math.sin(x * 0.6)), int(128 + 8 * math.sin(y * 0.55)), 252))
            white_rough.putpixel((x, y), int(178 + 10 * micro))

            block_x = (x // 48) % 4
            block_y = (y // 48) % 4
            stripe_x = x % 48 < 8
            stripe_y = y % 48 < 8
            if stripe_x or stripe_y:
                color = (20, 22, 31)
            elif (block_x + block_y) % 2 == 0:
                color = (215, 217, 226)
            else:
                color = (69, 71, 84)
            if (x % 96 < 4) or (y % 96 < 4):
                color = (214, 96, 143)
            plaid_albedo.putpixel((x, y), color)
            plaid_normal.putpixel((x, y), (128 + int(5 * math.sin(x * 0.25)), 128 + int(5 * math.sin(y * 0.25)), 253))
            plaid_rough.putpixel((x, y), int(165 + 12 * micro))

            satin = 0.5 + 0.5 * math.sin((x + y * 0.32) * math.tau / 36.0)
            pink_albedo.putpixel((x, y), (235, int(115 + 22 * satin), int(171 + 24 * satin)))
            pink_normal.putpixel((x, y), (128 + int(10 * math.sin(x * 0.20)), 128, 252))
            pink_rough.putpixel((x, y), int(112 + 18 * (1.0 - satin)))

    outputs = {
        "white_albedo": directory / "white_fabric_albedo.png",
        "white_normal": directory / "white_fabric_normal.png",
        "white_rough": directory / "white_fabric_roughness.png",
        "plaid_albedo": directory / "plaid_albedo.png",
        "plaid_normal": directory / "plaid_normal.png",
        "plaid_rough": directory / "plaid_roughness.png",
        "pink_albedo": directory / "pink_satin_albedo.png",
        "pink_normal": directory / "pink_satin_normal.png",
        "pink_rough": directory / "pink_satin_roughness.png"
    }
    white_albedo.save(outputs["white_albedo"], optimize=True)
    white_normal.save(outputs["white_normal"], optimize=True)
    white_rough.save(outputs["white_rough"], optimize=True)
    plaid_albedo.save(outputs["plaid_albedo"], optimize=True)
    plaid_normal.save(outputs["plaid_normal"], optimize=True)
    plaid_rough.save(outputs["plaid_rough"], optimize=True)
    pink_albedo.save(outputs["pink_albedo"], optimize=True)
    pink_normal.save(outputs["pink_normal"], optimize=True)
    pink_rough.save(outputs["pink_rough"], optimize=True)
    return outputs


def finish_mesh(obj: bpy.types.Object, body: bpy.types.Object, armature: bpy.types.Object, *, smooth: bool = True) -> bpy.types.Object:
    obj.parent = armature
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True
    base.transfer_nearest_body_weights(obj, body)
    if smooth:
        for polygon in obj.data.polygons:
            polygon.use_smooth = True
    return obj


def ring_skirt(
    name: str,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    *,
    top_z: float,
    bottom_z: float,
    top_rx: float,
    top_ry: float,
    bottom_rx: float,
    bottom_ry: float,
    pleats: int,
    scallop: float = 0.0,
) -> bpy.types.Object:
    segments = pleats * 4
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    for ring_index, (z, rx, ry) in enumerate(((top_z, top_rx, top_ry), (bottom_z, bottom_rx, bottom_ry))):
        for index in range(segments):
            angle = math.tau * index / segments
            fold = 1.0 + 0.055 * math.sin(angle * pleats * 2)
            local_z = z
            if ring_index == 1 and scallop:
                local_z += scallop * (0.5 + 0.5 * math.cos(angle * pleats))
            vertices.append((rx * fold * math.cos(angle), ry * fold * math.sin(angle), local_z))
    for index in range(segments):
        next_index = (index + 1) % segments
        faces.append((index, next_index, segments + next_index, segments + index))
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    uv = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            ring = 0 if vertex_index < segments else 1
            index = vertex_index % segments
            uv.data[loop_index].uv = (index / segments, float(ring))
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj = finish_mesh(obj, body, armature)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    solidify = obj.modifiers.new("Fabric thickness", "SOLIDIFY")
    solidify.thickness = 0.0016
    solidify.offset = 0.0
    solidify.use_even_offset = True
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    bevel = obj.modifiers.new("Soft skirt edge", "BEVEL")
    bevel.width = 0.0008
    bevel.segments = 2
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    obj.select_set(False)
    return obj


def ellipsoid(
    name: str,
    location: tuple[float, float, float],
    scale: tuple[float, float, float],
    material: bpy.types.Material,
    body: bpy.types.Object,
    armature: bpy.types.Object,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(material)
    return finish_mesh(obj, body, armature)


def bow(
    name: str,
    center: tuple[float, float, float],
    scale: float,
    material: bpy.types.Material,
    body: bpy.types.Object,
    armature: bpy.types.Object,
) -> list[bpy.types.Object]:
    x, y, z = center
    left = ellipsoid(f"{name}_L", (x - scale * 0.78, y, z), (scale, scale * 0.26, scale * 0.56), material, body, armature)
    right = ellipsoid(f"{name}_R", (x + scale * 0.78, y, z), (scale, scale * 0.26, scale * 0.56), material, body, armature)
    bpy.ops.mesh.primitive_cube_add(location=(x, y - scale * 0.03, z), scale=(scale * 0.25, scale * 0.22, scale * 0.30))
    knot = bpy.context.active_object
    knot.name = f"{name}_Knot"
    knot.data.materials.append(material)
    bevel = knot.modifiers.new("Rounded knot", "BEVEL")
    bevel.width = scale * 0.09
    bevel.segments = 3
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    finish_mesh(knot, body, armature)
    return [left, right, knot]


def bone_midpoint(armature: bpy.types.Object, bone_name: str) -> Vector:
    bone = armature.data.bones.get(bone_name)
    if bone is None:
        raise RuntimeError(f"Required Siroino bone missing: {bone_name}")
    return armature.matrix_world @ ((bone.head_local + bone.tail_local) * 0.5)


def create_outfit(body: bpy.types.Object, armature: bpy.types.Object, materials: dict[str, bpy.types.Material]) -> list[bpy.types.Object]:
    white = materials["white"]
    plaid = materials["plaid"]
    pink = materials["pink"]
    black = materials["black"]
    silver = materials["silver"]
    garments: list[bpy.types.Object] = []

    blouse_front = base.extract_surface(
        body,
        armature,
        "White_Cropped_Blouse_Front",
        lambda c: 0.835 <= c.z <= 1.018 and c.y < 0.005 and abs(c.x) <= 0.145,
        white,
        0.0062,
    )
    blouse_back = base.extract_surface(
        body,
        armature,
        "White_Cropped_Blouse_Back",
        lambda c: 0.842 <= c.z <= 0.985 and c.y >= -0.006 and abs(c.x) <= 0.143,
        white,
        0.0060,
    )
    garments.extend((blouse_front, blouse_back))

    waist_panel = base.extract_surface(
        body,
        armature,
        "White_Waist_Base",
        lambda c: 0.705 <= c.z <= 0.792 and abs(c.x) <= 0.155,
        white,
        0.0052,
    )
    garments.append(waist_panel)

    plaid_skirt = ring_skirt(
        "Black_Pink_Plaid_Pleated_Skirt",
        body,
        armature,
        plaid,
        top_z=0.786,
        bottom_z=0.610,
        top_rx=0.145,
        top_ry=0.103,
        bottom_rx=0.238,
        bottom_ry=0.174,
        pleats=12,
    )
    underskirt = ring_skirt(
        "White_Ruffle_Underskirt",
        body,
        armature,
        white,
        top_z=0.655,
        bottom_z=0.555,
        top_rx=0.205,
        top_ry=0.150,
        bottom_rx=0.266,
        bottom_ry=0.195,
        pleats=16,
        scallop=0.015,
    )
    garments.extend((plaid_skirt, underskirt))

    stockings = base.extract_surface(
        body,
        armature,
        "White_Thigh_High_Stockings",
        lambda c: 0.045 <= c.z <= 0.505 and abs(c.x) >= 0.016,
        white,
        0.0045,
    )
    garments.append(stockings)

    for side_name in ("L", "R"):
        shoulder = bone_midpoint(armature, f"UpperArm_{side_name}")
        sign = -1 if side_name == "L" else 1
        shoulder.x += sign * 0.012
        puff = ellipsoid(
            f"White_Puff_Sleeve_{side_name}",
            tuple(shoulder),
            (0.075, 0.080, 0.090),
            white,
            body,
            armature,
        )
        garments.append(puff)

        lower = bone_midpoint(armature, f"LowerArm_{side_name}")
        warmer = ellipsoid(
            f"White_Detached_Sleeve_{side_name}",
            tuple(lower),
            (0.055, 0.060, 0.145),
            white,
            body,
            armature,
        )
        garments.append(warmer)

        x = -0.067 if side_name == "L" else 0.067
        thigh_loop = base.surface_cross_section_loop(body, 0.505, x - 0.043, x + 0.043, 0.006, 32)
        garments.append(base.curve_tube(f"Black_Thigh_Band_{side_name}", thigh_loop, 0.0030, black, armature, f"UpperLeg_{side_name}", cyclic=True))
        pink_loop = [(px, py - 0.002, pz - 0.012) for px, py, pz in thigh_loop]
        garments.append(base.curve_tube(f"Pink_Thigh_Trim_{side_name}", pink_loop, 0.0017, pink, armature, f"UpperLeg_{side_name}", cyclic=True))

    neck_y = base.body_front_y(body, 0.0, 1.005) - 0.012
    garments.append(base.curve_tube("Black_Neck_Ribbon", [(-0.040, neck_y, 1.030), (0.0, neck_y - 0.002, 0.952), (0.040, neck_y, 1.030)], 0.0028, black, armature, "Chest"))
    garments.extend(bow("Pink_Collar_Bow", (0.0, neck_y - 0.004, 0.965), 0.026, pink, body, armature))

    waist_y = base.body_front_y(body, 0.0, 0.770) - 0.014
    garments.append(base.curve_tube("Black_Waist_Harness", [(-0.135, waist_y, 0.782), (-0.090, waist_y - 0.003, 0.716), (0.0, waist_y - 0.004, 0.690), (0.090, waist_y - 0.003, 0.716), (0.135, waist_y, 0.782)], 0.0030, black, armature, "Hips"))
    for side, x in (("L", -0.155), ("R", 0.155)):
        garments.extend(bow(f"Pink_Skirt_Bow_{side}", (x, -0.030, 0.650), 0.022, pink, body, armature))
        garments.append(base.heart_curve(f"Silver_Heart_{side}", (x, -0.045, 0.700), 0.00062, silver, armature, "Hips"))

    hem_loop = base.ellipse_points((0.0, 0.0, 0.565), (0.266, 0.195), 96)
    garments.append(base.curve_tube("Pink_Underskirt_Hem", hem_loop, 0.0022, pink, armature, "Hips", cyclic=True))

    for obj in garments:
        if obj.type == "MESH" and obj.parent is None:
            finish_mesh(obj, body, armature)
    return garments


def clean_meshes(objects: list[bpy.types.Object]) -> None:
    for obj in objects:
        if obj.type != "MESH":
            continue
        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.dissolve_degenerate(bm, dist=1e-7, edges=list(bm.edges))
        if bm.faces:
            bmesh.ops.triangulate(bm, faces=list(bm.faces))
        loose = [vertex for vertex in bm.verts if not vertex.link_faces]
        if loose:
            bmesh.ops.delete(bm, geom=loose, context="VERTS")
        bm.to_mesh(mesh)
        bm.free()
        mesh.update(calc_edges=True)


def write_unity_sidecars(fbx: Path, prefab: Path, product_name: str) -> list[Path]:
    guid = uuid.uuid4().hex
    prefab_guid = uuid.uuid4().hex
    fbx_meta = fbx.with_suffix(fbx.suffix + ".meta")
    fbx_meta.write_text(
        f"""fileFormatVersion: 2
guid: {guid}
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
  meshes:
    globalScale: 1
    meshCompression: 0
    importBlendShapes: 1
    importCameras: 0
    importLights: 0
    weldVertices: 1
    preserveHierarchy: 1
    maxBonesPerVertex: 4
    minBoneWeight: 0.001
  tangentSpace:
    normalSmoothAngle: 60
    normalImportMode: 0
    tangentImportMode: 3
  importAnimation: 0
  animationType: 2
  userData: image2outfit Cyber Kawaii Layered Set for Siroino _Large
  assetBundleName:
  assetBundleVariant:
""",
        encoding="utf-8",
    )
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
    - target: {{fileID: 100000, guid: {guid}, type: 3}}
      propertyPath: m_Name
      value: {product_name}
      objectReference: {{fileID: 0}}
    m_RemovedComponents: []
    m_RemovedGameObjects: []
    m_AddedGameObjects: []
    m_AddedComponents: []
  m_SourcePrefab: {{fileID: 100100000, guid: {guid}, type: 3}}
""",
        encoding="utf-8",
    )
    prefab_meta = prefab.with_suffix(prefab.suffix + ".meta")
    prefab_meta.write_text(
        f"""fileFormatVersion: 2
guid: {prefab_guid}
PrefabImporter:
  externalObjects: {{}}
  userData:
  assetBundleName:
  assetBundleVariant:
""",
        encoding="utf-8",
    )
    return [fbx_meta, prefab, prefab_meta]


def main() -> int:
    _, job = base.load_job()
    base.clean_scene()
    source = repo_path(job["targetSourcePath"])
    product_root = repo_path(job["productRoot"])
    blend_path = repo_path(job["blendPath"])
    fbx_path = repo_path(job["fbxAssetPath"])
    prefab_path = repo_path(job["prefabAssetPath"])
    artifact_dir = repo_path(job["artifactDir"])
    preview_dir = product_root / "Previews"
    pose_dir = preview_dir / "Poses"
    texture_dir = product_root / "Textures"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    product_root.mkdir(parents=True, exist_ok=True)

    bpy.ops.import_scene.fbx(filepath=str(source), use_anim=False)
    body, armature = g.select_body_and_armature()
    armature.name = "SiroinoSotai_Armature"
    profile = g.apply_large_profile(body, job.get("bodyShapeProfile"))
    base.set_skin_material(body)

    textures = make_textures(texture_dir)
    materials = {
        "white": texture_material("MAT_White_Soft_Fabric", textures["white_albedo"], textures["white_normal"], textures["white_rough"], sheen=0.18),
        "plaid": texture_material("MAT_Black_Pink_Plaid", textures["plaid_albedo"], textures["plaid_normal"], textures["plaid_rough"], sheen=0.04),
        "pink": texture_material("MAT_Pink_Satin", textures["pink_albedo"], textures["pink_normal"], textures["pink_rough"], sheen=0.24),
        "black": base.plain_material("MAT_Black_Straps", (0.010, 0.011, 0.016, 1.0), roughness=0.28),
        "silver": base.plain_material("MAT_Silver_Hardware", (0.72, 0.76, 0.84, 1.0), roughness=0.17, metallic=0.94)
    }
    garments = create_outfit(body, armature, materials)
    clean_meshes(garments)

    improvement = g.improve_clearance(
        body,
        garments,
        targets=(0.0018, 0.0028, 0.0036),
        movable=lambda obj: "Silver_" not in obj.name,
    )
    clean_meshes(garments)
    measured = base.metrics(garments)

    blend_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)

    _, camera = g.pastel_studio()
    g.set_pose(armature, "neutral")
    previews = {name: repo_path(value) for name, value in job["previewPaths"].items()}
    g.render_five_views(camera, previews)
    multiview = preview_dir / "siroino-cyber-kawaii-large-multiview.webp"
    g.contact_sheet(
        previews,
        multiview,
        order=("front", "three-quarter", "left", "right", "back"),
        title="CYBER KAWAII LAYERED SET / SIROINO _LARGE",
    )
    pose_images = g.render_pose_set(armature, camera, pose_dir)
    pose_sheet = preview_dir / "siroino-cyber-kawaii-large-pose-review.webp"
    g.contact_sheet(
        pose_images,
        pose_sheet,
        order=("neutral", "arms-up", "arm-cross", "crouch", "sit", "twist"),
        title="POSE AND PENETRATION REVIEW",
    )

    g.reset_pose(armature)
    body.hide_render = True
    base.export_fbx(fbx_path, armature, garments)
    sidecars = write_unity_sidecars(fbx_path, prefab_path, job["productName"])

    passed = (
        measured["meshObjects"] >= 12
        and measured["vertices"] > 2500
        and measured["triangles"] > 3500
        and measured["unweightedVertices"] == 0
        and measured["weightSumErrors"] == 0
        and measured["degenerateTriangles"] == 0
        and measured["maxBoneInfluences"] <= 4
        and improvement[-1]["clearance"]["p01"] >= 0.0030
    )
    report = {
        "passed": passed,
        "productId": PRODUCT_ID,
        "productName": job["productName"],
        "targetProfile": profile,
        "targetAvatarAssetPath": job["targetAvatarAssetPath"],
        "targetSourcePath": job["targetSourcePath"],
        "blenderVersion": bpy.app.version_string,
        "metrics": measured,
        "improvementLoop": improvement,
        "views": {name: str(path.relative_to(ROOT)).replace("\\", "/") for name, path in previews.items()},
        "poseViews": {name: str(path.relative_to(ROOT)).replace("\\", "/") for name, path in pose_images.items()},
        "notes": [
            "The target must resolve to a Large-labelled Siroino prefab on the self-hosted runner.",
            "The standard PC FBX may be shared by size prefabs; official Large shape keys are baked before garment extraction.",
            "All preview and pose images are Blender renders of the generated FBX source scene.",
            "The design is original, logo-free, and based on the visual grammar of the supplied reference image."
        ]
    }
    g.write_json(artifact_dir / "product-build-report.json", report)
    g.write_json(artifact_dir / "improvement-loop.json", {"passes": improvement})

    manifest = {
        "schemaVersion": 1,
        "id": PRODUCT_ID,
        "productName": job["productName"],
        "target": "Siroino _Large",
        "status": "MODELED" if passed else "REJECTED",
        "designRevision": "v1-reference-interpretation-large-fit",
        "technicalGates": {
            "largeProfileResolved": "PASS",
            "blender": "PASS" if passed else "FAIL",
            "bodyClearance": "PASS" if improvement[-1]["clearance"]["p01"] >= 0.0030 else "FAIL",
            "fiveViewRender": "PASS",
            "poseRender": "PASS",
            "unityImport": "PENDING",
            "modularAvatar": "PENDING",
            "humanVisualReview": "PENDING",
            "humanPoseReview": "PENDING",
            "humanRuntimeReview": "PENDING"
        },
        "outputs": {
            "blend": job["blendPath"],
            "fbx": job["fbxAssetPath"],
            "prefab": job["prefabAssetPath"],
            "integratedPrefab": job["integratedPrefabAssetPath"],
            "multiview": str(multiview.relative_to(ROOT)).replace("\\", "/"),
            "poseReview": str(pose_sheet.relative_to(ROOT)).replace("\\", "/")
        }
    }
    g.write_json(repo_path(job["productManifestPath"]), manifest)

    readme = product_root / "README.md"
    readme.write_text(
        f"""# {job['productName']}

Target: **Siroino `_Large`**. The workflow requires a Large-labelled official prefab and applies the Large body shape profile before garment extraction.

## Design

- white cropped blouse with puff sleeves
- detached white arm sleeves
- black and pink neck ribbon
- black/pink plaid pleated mini skirt
- white ruffle underlayer
- black harness and thigh bands
- white thigh-high legwear
- pink bows and silver heart hardware

## Outputs

- Blender source: `{job['blendPath']}`
- FBX: `{job['fbxAssetPath']}`
- outfit Prefab: `{job['prefabAssetPath']}`
- integrated Prefab: `{job['integratedPrefabAssetPath']}`
- five-view render: `{manifest['outputs']['multiview']}`
- pose review: `{manifest['outputs']['poseReview']}`

The avatar package is private validation input and is never included in delivery assets.
""",
        encoding="utf-8",
    )

    hash_candidates = [blend_path, fbx_path, *sidecars, *textures.values(), *previews.values(), *pose_images.values(), multiview, pose_sheet, readme, repo_path(job["productManifestPath"])]
    (product_root / "SOURCE_HASHES.txt").write_text(
        "\n".join(f"{base.sha256(path)}  {path.relative_to(product_root)}" for path in hash_candidates if path.is_file()) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
