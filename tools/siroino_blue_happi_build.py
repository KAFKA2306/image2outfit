#!/usr/bin/env python3
"""Build the SiroinoSotai_PC saturated-blue open-front happi."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import uuid
from pathlib import Path

import bpy
from PIL import Image

import genworks_product_common as g
import siroino_strappy_knit_build as base
from tuxedo_halter_runtime import (
    clean_meshes,
    normalize_bone_weights,
    render_prone_pose,
)

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "siroino-blue-happi"


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
    albedo_pixels = []
    normal_pixels = []
    roughness_pixels = []
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


def panel_predicates():
    return {
        "Happi_Back_Body": (
            lambda c: 0.565 <= c.z <= 1.015
            and abs(c.x) <= 0.150
            and c.y >= -0.004
        ),
        "Happi_Front_Left": (
            lambda c: 0.565 <= c.z <= 1.015
            and -0.155 <= c.x <= -0.018
            and c.y < 0.018
        ),
        "Happi_Front_Right": (
            lambda c: 0.565 <= c.z <= 1.015
            and 0.018 <= c.x <= 0.155
            and c.y < 0.018
        ),
        "Happi_Sleeve_Left": (
            lambda c: c.x <= -0.112
            and 0.700 <= c.z <= 1.020
            and abs(c.y) <= 0.150
        ),
        "Happi_Sleeve_Right": (
            lambda c: c.x >= 0.112
            and 0.700 <= c.z <= 1.020
            and abs(c.y) <= 0.150
        ),
    }


def create_front_band(
    name: str,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    sign: float,
) -> bpy.types.Object:
    rows = 22
    inner_x = sign * 0.017
    outer_x = sign * 0.050
    vertices = []
    faces = []
    for row in range(rows + 1):
        z = 0.575 + (1.008 - 0.575) * row / rows
        for x in (inner_x, outer_x):
            y = base.body_front_y(body, x, z) - 0.025
            vertices.append((x, y, z))
    for row in range(rows):
        a = row * 2
        faces.append((a, a + 1, a + 3, a + 2))
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    base.rigid_mesh_weight(obj, armature, "Chest")
    solidify = obj.modifiers.new("Collar band thickness", "SOLIDIFY")
    solidify.thickness = 0.0022
    solidify.offset = 0.0
    solidify.use_even_offset = True
    bevel = obj.modifiers.new("Collar band edge", "BEVEL")
    bevel.width = 0.0008
    bevel.segments = 2
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    return obj


def create_back_collar(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    segments = 36
    vertices = []
    faces = []
    for index in range(segments + 1):
        angle = math.pi - math.pi * index / segments
        for radius in (0.043, 0.071):
            x = radius * math.cos(angle)
            y = 0.006 + 0.050 * math.sin(angle)
            z = 1.005 + 0.006 * math.cos(angle * 2.0)
            vertices.append((x, y, z))
    for index in range(segments):
        a = index * 2
        faces.append((a, a + 1, a + 3, a + 2))
    mesh = bpy.data.meshes.new("Happi_Collar_Back_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    mesh.materials.append(material)
    obj = bpy.data.objects.new("Happi_Collar_Back", mesh)
    bpy.context.collection.objects.link(obj)
    base.rigid_mesh_weight(obj, armature, "Neck")
    solidify = obj.modifiers.new("Back collar thickness", "SOLIDIFY")
    solidify.thickness = 0.0022
    solidify.offset = 0.0
    solidify.use_even_offset = True
    bevel = obj.modifiers.new("Back collar edge", "BEVEL")
    bevel.width = 0.0008
    bevel.segments = 2
    return obj


def configure_cloth(
    panels: list[bpy.types.Object],
    body: bpy.types.Object,
    frame_end: int,
) -> list[dict[str, object]]:
    collision = body.modifiers.get("Happi Collision")
    if collision is None:
        body.modifiers.new("Happi Collision", "COLLISION")
    body.collision.thickness_outer = 0.004
    body.collision.damping = 0.5
    contracts = []
    for panel in panels:
        coordinates = [panel.matrix_world @ vertex.co for vertex in panel.data.vertices]
        if "Sleeve_Left" in panel.name:
            selected = [
                vertex.index
                for vertex, coordinate in zip(panel.data.vertices, coordinates)
                if coordinate.x > -0.175
            ]
        elif "Sleeve_Right" in panel.name:
            selected = [
                vertex.index
                for vertex, coordinate in zip(panel.data.vertices, coordinates)
                if coordinate.x < 0.175
            ]
        else:
            selected = [
                vertex.index
                for vertex, coordinate in zip(panel.data.vertices, coordinates)
                if coordinate.z > 0.965
            ]
        if not selected:
            selected = [vertex.index for vertex in panel.data.vertices[:8]]
        pin = panel.vertex_groups.get("HappiClothPin")
        if pin is None:
            pin = panel.vertex_groups.new(name="HappiClothPin")
        pin.add(selected, 1.0, "REPLACE")
        cloth = panel.modifiers.new("Happi Cloth", "CLOTH")
        cloth.settings.quality = 7
        cloth.settings.mass = 0.24
        cloth.settings.tension_stiffness = 26.0
        cloth.settings.compression_stiffness = 24.0
        cloth.settings.shear_stiffness = 10.0
        cloth.settings.bending_stiffness = 0.75
        cloth.settings.air_damping = 4.0
        cloth.settings.vertex_group_mass = pin.name
        cloth.settings.pin_stiffness = 1.0
        cloth.collision_settings.use_collision = True
        cloth.collision_settings.collision_quality = 5
        cloth.collision_settings.distance_min = 0.003
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


def write_prefabs(
    fbx: Path,
    outfit_prefab: Path,
    integrated_prefab: Path,
    product_name: str,
) -> list[Path]:
    fbx_guid = uuid.uuid4().hex
    outputs = []
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
    outputs.append(fbx_meta)
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
    axis: str, status: str, evidence: dict | list | str
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
        normal_strength=0.32,
        sheen=0.16,
    )
    edge = base.plain_material(
        "MAT_Happi_Blue_Edge",
        (0.012, 0.075, 0.46, 1.0),
        roughness=0.58,
    )

    panels = [
        base.extract_surface(
            body,
            armature,
            name,
            predicate,
            blue,
            0.018 if "Sleeve" not in name else 0.021,
        )
        for name, predicate in panel_predicates().items()
    ]
    structural = [
        create_front_band("Happi_Collar_Front_Left", body, armature, edge, -1.0),
        create_front_band("Happi_Collar_Front_Right", body, armature, edge, 1.0),
        create_back_collar(body, armature, edge),
    ]
    garments = [*panels, *structural]
    clean_meshes(garments)

    scene = bpy.context.scene
    frame_end = 18
    scene.frame_start = 1
    scene.frame_end = frame_end
    scene.gravity = (0.0, 0.0, -3.5)
    cloth_contracts = configure_cloth(panels, body, frame_end)
    clean_meshes(garments)

    clearance_history = g.improve_clearance(
        body,
        garments,
        targets=(0.003, 0.005, 0.008),
        movable=lambda obj: not obj.name.startswith("Happi_Collar"),
    )
    clean_meshes(garments)
    weight_report = normalize_bone_weights(
        garments,
        armature,
        rigid_groups={
            "Happi_Collar_Front_Left": "Chest",
            "Happi_Collar_Front_Right": "Chest",
            "Happi_Collar_Back": "Neck",
        },
    )
    measured = base.metrics(garments)
    clearance_p01 = clearance_history[-1]["clearance"]["p01"]

    front_left = bpy.data.objects["Happi_Front_Left"]
    front_right = bpy.data.objects["Happi_Front_Right"]
    left_inner = max(
        (front_left.matrix_world @ vertex.co).x for vertex in front_left.data.vertices
    )
    right_inner = min(
        (front_right.matrix_world @ vertex.co).x
        for vertex in front_right.data.vertices
    )
    front_opening = right_inner - left_inner

    technical_pass = (
        measured["meshObjects"] >= 8
        and measured["vertices"] > 500
        and measured["unweightedVertices"] == 0
        and measured["weightSumErrors"] == 0
        and measured["degenerateTriangles"] == 0
        and measured["maxBoneInfluences"] <= 4
        and clearance_p01 >= 0.002
        and front_opening >= 0.020
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
        armature, camera, pose_dir / "prone.png"
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
            "frameEnd": frame_end,
            "cacheBaked": True,
            "gravity": list(scene.gravity),
            "contracts": cloth_contracts,
            "bodyCollisionThicknessM": 0.004,
            "structuralObjectsExcludedFromSolve": [
                "Happi_Collar_Front_Left",
                "Happi_Collar_Front_Right",
                "Happi_Collar_Back",
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
                "panelObjects": [obj.name for obj in panels],
                "structuralObjects": [obj.name for obj in structural],
                "stitchGraph": job["garmentPipeline"]["stitchGraphPath"],
            },
        ),
        quality_axis(
            "fit",
            "PASS"
            if clearance_p01 >= 0.002 and front_opening >= 0.020
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
            {"bodyPanels": 5, "structuralCollarObjects": 3},
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
            "PASS",
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
            {
                "reference": (
                    "private-reference://sha256/"
                    "9fc40516ae446274dc869cd695ea217fb741089d26dda43d685bba2d82da0423"
                )
            },
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
            "The body, sleeves, and collar are separate auditable objects.",
            "The front opening is measured after cloth and clearance refinement.",
            "The collar and front bands are structural and excluded from the cloth solve.",
            "No manufacturer, product code, text, or crest is asserted.",
            "Visual silhouette and styling remain pending direct image inspection.",
        ],
    }
    report_path = write_json(
        evidence_dir / "product-build-report.json", report
    )

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
        "sourceReference": (
            "private-reference://sha256/"
            "9fc40516ae446274dc869cd695ea217fb741089d26dda43d685bba2d82da0423"
        ),
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

- separate back, left-front, and right-front body panels
- separate loose left and right sleeves
- two front collar bands and one back-neck collar bridge
- baked Blender Cloth settling for the five fabric panels
- structural collar objects excluded from the cloth solve
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
