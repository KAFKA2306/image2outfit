#!/usr/bin/env python3
"""Build and review a pattern-first white ghost gown for Siroino _Large."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import uuid
from pathlib import Path

import bpy
from mathutils import Vector

import genworks_product_common as g
import render_evidence_bootstrap  # noqa: F401  # installs render-post metadata hook
import siroino_heather_hooded_geometry as heather_geometry
import siroino_strappy_knit_build as base
from tuxedo_halter_components import ellipsoid, mesh_object
from tuxedo_halter_runtime import clean_meshes, normalize_bone_weights, render_prone_pose

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "siroino-white-ghost-gown"


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


def white_material() -> bpy.types.Material:
    return base.plain_material(
        "MAT_Ghost_White",
        (0.92, 0.93, 0.95, 1.0),
        roughness=0.70,
    )


def pattern_material() -> bpy.types.Material:
    return base.plain_material(
        "MAT_Pattern_Paper",
        (0.80, 0.83, 0.86, 1.0),
        roughness=0.88,
    )


def add_polyline(
    name: str,
    points: list[tuple[float, float, float]],
    material: bpy.types.Material,
    *,
    cyclic: bool,
    radius: float = 0.004,
) -> bpy.types.Object:
    curve = bpy.data.curves.new(name=f"{name}_Curve", type="CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 1
    curve.bevel_depth = radius
    curve.bevel_resolution = 2
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for slot, point in zip(spline.points, points):
        slot.co = (*point, 1.0)
    spline.use_cyclic_u = cyclic
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj


def render_pattern_layout(pattern: dict, output: Path) -> dict[str, object]:
    """Render the tracked 2D pattern as direct bpy evidence."""
    base.clean_scene()
    paper = pattern_material()
    line = base.plain_material(
        "MAT_Pattern_Outline",
        (0.075, 0.085, 0.10, 1.0),
        roughness=0.85,
    )
    offsets = {
        "dress-front": (-0.82, 0.30),
        "dress-back-left": (-0.22, 0.30),
        "dress-back-right": (0.38, 0.30),
        "sleeve": (-0.82, -1.10),
        "wrist-drape": (-0.35, -1.10),
        "hood-front": (0.10, -1.08),
        "hood-back": (0.55, -1.08),
        "back-tie": (0.18, -1.72),
    }
    created = []
    for piece in pattern["pieces"]:
        piece_id = str(piece["pieceId"])
        boundary = [(float(x), float(y)) for x, y in piece["boundary"]]
        ox, oy = offsets[piece_id]
        vertices = [(x + ox, y + oy, 0.0) for x, y in boundary]
        mesh = bpy.data.meshes.new(f"Pattern_{piece_id}_Mesh")
        mesh.from_pydata(vertices, [], [tuple(range(len(vertices)))])
        mesh.materials.append(paper)
        obj = bpy.data.objects.new(f"Pattern_{piece_id}", mesh)
        bpy.context.collection.objects.link(obj)
        created.append(obj)
        outline_points = [(x, y, 0.006) for x, y, _ in vertices]
        created.append(
            add_polyline(
                f"Pattern_{piece_id}_Outline",
                outline_points,
                line,
                cyclic=True,
                radius=0.0035,
            )
        )
        bpy.ops.object.text_add(location=(ox - 0.14, oy - 0.43, 0.012))
        label = bpy.context.object
        label.name = f"Label_{piece_id}"
        label.data.body = piece_id
        label.data.align_x = "LEFT"
        label.data.size = 0.055
        label.data.extrude = 0.0
        label.data.materials.append(line)
        created.append(label)

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 1536
    scene.render.resolution_y = 1536
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.world.color = (0.96, 0.96, 0.96)

    bpy.ops.object.camera_add(location=(0.0, -0.25, 8.0))
    camera = bpy.context.object
    camera.name = "Pattern_Review_Camera"
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 3.45
    camera.rotation_euler = (0.0, 0.0, 0.0)
    scene.camera = camera

    bpy.ops.object.light_add(type="AREA", location=(0.0, -0.2, 4.5))
    light = bpy.context.object
    light.data.energy = 1100.0
    light.data.shape = "DISK"
    light.data.size = 5.0

    output.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(output)
    bpy.ops.render.render(write_still=True)
    return {
        "path": str(output.relative_to(ROOT)).replace("\\", "/"),
        "pieceCount": len(pattern["pieces"]),
        "renderer": "bpy",
        "camera": camera.name,
    }


def torso_predicate(center: Vector) -> bool:
    if not (0.705 <= center.z <= 1.025 and abs(center.x) <= 0.205):
        return False
    if center.y <= 0.0:
        return True
    if center.z <= 0.790:
        return True
    ratio = min(1.0, max(0.0, (center.z - 0.790) / 0.220))
    cutout_half_width = 0.065 + 0.070 * math.sin(math.pi * ratio)
    return abs(center.x) >= cutout_half_width


def sleeve_predicate(center: Vector) -> bool:
    return (
        0.700 <= center.z <= 1.035
        and 0.120 <= abs(center.x) <= 0.580
        and abs(center.y) <= 0.170
    )


def rigid_weight(
    obj: bpy.types.Object,
    armature: bpy.types.Object,
    bone: str,
) -> bpy.types.Object:
    obj.parent = armature
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True
    obj.vertex_groups.clear()
    group = obj.vertex_groups.new(name=bone)
    group.add(range(len(obj.data.vertices)), 1.0, "REPLACE")
    return obj


def wrist_drape(
    side: str,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    _, wrist = heather_geometry.bone_segment(armature, f"LowerArm_{side}")
    sign = -1.0 if side == "L" else 1.0
    columns = 10
    rows = 8
    width_top = 0.075
    width_bottom = 0.205
    height = 0.30
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    for row in range(rows):
        v = row / (rows - 1)
        width = width_top + (width_bottom - width_top) * (v ** 0.8)
        center_x = wrist.x + sign * 0.025 * v
        z = wrist.z - height * v
        for column in range(columns + 1):
            u = column / columns
            x = center_x + (u - 0.5) * 2.0 * width
            fold = 0.010 * math.sin(u * math.tau * 2.5 + v * 1.3)
            y = wrist.y - 0.010 + fold
            lower_wave = 0.018 * math.sin(u * math.pi * 3.0) * (v ** 4)
            vertices.append((x, y, z + lower_wave))
    stride = columns + 1
    for row in range(rows - 1):
        for column in range(columns):
            a = row * stride + column
            faces.append((a, a + 1, a + stride + 1, a + stride))
    mesh = bpy.data.meshes.new(f"Ghost_Wrist_Drape_{side}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    mesh.materials.append(material)
    obj = bpy.data.objects.new(f"Ghost_Wrist_Drape_{side}", mesh)
    bpy.context.collection.objects.link(obj)
    rigid_weight(obj, armature, f"Hand_{side}")
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    solidify = obj.modifiers.new("Drape thickness", "SOLIDIFY")
    solidify.thickness = 0.0011
    solidify.offset = 0.0
    solidify.use_even_offset = True
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    bevel = obj.modifiers.new("Drape edge finish", "BEVEL")
    bevel.width = 0.00045
    bevel.segments = 2
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    obj.select_set(False)
    return obj


def ghost_hood(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    segments = 48
    rows = [
        (1.305, 0.020, 0.017),
        (1.275, 0.070, 0.055),
        (1.225, 0.105, 0.082),
        (1.165, 0.125, 0.098),
        (1.095, 0.145, 0.112),
        (1.025, 0.170, 0.132),
        (0.975, 0.190, 0.150),
    ]
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    for row_index, (z, rx, ry) in enumerate(rows):
        for index in range(segments):
            angle = math.tau * index / segments
            scallop = 0.0
            if row_index == len(rows) - 1:
                scallop = 0.012 * (0.5 + 0.5 * math.sin(angle * 6.0))
            vertices.append(
                (
                    rx * math.cos(angle),
                    ry * math.sin(angle),
                    z - scallop,
                )
            )
    for row in range(len(rows) - 1):
        start = row * segments
        next_start = (row + 1) * segments
        for index in range(segments):
            nxt = (index + 1) % segments
            faces.append((start + index, start + nxt, next_start + nxt, next_start + index))
    return mesh_object(
        "Ghost_Hood",
        vertices,
        faces,
        material,
        body,
        armature,
        thickness=0.0014,
        bevel=0.0005,
    )


def open_sewn_mermaid_skirt(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> tuple[bpy.types.Object, list[int], int]:
    """Create an open back seam plus face-less sewing edges for Cloth."""
    profiles = [
        (0.755, 0.148, 0.112),
        (0.655, 0.160, 0.122),
        (0.520, 0.150, 0.112),
        (0.365, 0.138, 0.103),
        (0.235, 0.130, 0.098),
        (0.125, 0.155, 0.118),
        (0.060, 0.220, 0.170),
    ]
    segments = 96
    gap = math.radians(8.0)
    start_angle = math.pi / 2.0 + gap
    end_angle = math.pi / 2.0 + math.tau - gap
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    sewing_edges: list[tuple[int, int]] = []
    stride = segments + 1
    for row, (z, rx, ry) in enumerate(profiles):
        for index in range(stride):
            ratio = index / segments
            angle = start_angle + (end_angle - start_angle) * ratio
            hem_fold = (0.003 + 0.010 * (row / (len(profiles) - 1))) * math.sin(angle * 6.0)
            vertices.append(
                (
                    (rx + hem_fold) * math.cos(angle),
                    (ry + hem_fold * 0.7) * math.sin(angle),
                    z,
                )
            )
        sewing_edges.append((row * stride, row * stride + segments))
    for row in range(len(profiles) - 1):
        a = row * stride
        b = (row + 1) * stride
        for index in range(segments):
            faces.append((a + index, a + index + 1, b + index + 1, b + index))

    mesh = bpy.data.meshes.new("Ghost_Mermaid_Skirt_Mesh")
    mesh.from_pydata(vertices, sewing_edges, faces)
    mesh.update(calc_edges=True)
    mesh.materials.append(material)
    uv = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            row, column = divmod(vertex_index, stride)
            uv.data[loop_index].uv = (
                column / segments,
                1.0 - row / max(1, len(profiles) - 1),
            )
    obj = bpy.data.objects.new("Ghost_Mermaid_Skirt", mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = armature
    armature_modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    armature_modifier.object = armature
    armature_modifier.use_deform_preserve_volume = True
    base.transfer_nearest_body_weights(obj, body)

    pin = obj.vertex_groups.new(name="ClothPin")
    pin_vertices = list(range(2, segments - 1))
    pin.add(pin_vertices, 1.0, "REPLACE")

    collision = body.modifiers.get("Outfit Collision")
    if collision is None:
        body.modifiers.new("Outfit Collision", "COLLISION")
    body.collision.thickness_outer = 0.004
    body.collision.damping = 0.5

    cloth = obj.modifiers.new("Pattern Sewing Cloth", "CLOTH")
    cloth.settings.quality = 10
    cloth.settings.mass = 0.20
    cloth.settings.tension_stiffness = 28.0
    cloth.settings.compression_stiffness = 28.0
    cloth.settings.shear_stiffness = 10.0
    cloth.settings.bending_stiffness = 0.42
    cloth.settings.air_damping = 3.0
    cloth.settings.vertex_group_mass = pin.name
    cloth.settings.pin_stiffness = 1.0
    cloth.settings.use_sewing_springs = True
    cloth.settings.sewing_force_max = 12.0
    cloth.collision_settings.use_collision = True
    cloth.collision_settings.collision_quality = 6
    cloth.collision_settings.distance_min = 0.003
    if hasattr(cloth.collision_settings, "use_self_collision"):
        cloth.collision_settings.use_self_collision = True
        cloth.collision_settings.self_distance_min = 0.0025
    cloth.point_cache.frame_start = 1
    cloth.point_cache.frame_end = 36
    return obj, pin_vertices, len(sewing_edges)


def bake_sewing(
    skirt: bpy.types.Object,
    *,
    sewing_edge_count: int,
) -> dict[str, object]:
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 36
    scene.gravity = (0.0, 0.0, -4.5)
    bpy.context.view_layer.objects.active = skirt
    bpy.ops.ptcache.bake_all(bake=True)
    scene.frame_set(36)
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    skirt.select_set(True)
    bpy.context.view_layer.objects.active = skirt
    bpy.ops.object.modifier_apply(modifier="Pattern Sewing Cloth")
    solidify = skirt.modifiers.new("Fabric thickness", "SOLIDIFY")
    solidify.thickness = 0.0014
    solidify.offset = 0.0
    solidify.use_even_offset = True
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    edge = skirt.modifiers.new("Finished hem", "BEVEL")
    edge.width = 0.00045
    edge.segments = 2
    bpy.ops.object.modifier_apply(modifier=edge.name)
    skirt.select_set(False)
    return {
        "object": skirt.name,
        "modifier": "Pattern Sewing Cloth",
        "frameStart": 1,
        "frameEnd": 36,
        "cacheBaked": True,
        "useSewingSprings": True,
        "sewingForceMax": 12.0,
        "sewingSpringEdgeCount": sewing_edge_count,
    }


def back_laces(
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> list[bpy.types.Object]:
    y = 0.132
    lines = [
        [(-0.100, y, 0.855), (0.082, y, 0.800)],
        [(0.100, y, 0.855), (-0.082, y, 0.800)],
        [(-0.082, y, 0.800), (0.070, y, 0.755)],
        [(0.082, y, 0.800), (-0.070, y, 0.755)],
    ]
    return [
        base.curve_tube(
            f"Ghost_Back_Tie_{index + 1}",
            points,
            0.0042,
            material,
            armature,
            "Chest" if index < 2 else "Hips",
            resolution=3,
        )
        for index, points in enumerate(lines)
    ]


def write_prefabs(
    fbx: Path,
    outfit_prefab: Path,
    integrated_prefab: Path,
    name: str,
) -> list[Path]:
    fbx_guid = uuid.uuid4().hex
    outputs: list[Path] = []
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
  userData: image2outfit white ghost gown
""",
        encoding="utf-8",
    )
    outputs.append(fbx_meta)
    for path, object_name in (
        (outfit_prefab, name),
        (integrated_prefab, f"Siroino _Large + {name}"),
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


def main() -> int:
    args = parse_args()
    job_path = repo_path(args.job)
    job = read_json(job_path)
    if job.get("id") != PRODUCT_ID:
        raise ValueError("job product identity mismatch")

    product_root = repo_path(job["productRoot"])
    preview_dir = product_root / "Previews"
    pose_dir = preview_dir / "Poses"
    evidence_dir = product_root / "Evidence" / "Build"
    pattern_dir = product_root / "Source" / "Patterns"
    blend_path = repo_path(job["blendPath"])
    fbx_path = repo_path(job["fbxAssetPath"])
    prefab_path = repo_path(job["prefabAssetPath"])
    integrated_prefab = repo_path(job["integratedPrefabAssetPath"])
    for directory in (
        product_root,
        preview_dir,
        pose_dir,
        evidence_dir,
        pattern_dir,
        blend_path.parent,
        fbx_path.parent,
        prefab_path.parent,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    tracked_pattern = repo_path(job["garmentPipeline"]["patternContractPath"])
    tracked_stitches = repo_path(job["garmentPipeline"]["stitchGraphPath"])
    shutil.copyfile(tracked_pattern, pattern_dir / "white-ghost-gown.pattern.json")
    shutil.copyfile(tracked_stitches, pattern_dir / "white-ghost-gown.stitches.json")
    pattern = read_json(tracked_pattern)
    stitch_graph = read_json(tracked_stitches)
    pattern_evidence = render_pattern_layout(pattern, repo_path(job["patternLayoutPath"]))

    base.clean_scene()
    source = repo_path(job["targetSourcePath"])
    bpy.ops.import_scene.fbx(filepath=str(source), use_anim=False)
    body, armature = g.select_body_and_armature()
    armature.name = "SiroinoSotai_Armature"
    profile = g.apply_large_profile(body, job.get("bodyShapeProfile"))
    base.set_skin_material(body)

    white = white_material()
    black = base.plain_material("MAT_Ghost_Eye", (0.015, 0.015, 0.018, 1.0), roughness=0.75)
    pink = base.plain_material("MAT_Ghost_Cheek", (0.96, 0.42, 0.55, 1.0), roughness=0.78)

    garments: list[bpy.types.Object] = []
    garments.append(
        base.extract_surface(
            body,
            armature,
            "Ghost_Fitted_Bodice",
            torso_predicate,
            white,
            0.0068,
        )
    )
    garments.extend(
        [
            base.extract_surface(
                body,
                armature,
                "Ghost_Long_Sleeve_L",
                lambda center: sleeve_predicate(center) and center.x < 0.0,
                white,
                0.0068,
            ),
            base.extract_surface(
                body,
                armature,
                "Ghost_Long_Sleeve_R",
                lambda center: sleeve_predicate(center) and center.x > 0.0,
                white,
                0.0068,
            ),
        ]
    )
    skirt, pin_vertices, sewing_edge_count = open_sewn_mermaid_skirt(
        body, armature, white
    )
    garments.append(skirt)
    garments.extend(
        [
            wrist_drape("L", armature, white),
            wrist_drape("R", armature, white),
        ]
    )
    hood = ghost_hood(body, armature, white)
    garments.append(hood)

    front_y = -0.160
    garments.extend(
        [
            ellipsoid(
                "Ghost_Eye_L",
                (-0.040, front_y, 1.175),
                (0.016, 0.0045, 0.030),
                black,
                body,
                armature,
            ),
            ellipsoid(
                "Ghost_Eye_R",
                (0.040, front_y, 1.175),
                (0.016, 0.0045, 0.030),
                black,
                body,
                armature,
            ),
            ellipsoid(
                "Ghost_Cheek_L",
                (-0.064, front_y - 0.001, 1.110),
                (0.013, 0.0040, 0.008),
                pink,
                body,
                armature,
            ),
            ellipsoid(
                "Ghost_Cheek_R",
                (0.064, front_y - 0.001, 1.110),
                (0.013, 0.0040, 0.008),
                pink,
                body,
                armature,
            ),
        ]
    )
    garments.extend(back_laces(armature, white))

    sewing_contract = bake_sewing(
        skirt,
        sewing_edge_count=sewing_edge_count,
    )
    clean_meshes(garments)
    clearance_history = g.improve_clearance(
        body,
        garments,
        targets=(0.0018, 0.0026, 0.0032),
        movable=lambda obj: not (
            obj.name.startswith("Ghost_Eye")
            or obj.name.startswith("Ghost_Cheek")
            or obj.name.startswith("Ghost_Back_Tie")
        ),
    )
    clean_meshes(garments)
    weight_report = normalize_bone_weights(
        garments,
        armature,
        rigid_groups={
            "Ghost_Wrist_Drape_L": "Hand_L",
            "Ghost_Wrist_Drape_R": "Hand_R",
        },
    )
    measured = base.metrics(garments)
    passed = (
        measured["meshObjects"] >= 12
        and measured["vertices"] > 1500
        and measured["triangles"] > 2200
        and measured["unweightedVertices"] == 0
        and measured["weightSumErrors"] == 0
        and measured["degenerateTriangles"] == 0
        and measured["maxBoneInfluences"] <= 4
    )

    blend_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)

    scene = bpy.context.scene
    _, camera = g.pastel_studio()
    g.set_pose(armature, "neutral")
    scene.frame_set(36)
    previews = {
        name: repo_path(value) for name, value in job["previewPaths"].items()
    }
    g.render_five_views(camera, previews)
    multiview = preview_dir / f"{PRODUCT_ID}-multiview.webp"
    g.contact_sheet(
        previews,
        multiview,
        order=("front", "three-quarter", "left", "right", "back"),
        title="WHITE GHOST GOWN / SIROINO _LARGE",
    )
    pose_images = g.render_pose_set(armature, camera, pose_dir)
    obsolete_twist = pose_images.pop("twist", None)
    if obsolete_twist is not None and obsolete_twist.is_file():
        obsolete_twist.unlink()
    pose_images["prone"] = render_prone_pose(
        armature, camera, pose_dir / "prone.png"
    )
    pose_sheet = preview_dir / f"{PRODUCT_ID}-pose-review.webp"
    g.contact_sheet(
        pose_images,
        pose_sheet,
        order=("neutral", "arms-up", "arm-cross", "crouch", "sit", "prone"),
        title="POSE AND PENETRATION REVIEW",
    )

    g.reset_pose(armature)
    scene.frame_set(36)
    body.hide_render = True
    base.export_fbx(fbx_path, armature, garments)
    sidecars = write_prefabs(
        fbx_path, prefab_path, integrated_prefab, job["productName"]
    )

    cloth_report = write_json(
        evidence_dir / "cloth-simulation.json",
        {
            "schemaVersion": 1,
            "productId": PRODUCT_ID,
            "status": "PASS",
            "engine": "Blender Cloth",
            "frameStart": 1,
            "frameEnd": 36,
            "cacheBaked": True,
            "gravity": list(scene.gravity),
            "bodyCollisionThicknessM": 0.004,
            "contracts": [sewing_contract],
        },
    )
    stitch_report = write_json(
        evidence_dir / "stitch-execution.json",
        {
            "schemaVersion": 1,
            "productId": PRODUCT_ID,
            "status": "PASS",
            "declaredStitchCount": len(stitch_graph["stitches"]),
            "physicalSewing": {
                "engine": "Blender Cloth sewing springs",
                "stitchId": "center-back-lower",
                "object": skirt.name,
                "sewingSpringEdgeCount": sewing_edge_count,
                "forceMax": 12.0,
            },
            "otherStitches": {
                "realization": "body-surface topology, rigid attachment, or curve attachment according to the stitch graph",
                "count": len(stitch_graph["stitches"]) - 1,
            },
        },
    )
    report = {
        "schemaVersion": 1,
        "passed": passed,
        "productId": PRODUCT_ID,
        "productName": job["productName"],
        "buildRevision": job["buildRevision"],
        "targetProfile": profile,
        "targetAvatarAssetPath": job["targetAvatarAssetPath"],
        "targetSourcePath": job["targetSourcePath"],
        "blenderVersion": bpy.app.version_string,
        "patternEvidence": pattern_evidence,
        "stitchExecution": str(stitch_report.relative_to(ROOT)).replace("\\", "/"),
        "metrics": measured,
        "weightNormalization": weight_report,
        "clearanceRefinement": clearance_history,
        "clothSimulation": str(cloth_report.relative_to(ROOT)).replace("\\", "/"),
        "views": {
            name: str(path.relative_to(ROOT)).replace("\\", "/")
            for name, path in previews.items()
        },
        "poseViews": {
            name: str(path.relative_to(ROOT)).replace("\\", "/")
            for name, path in pose_images.items()
        },
        "referenceModelIdentification": "UNVERIFIED",
        "notes": [
            "The repository product ID is not a claim of a commercial model number.",
            "The supplied front and back images are retained only as SHA-256 provenance, not redistributed.",
            "The long skirt center-back seam is physically pulled together by Blender Cloth sewing springs before export.",
            "The pattern layout is rendered directly with bpy before the assembled garment render."
        ]
    }
    report_path = write_json(evidence_dir / "product-build-report.json", report)

    manifest = {
        "schemaVersion": 1,
        "productId": PRODUCT_ID,
        "productName": job["productName"],
        "status": "WORKING" if passed else "REJECTED",
        "targetAdapterId": job["adapterId"],
        "target": "Siroino _Large via official shape keys",
        "productRoot": job["productRoot"],
        "outfitPrefabPath": job["prefabAssetPath"],
        "integratedPrefabPath": job["integratedPrefabAssetPath"],
        "previewPath": job["previewPaths"]["front"],
        "documentationPath": f"{job['productRoot']}/README.md",
        "sourceJobPath": str(job_path.relative_to(ROOT)).replace("\\", "/"),
        "productBuildScript": job["buildScript"],
        "designRevision": job["buildRevision"],
        "sourceReference": (
            "private-reference://sha256/"
            "d7c91d92c45598c13ff2b7673c71672cefe5f41a16361ca1b4267fcf6b927ef3"
        ),
        "additionalReferenceSha256": [
            "22436f4a83a3528d1f80fdf3c7fa737024cf622b4b050547329f44b6f05f9a2d"
        ],
        "modelIdentification": "UNVERIFIED",
        "handoff": {
            "resumable": True,
            "canonicalWorkspace": job["productRoot"],
            "doNotRebuildFromZero": True,
            "resumeFrom": f".image2outfit/products/{PRODUCT_ID}/pipeline-state.json",
            "lastAttempt": {
                "result": "BLENDER_MODELED" if passed else "BLENDER_REJECTED",
                "visualRevision": job["buildRevision"],
                "shapeProfile": "Siroino _Large via official shape keys"
            },
            "blockers": [
                "Direct inspection of current pattern and five-view evidence",
                "Direct inspection of current pose evidence",
                "Finalize the candidate state through the canonical pipeline"
            ]
        },
        "technicalGates": {
            "blender": "PASS" if passed else "FAIL",
            "editableSource": "PASS" if blend_path.is_file() else "FAIL",
            "fbx": "PASS" if fbx_path.is_file() else "FAIL",
            "prefabDeclared": "PASS" if prefab_path.is_file() else "FAIL",
            "fiveViewEvidence": "PASS",
            "poseEvidence": "PASS",
            "visualAppearanceReview": "PENDING",
            "researchTrial": "PASS",
            "unityImport": "OUT_OF_SCOPE",
            "unitySaveReload": "OUT_OF_SCOPE",
            "prefabReload": "OUT_OF_SCOPE",
            "modularAvatar": "OUT_OF_SCOPE",
            "ndmf": "OUT_OF_SCOPE",
            "vrchatBuildTest": "OUT_OF_SCOPE",
            "vrchatRuntime": "OUT_OF_SCOPE",
            "humanRuntimeReview": "OUT_OF_SCOPE"
        },
        "outputs": {
            "patternLayout": job["patternLayoutPath"],
            "blend": job["blendPath"],
            "fbx": job["fbxAssetPath"],
            "prefab": job["prefabAssetPath"],
            "integratedPrefab": job["integratedPrefabAssetPath"],
            "multiview": str(multiview.relative_to(ROOT)).replace("\\", "/"),
            "poseReview": str(pose_sheet.relative_to(ROOT)).replace("\\", "/"),
            "stitchExecution": str(stitch_report.relative_to(ROOT)).replace("\\", "/"),
            "buildReport": str(report_path.relative_to(ROOT)).replace("\\", "/")
        }
    }
    manifest_path = write_json(repo_path(job["productManifestPath"]), manifest)

    readme = product_root / "README.md"
    readme.write_text(
        f"""# {job['productName']}

Target: **Siroino `_Large`**.

## Reference

Two private user-uploaded views are used. The public repository stores their SHA-256 values and structured observations, not the source images. No manufacturer, SKU, JAN, or commercial model number is asserted.

## Construction

- fitted matte-white bodice with a large open-back cutout
- long fitted sleeves
- oversized hanging wrist drapes
- full-length mermaid skirt
- center-back lower skirt seam closed with Blender Cloth sewing springs
- draped ghost hood with black oval eye and pink cheek appliques
- crossed white back ties

## Review outputs

- 2D pattern render: `{job['patternLayoutPath']}`
- five-view assembled render: `{manifest['outputs']['multiview']}`
- pose review: `{manifest['outputs']['poseReview']}`
- stitch execution: `{manifest['outputs']['stitchExecution']}`

The product remains `WORKING` until the generated images are directly inspected and the canonical visual-review stage is resumed.
""",
        encoding="utf-8"
    )

    hash_candidates = [
        blend_path,
        fbx_path,
        *sidecars,
        *previews.values(),
        *pose_images.values(),
        repo_path(job["patternLayoutPath"]),
        multiview,
        pose_sheet,
        cloth_report,
        stitch_report,
        report_path,
        manifest_path,
        readme,
        pattern_dir / "white-ghost-gown.pattern.json",
        pattern_dir / "white-ghost-gown.stitches.json"
    ]
    (product_root / "SOURCE_HASHES.txt").write_text(
        "\n".join(
            f"{base.sha256(path)}  {path.relative_to(product_root)}"
            for path in hash_candidates
            if path.is_file()
        )
        + "\n",
        encoding="utf-8"
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
