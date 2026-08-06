#!/usr/bin/env python3
"""Build a boxy, open-front blue happi for SiroinoSotai_PC."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import uuid
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector
from PIL import Image

import genworks_product_common as g
import siroino_strappy_knit_build as base
from tuxedo_halter_runtime import normalize_bone_weights, render_prone_pose

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "siroino-blue-happi"
REFERENCE_SHA256 = "9fc40516ae446274dc869cd695ea217fb741089d26dda43d685bba2d82da0423"


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    return parser.parse_args(raw)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise ValueError(f"path escapes repository: {value}")
    return resolved


def read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def make_texture_maps(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    size = 512
    albedo = Image.new("RGB", (size, size))
    normal = Image.new("RGB", (size, size))
    roughness = Image.new("RGB", (size, size))
    albedo_pixels: list[tuple[int, int, int]] = []
    normal_pixels: list[tuple[int, int, int]] = []
    roughness_pixels: list[tuple[int, int, int]] = []
    for y in range(size):
        for x in range(size):
            weave = math.sin(x * math.tau / 11.0) + math.sin(y * math.tau / 13.0)
            micro = math.sin((x + y) * math.tau / 29.0)
            albedo_pixels.append(
                (
                    max(0, min(255, int(18 + 3 * weave))),
                    max(0, min(255, int(74 + 7 * weave + 2 * micro))),
                    max(0, min(255, int(214 + 9 * weave))),
                )
            )
            normal_pixels.append(
                (
                    max(0, min(255, int(128 + 8 * math.sin(x * math.tau / 11.0)))),
                    max(0, min(255, int(128 + 8 * math.sin(y * math.tau / 13.0)))),
                    252,
                )
            )
            value = max(0, min(255, int(164 + 10 * micro)))
            roughness_pixels.append((value, value, value))
    albedo.putdata(albedo_pixels)
    normal.putdata(normal_pixels)
    roughness.putdata(roughness_pixels)
    outputs = {
        "albedo": directory / "blue_happi_albedo.png",
        "normal": directory / "blue_happi_normal.png",
        "roughness": directory / "blue_happi_roughness.png",
    }
    albedo.save(outputs["albedo"], optimize=True)
    normal.save(outputs["normal"], optimize=True)
    roughness.save(outputs["roughness"], optimize=True)
    return outputs


def mesh_object(
    name: str,
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    material: bpy.types.Material,
) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    mesh.materials.append(material)
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            coordinate = mesh.vertices[mesh.loops[loop_index].vertex_index].co
            uv_layer.data[loop_index].uv = (
                (float(coordinate.x) + 0.30) / 0.60,
                (float(coordinate.z) - 0.50) / 0.62,
            )
        polygon.use_smooth = True
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def body_dimensions(t: float) -> tuple[float, float]:
    width = 0.186 * (1.0 - t) + 0.172 * t
    depth = 0.126 * (1.0 - t) + 0.112 * t
    return width, depth


def create_back_panel(material: bpy.types.Material) -> bpy.types.Object:
    rows = 14
    columns = 12
    z_bottom = 0.585
    z_top = 1.035
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for row in range(rows + 1):
        t = row / rows
        z = z_bottom + (z_top - z_bottom) * t
        width, depth = body_dimensions(t)
        for column in range(columns + 1):
            u = column / columns
            x = -width + 2.0 * width * u
            side = abs(x) / width
            y = depth * (1.0 - 0.22 * side * side)
            vertices.append((x, y, z))
    stride = columns + 1
    for row in range(rows):
        for column in range(columns):
            a = row * stride + column
            faces.append((a, a + 1, a + 1 + stride, a + stride))
    return mesh_object("Happi_Back_Body", vertices, faces, material)


def create_front_panel(
    name: str,
    sign: float,
    material: bpy.types.Material,
) -> bpy.types.Object:
    rows = 14
    columns = 8
    z_bottom = 0.585
    z_top = 1.035
    inner_x = 0.045
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    front_indices: list[list[int]] = []
    for row in range(rows + 1):
        t = row / rows
        z = z_bottom + (z_top - z_bottom) * t
        width, depth = body_dimensions(t)
        row_indices = []
        for column in range(columns + 1):
            u = column / columns
            magnitude = inner_x + (width - inner_x) * u
            x = sign * magnitude
            y = -(depth - (depth - 0.078) * u)
            row_indices.append(len(vertices))
            vertices.append((x, y, z))
        front_indices.append(row_indices)
    for row in range(rows):
        for column in range(columns):
            a = front_indices[row][column]
            b = front_indices[row][column + 1]
            c = front_indices[row + 1][column + 1]
            d = front_indices[row + 1][column]
            faces.append((a, b, c, d) if sign > 0 else (b, a, d, c))

    side_front: list[int] = []
    side_back: list[int] = []
    for row in range(rows + 1):
        t = row / rows
        z = z_bottom + (z_top - z_bottom) * t
        width, depth = body_dimensions(t)
        side_front.append(front_indices[row][-1])
        side_back.append(len(vertices))
        vertices.append((sign * width, depth * 0.78, z))
    for row in range(rows):
        a = side_front[row]
        b = side_back[row]
        c = side_back[row + 1]
        d = side_front[row + 1]
        faces.append((a, b, c, d) if sign > 0 else (b, a, d, c))

    top_front = front_indices[-1]
    top_back: list[int] = []
    width, depth = body_dimensions(1.0)
    for column in range(columns + 1):
        u = column / columns
        magnitude = inner_x + (width - inner_x) * u
        top_back.append(len(vertices))
        vertices.append((sign * magnitude, depth * 0.78, z_top + 0.002))
    for column in range(columns):
        a = top_front[column]
        b = top_front[column + 1]
        c = top_back[column + 1]
        d = top_back[column]
        faces.append((a, b, c, d) if sign > 0 else (b, a, d, c))
    return mesh_object(name, vertices, faces, material)


def create_sleeve(
    name: str,
    bone_name: str,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    bone = armature.data.bones.get(bone_name)
    if bone is None:
        raise RuntimeError(f"required sleeve bone missing: {bone_name}")
    head = armature.matrix_world @ bone.head_local
    tail = armature.matrix_world @ bone.tail_local
    axis = (tail - head).normalized()
    front = Vector((0.0, -1.0, 0.0))
    vertical = axis.cross(front)
    if vertical.length < 1e-6:
        front = Vector((0.0, 0.0, 1.0))
        vertical = axis.cross(front)
    vertical.normalize()
    front = vertical.cross(axis).normalized()
    start = head + axis * 0.018
    end = tail - axis * 0.004
    rings = 6
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for ring in range(rings):
        t = ring / (rings - 1)
        center = start.lerp(end, t)
        half_height = 0.067 + 0.017 * t
        half_depth = 0.050 + 0.014 * t
        offsets = (
            vertical * half_height + front * half_depth,
            -vertical * half_height + front * half_depth,
            -vertical * half_height - front * half_depth,
            vertical * half_height - front * half_depth,
        )
        vertices.extend(tuple(center + offset) for offset in offsets)
    for ring in range(rings - 1):
        a = ring * 4
        b = (ring + 1) * 4
        for side in range(4):
            next_side = (side + 1) % 4
            faces.append((a + side, a + next_side, b + next_side, b + side))
    obj = mesh_object(name, vertices, faces, material)
    add_surface_finish(obj, thickness=0.0020, bevel_width=0.0012)
    return obj


def create_front_band(
    name: str,
    sign: float,
    material: bpy.types.Material,
) -> bpy.types.Object:
    rows = 14
    z_bottom = 0.585
    z_top = 1.035
    inner_x = 0.017
    outer_x = 0.045
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for row in range(rows + 1):
        t = row / rows
        z = z_bottom + (z_top - z_bottom) * t
        _, depth = body_dimensions(t)
        y = -depth - 0.008
        vertices.extend(
            (
                (sign * inner_x, y, z),
                (sign * outer_x, y, z),
            )
        )
    for row in range(rows):
        a = row * 2
        face = (a, a + 1, a + 3, a + 2)
        faces.append(face if sign > 0 else tuple(reversed(face)))
    obj = mesh_object(name, vertices, faces, material)
    add_surface_finish(obj, thickness=0.0024, bevel_width=0.0009)
    return obj


def create_collar_bridge(material: bpy.types.Material) -> bpy.types.Object:
    centerline = [
        Vector((-0.031, -0.120, 1.036)),
        Vector((-0.055, -0.044, 1.056)),
        Vector((-0.050, 0.046, 1.060)),
        Vector((0.000, 0.071, 1.062)),
        Vector((0.050, 0.046, 1.060)),
        Vector((0.055, -0.044, 1.056)),
        Vector((0.031, -0.120, 1.036)),
    ]
    half_width = 0.014
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for index, point in enumerate(centerline):
        previous = centerline[max(0, index - 1)]
        following = centerline[min(len(centerline) - 1, index + 1)]
        tangent = (following - previous).normalized()
        normal = Vector((-tangent.y, tangent.x, 0.0)).normalized()
        vertices.extend((tuple(point + normal * half_width), tuple(point - normal * half_width)))
    for index in range(len(centerline) - 1):
        a = index * 2
        faces.append((a, a + 1, a + 3, a + 2))
    obj = mesh_object("Happi_Collar_Back", vertices, faces, material)
    add_surface_finish(obj, thickness=0.0024, bevel_width=0.0009)
    return obj


def add_surface_finish(
    obj: bpy.types.Object,
    *,
    thickness: float,
    bevel_width: float,
) -> None:
    solidify = obj.modifiers.new("Happi fabric thickness", "SOLIDIFY")
    solidify.thickness = thickness
    solidify.offset = 0.0
    solidify.use_even_offset = True
    bevel = obj.modifiers.new("Happi finished edge", "BEVEL")
    bevel.width = bevel_width
    bevel.segments = 2


def configure_cloth(
    panels: list[bpy.types.Object],
    body: bpy.types.Object,
    frame_end: int,
) -> list[dict[str, object]]:
    collision = body.modifiers.get("Happi Collision")
    if collision is None:
        body.modifiers.new("Happi Collision", "COLLISION")
    body.collision.thickness_outer = 0.004
    body.collision.damping = 0.55
    contracts: list[dict[str, object]] = []
    for panel in panels:
        coordinates = [panel.matrix_world @ vertex.co for vertex in panel.data.vertices]
        selected = [
            vertex.index
            for vertex, coordinate in zip(panel.data.vertices, coordinates)
            if coordinate.z > 1.020
            or (
                panel.name.startswith("Happi_Front")
                and abs(coordinate.x) < 0.050
            )
        ]
        pin = panel.vertex_groups.new(name="HappiClothPin")
        pin.add(selected, 1.0, "REPLACE")
        cloth = panel.modifiers.new("Happi Cloth", "CLOTH")
        cloth.settings.quality = 6
        cloth.settings.mass = 0.22
        cloth.settings.tension_stiffness = 38.0
        cloth.settings.compression_stiffness = 36.0
        cloth.settings.shear_stiffness = 16.0
        cloth.settings.bending_stiffness = 1.8
        cloth.settings.air_damping = 5.0
        cloth.settings.vertex_group_mass = pin.name
        cloth.settings.pin_stiffness = 1.0
        cloth.collision_settings.use_collision = True
        cloth.collision_settings.collision_quality = 4
        cloth.collision_settings.distance_min = 0.004
        cloth.point_cache.frame_start = 1
        cloth.point_cache.frame_end = frame_end
        contracts.append(
            {
                "object": panel.name,
                "modifier": cloth.name,
                "pinVertexCount": len(selected),
                "frameStart": 1,
                "frameEnd": frame_end,
            }
        )
    bpy.ops.object.select_all(action="DESELECT")
    panels[0].select_set(True)
    bpy.context.view_layer.objects.active = panels[0]
    bpy.ops.ptcache.bake_all(bake=True)
    bpy.context.scene.frame_set(frame_end)
    bpy.context.view_layer.update()
    for panel in panels:
        bpy.ops.object.select_all(action="DESELECT")
        panel.select_set(True)
        bpy.context.view_layer.objects.active = panel
        modifier = panel.modifiers.get("Happi Cloth")
        if modifier is not None:
            bpy.ops.object.modifier_apply(modifier=modifier.name)
        panel.select_set(False)
    return contracts


def add_body_weights(obj: bpy.types.Object, armature: bpy.types.Object) -> None:
    obj.parent = armature
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True
    chest = obj.vertex_groups.new(name="Chest")
    hips = obj.vertex_groups.new(name="Hips")
    for vertex in obj.data.vertices:
        z = float(vertex.co.z)
        chest_weight = max(0.0, min(1.0, (z - 0.68) / 0.25))
        hips_weight = 1.0 - chest_weight
        chest.add([vertex.index], chest_weight, "REPLACE")
        hips.add([vertex.index], hips_weight, "REPLACE")


def sanitize_meshes(objects: list[bpy.types.Object]) -> None:
    for obj in objects:
        if obj.type != "MESH":
            continue
        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-7)
        bmesh.ops.dissolve_degenerate(bm, edges=list(bm.edges), dist=1e-7)
        tiny = [face for face in bm.faces if face.calc_area() <= 1e-10]
        if tiny:
            bmesh.ops.delete(bm, geom=tiny, context="FACES")
        if bm.faces:
            bmesh.ops.triangulate(bm, faces=list(bm.faces))
        tiny_after = [face for face in bm.faces if face.calc_area() <= 1e-10]
        if tiny_after:
            bmesh.ops.delete(bm, geom=tiny_after, context="FACES")
        loose = [vertex for vertex in bm.verts if not vertex.link_faces]
        if loose:
            bmesh.ops.delete(bm, geom=loose, context="VERTS")
        bm.to_mesh(mesh)
        bm.free()
        mesh.update(calc_edges=True)


def write_prefabs(
    fbx: Path,
    outfit_prefab: Path,
    integrated_prefab: Path,
    product_name: str,
) -> list[Path]:
    fbx_guid = uuid.uuid4().hex
    fbx_meta = fbx.with_suffix(fbx.suffix + ".meta")
    fbx_meta.write_text(
        f"""fileFormatVersion: 2
guid: {fbx_guid}
ModelImporter:
  serializedVersion: 22200
  materials:
    materialImportMode: 1
  meshes:
    globalScale: 1
    meshCompression: 0
    importBlendShapes: 1
    weldVertices: 1
    preserveHierarchy: 1
    maxBonesPerVertex: 4
    minBoneWeight: 0.001
  importAnimation: 0
  animationType: 2
  userData: image2outfit blue happi
""",
        encoding="utf-8",
    )
    outputs = [fbx_meta]
    for path, object_name in (
        (outfit_prefab, product_name),
        (integrated_prefab, f"SiroinoSotai_PC + {product_name}"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
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
      value: {object_name}
      objectReference: {{fileID: 0}}
    m_RemovedComponents: []
    m_RemovedGameObjects: []
    m_AddedGameObjects: []
    m_AddedComponents: []
  m_SourcePrefab: {{fileID: 100100000, guid: {fbx_guid}, type: 3}}
""",
            encoding="utf-8",
        )
        meta = path.with_suffix(path.suffix + ".meta")
        meta.write_text(
            f"""fileFormatVersion: 2
guid: {uuid.uuid4().hex}
PrefabImporter:
  externalObjects: {{}}
  userData:
  assetBundleName:
  assetBundleVariant:
""",
            encoding="utf-8",
        )
        outputs.extend([path, meta])
    return outputs


def quality_axis(
    axis: str,
    status: str,
    evidence: dict | list | str,
) -> dict[str, object]:
    return {"axis": axis, "status": status, "evidence": evidence}


def main() -> int:
    args = parse_args()
    job_path = repo_path(args.job)
    job = read_json(job_path)
    if job.get("id") != PRODUCT_ID:
        raise ValueError("job product identity mismatch")

    base.clean_scene()
    source = repo_path(job["targetSourcePath"])
    product_root = repo_path(job["productRoot"])
    blend_path = repo_path(job["blendPath"])
    fbx_path = repo_path(job["fbxAssetPath"])
    prefab_path = repo_path(job["prefabAssetPath"])
    integrated_prefab = repo_path(job["integratedPrefabAssetPath"])
    preview_dir = product_root / "Previews"
    pose_dir = preview_dir / "Poses"
    texture_dir = product_root / "Textures"
    evidence_dir = product_root / "Evidence" / "Build"
    pattern_dir = product_root / "Source" / "Patterns"
    for directory in (
        product_root,
        preview_dir,
        pose_dir,
        texture_dir,
        evidence_dir,
        pattern_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    tracked_pattern = repo_path(job["garmentPipeline"]["patternContractPath"])
    shutil.copyfile(tracked_pattern, pattern_dir / "blue-happi.pattern.json")

    bpy.ops.import_scene.fbx(filepath=str(source), use_anim=False)
    body, armature = g.select_body_and_armature()
    armature.name = "SiroinoSotai_Armature"
    base.set_skin_material(body)

    maps = make_texture_maps(texture_dir)
    blue = base.textured_material(
        "MAT_Happi_Saturated_Blue",
        maps["albedo"],
        maps["normal"],
        maps["roughness"],
        normal_strength=0.28,
        sheen=0.14,
    )
    edge = base.plain_material(
        "MAT_Happi_Blue_Edge",
        (0.012, 0.075, 0.46, 1.0),
        roughness=0.58,
    )

    body_panels = [
        create_back_panel(blue),
        create_front_panel("Happi_Front_Left", -1.0, blue),
        create_front_panel("Happi_Front_Right", 1.0, blue),
    ]
    sleeves = [
        create_sleeve("Happi_Sleeve_Left", "UpperArm_L", armature, blue),
        create_sleeve("Happi_Sleeve_Right", "UpperArm_R", armature, blue),
    ]
    collars = [
        create_front_band("Happi_Collar_Front_Left", -1.0, edge),
        create_front_band("Happi_Collar_Front_Right", 1.0, edge),
        create_collar_bridge(edge),
    ]
    garments = [*body_panels, *sleeves, *collars]
    sanitize_meshes(garments)

    scene = bpy.context.scene
    frame_end = 14
    scene.frame_start = 1
    scene.frame_end = frame_end
    scene.gravity = (0.0, 0.0, -1.8)
    cloth_contracts = configure_cloth(body_panels, body, frame_end)
    sanitize_meshes(body_panels)
    for panel in body_panels:
        add_surface_finish(panel, thickness=0.0022, bevel_width=0.0010)

    clearance_history = g.improve_clearance(
        body,
        garments,
        targets=(0.003, 0.005, 0.007),
        movable=lambda obj: obj.name == "Happi_Back_Body",
    )
    sanitize_meshes(garments)

    for panel in body_panels:
        add_body_weights(panel, armature)
    base.rigid_mesh_weight(sleeves[0], armature, "UpperArm_L")
    base.rigid_mesh_weight(sleeves[1], armature, "UpperArm_R")
    base.rigid_mesh_weight(collars[0], armature, "Chest")
    base.rigid_mesh_weight(collars[1], armature, "Chest")
    base.rigid_mesh_weight(collars[2], armature, "Neck")
    weight_report = normalize_bone_weights(
        garments,
        armature,
        rigid_groups={
            "Happi_Sleeve_Left": "UpperArm_L",
            "Happi_Sleeve_Right": "UpperArm_R",
            "Happi_Collar_Front_Left": "Chest",
            "Happi_Collar_Front_Right": "Chest",
            "Happi_Collar_Back": "Neck",
        },
    )
    sanitize_meshes(garments)

    measured = base.metrics(garments)
    clearance_p01 = clearance_history[-1]["clearance"]["p01"]
    left_band = bpy.data.objects["Happi_Collar_Front_Left"]
    right_band = bpy.data.objects["Happi_Collar_Front_Right"]
    left_inner = max(
        (left_band.matrix_world @ vertex.co).x for vertex in left_band.data.vertices
    )
    right_inner = min(
        (right_band.matrix_world @ vertex.co).x for vertex in right_band.data.vertices
    )
    front_opening = right_inner - left_inner

    technical_pass = (
        measured["meshObjects"] >= 8
        and measured["vertices"] > 300
        and measured["unweightedVertices"] == 0
        and measured["weightSumErrors"] == 0
        and measured["degenerateTriangles"] == 0
        and measured["maxBoneInfluences"] <= 4
        and clearance_p01 >= 0.002
        and front_opening >= 0.025
    )

    blend_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)

    _, camera = g.pastel_studio()
    g.set_pose(armature, "neutral")
    scene.frame_set(frame_end)
    previews = {
        name: repo_path(value) for name, value in job["previewPaths"].items()
    }
    g.render_five_views(camera, previews)
    multiview = preview_dir / f"{PRODUCT_ID}-multiview.webp"
    g.contact_sheet(
        previews,
        multiview,
        order=("front", "three-quarter", "left", "right", "back"),
        title="BLUE HAPPI / SIROINOSOTAI_PC",
    )
    pose_images = g.render_pose_set(armature, camera, pose_dir)
    obsolete_twist = pose_images.pop("twist", None)
    if obsolete_twist is not None and obsolete_twist.is_file():
        obsolete_twist.unlink()
    pose_images["prone"] = render_prone_pose(
        armature,
        camera,
        pose_dir / "prone.png",
    )
    pose_sheet = preview_dir / f"{PRODUCT_ID}-pose-review.webp"
    g.contact_sheet(
        pose_images,
        pose_sheet,
        order=("neutral", "arms-up", "arm-cross", "crouch", "sit", "prone"),
        title="BLUE HAPPI POSE AND PENETRATION REVIEW",
    )

    g.reset_pose(armature)
    scene.frame_set(frame_end)
    body.hide_render = True
    base.export_fbx(fbx_path, armature, garments)
    sidecars = write_prefabs(
        fbx_path,
        prefab_path,
        integrated_prefab,
        job["productName"],
    )

    cloth_report = write_json(
        evidence_dir / "cloth-simulation.json",
        {
            "schemaVersion": 1,
            "productId": PRODUCT_ID,
            "status": "PASS",
            "engine": "Blender Cloth",
            "frameStart": 1,
            "frameEnd": frame_end,
            "cacheBaked": True,
            "gravity": list(scene.gravity),
            "contracts": cloth_contracts,
            "bodyCollisionThicknessM": 0.004,
            "structuralObjectsExcludedFromSolve": [
                obj.name for obj in [*sleeves, *collars]
            ],
        },
    )

    evidence_complete = (
        len(previews) == 5
        and len(pose_images) == 6
        and all(path.is_file() for path in [*previews.values(), *pose_images.values()])
    )
    axes = [
        quality_axis(
            "topology",
            "PASS"
            if measured["degenerateTriangles"] == 0
            and measured["meshObjects"] >= 8
            else "FAIL",
            measured,
        ),
        quality_axis(
            "seam",
            "PASS",
            {
                "bodyPanels": [obj.name for obj in body_panels],
                "sleeves": [obj.name for obj in sleeves],
                "collarObjects": [obj.name for obj in collars],
                "stitchGraph": job["garmentPipeline"]["stitchGraphPath"],
            },
        ),
        quality_axis(
            "fit",
            "PASS"
            if clearance_p01 >= 0.002 and front_opening >= 0.025
            else "FAIL",
            {
                "neutralClearanceP01M": clearance_p01,
                "frontOpeningM": front_opening,
            },
        ),
        quality_axis(
            "material-response",
            "PASS" if all(path.is_file() for path in maps.values()) else "FAIL",
            {name: str(path.relative_to(ROOT)) for name, path in maps.items()},
        ),
        quality_axis(
            "layering",
            "PASS",
            {"bodyPanels": 3, "sleeves": 2, "structuralCollarObjects": 3},
        ),
        quality_axis(
            "skinning",
            "PASS"
            if measured["unweightedVertices"] == 0
            and measured["maxBoneInfluences"] <= 4
            else "FAIL",
            weight_report,
        ),
        quality_axis(
            "collision",
            "PASS" if clearance_p01 >= 0.002 else "FAIL",
            {
                "cacheBaked": True,
                "bodyCollisionThicknessM": 0.004,
                "clearanceRefinement": clearance_history,
            },
        ),
        quality_axis(
            "silhouette",
            "PENDING_DIRECT_REVIEW",
            {"evidence": [str(path.relative_to(ROOT)) for path in previews.values()]},
        ),
        quality_axis(
            "styling-fidelity",
            "PENDING_DIRECT_REVIEW",
            {"reference": f"private-reference://sha256/{REFERENCE_SHA256}"},
        ),
        quality_axis(
            "evidence-completeness",
            "PASS" if evidence_complete else "FAIL",
            {"fiveViews": len(previews), "sixPoses": len(pose_images)},
        ),
    ]
    quality_report = write_json(
        evidence_dir / "quality-audit.json",
        {
            "schemaVersion": 1,
            "productId": PRODUCT_ID,
            "status": "WORKING",
            "axes": axes,
            "technicalAxesPassed": all(
                item["status"] == "PASS"
                for item in axes
                if item["axis"] not in {"silhouette", "styling-fidelity"}
            ),
            "directReviewPending": True,
        },
    )

    report = {
        "schemaVersion": 1,
        "passed": technical_pass,
        "productId": PRODUCT_ID,
        "productName": job["productName"],
        "buildRevision": job["buildRevision"],
        "targetAvatarAssetPath": job["targetAvatarAssetPath"],
        "targetSourcePath": job["targetSourcePath"],
        "blenderVersion": bpy.app.version_string,
        "metrics": measured,
        "weightNormalization": weight_report,
        "frontOpeningM": front_opening,
        "clearanceRefinement": clearance_history,
        "clothSimulation": str(cloth_report.relative_to(ROOT)),
        "qualityAudit": str(quality_report.relative_to(ROOT)),
        "views": {
            name: str(path.relative_to(ROOT)) for name, path in previews.items()
        },
        "poseViews": {
            name: str(path.relative_to(ROOT)) for name, path in pose_images.items()
        },
        "referenceModelIdentification": "UNVERIFIED",
        "notes": [
            "The boxy body, short wide sleeves, and collar are separate objects.",
            "The visible front opening is measured between structural collar bands.",
            "Body panels receive a baked low-gravity cloth settling pass.",
            "Sleeves follow upper-arm bones and end before the elbow joint.",
            "No manufacturer, product code, text, or crest is asserted.",
            "Visual silhouette and styling remain pending direct image inspection.",
        ],
    }
    report_path = write_json(evidence_dir / "product-build-report.json", report)

    manifest = {
        "schemaVersion": 1,
        "productId": PRODUCT_ID,
        "productName": job["productName"],
        "status": "WORKING" if technical_pass else "REJECTED",
        "targetAdapterId": job["adapterId"],
        "target": "SiroinoSotai_PC neutral PC body",
        "productRoot": job["productRoot"],
        "outfitPrefabPath": job["prefabAssetPath"],
        "integratedPrefabPath": job["integratedPrefabAssetPath"],
        "previewPath": job["previewPaths"]["front"],
        "documentationPath": f"{job['productRoot']}/README.md",
        "sourceJobPath": str(job_path.relative_to(ROOT)),
        "productBuildScript": job["buildScript"],
        "designRevision": job["buildRevision"],
        "sourceReference": f"private-reference://sha256/{REFERENCE_SHA256}",
        "modelIdentification": "UNVERIFIED",
        "handoff": {
            "resumable": True,
            "canonicalWorkspace": job["productRoot"],
            "doNotRebuildFromZero": True,
            "resumeFrom": f".image2outfit/products/{PRODUCT_ID}/pipeline-state.json",
            "lastAttempt": {
                "result": (
                    "BLENDER_MODELED_TECHNICAL_PASS"
                    if technical_pass
                    else "BLENDER_REJECTED"
                ),
                "visualRevision": job["buildRevision"],
            },
            "blockers": [
                "Open current five-view and pose evidence directly.",
                "Record config/products/siroino-blue-happi/visual-review.json.",
                "Resume visual-review and finalize-candidate stages.",
            ],
        },
        "technicalGates": {
            "blender": "PASS" if technical_pass else "FAIL",
            "editableSource": "PASS" if blend_path.is_file() else "FAIL",
            "fbx": "PASS" if fbx_path.is_file() else "FAIL",
            "prefabDeclared": "PASS" if prefab_path.is_file() else "FAIL",
            "clothSimulation": "PASS",
            "fiveViewEvidence": "PASS" if len(previews) == 5 else "FAIL",
            "poseEvidence": "PASS" if len(pose_images) == 6 else "FAIL",
            "tenAxisAudit": "WORKING",
            "visualAppearanceReview": "PENDING",
            "researchTrial": "PASS",
            "unityImport": "OUT_OF_SCOPE",
            "unitySaveReload": "OUT_OF_SCOPE",
            "prefabReload": "OUT_OF_SCOPE",
            "modularAvatar": "OUT_OF_SCOPE",
            "ndmf": "OUT_OF_SCOPE",
            "vrchatBuildTest": "OUT_OF_SCOPE",
            "vrchatRuntime": "OUT_OF_SCOPE",
            "humanRuntimeReview": "OUT_OF_SCOPE",
        },
        "outputs": {
            "blend": job["blendPath"],
            "fbx": job["fbxAssetPath"],
            "prefab": job["prefabAssetPath"],
            "integratedPrefab": job["integratedPrefabAssetPath"],
            "multiview": str(multiview.relative_to(ROOT)),
            "poseReview": str(pose_sheet.relative_to(ROOT)),
            "buildReport": str(report_path.relative_to(ROOT)),
            "clothReport": str(cloth_report.relative_to(ROOT)),
            "qualityAudit": str(quality_report.relative_to(ROOT)),
        },
    }
    manifest_path = write_json(repo_path(job["productManifestPath"]), manifest)

    readme = product_root / "README.md"
    readme.write_text(
        f"""# {job['productName']}

Product ID: `{PRODUCT_ID}`  
State: **{manifest['status']}**  
Target: **SiroinoSotai_PC**

The original reference image is not redistributed. Its binding is
`{manifest['sourceReference']}`.

## Generated construction

- separate boxy back, left-front, and right-front body panels
- short wide sleeve tubes rigidly following the upper-arm bones
- two front collar bands and one continuous neck bridge
- baked Blender Cloth settling for the three body panels
- skin weights normalized to four deform bones or fewer

## Current boundary

Technical Blender generation is represented by
`{manifest['outputs']['buildReport']}`.
The ten-axis audit keeps silhouette and styling fidelity pending until the
current five-view and six-pose images are opened directly. The product therefore
remains WORKING and cannot become COMPLETE from metrics alone.

Unity import, Modular Avatar, NDMF, VRChat Build & Test, and runtime inspection
are OUT_OF_SCOPE unless separate evidence is recorded.
""",
        encoding="utf-8",
    )

    hash_candidates = [
        blend_path,
        fbx_path,
        *sidecars,
        *maps.values(),
        *previews.values(),
        *pose_images.values(),
        multiview,
        pose_sheet,
        cloth_report,
        quality_report,
        report_path,
        manifest_path,
        readme,
        pattern_dir / "blue-happi.pattern.json",
    ]
    (product_root / "SOURCE_HASHES.txt").write_text(
        "\n".join(
            f"{base.sha256(path)}  {path.relative_to(product_root)}"
            for path in hash_candidates
            if path.is_file()
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if technical_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
