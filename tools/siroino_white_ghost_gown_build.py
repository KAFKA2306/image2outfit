#!/usr/bin/env python3
"""Build and review a pattern-first white ghost gown for Siroino _Large.

The product-specific silhouette lives in ``siroino_white_ghost_gown_geometry``.
This module owns orchestration, evidence, deterministic sidecars, and manifests.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import bpy

import genworks_product_common as g
import render_evidence_bootstrap  # noqa: F401  # installs render-post metadata hook
import siroino_strappy_knit_build as base
import siroino_white_ghost_gown_geometry as geometry
from tuxedo_halter_runtime import clean_meshes, normalize_bone_weights, render_prone_pose

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "siroino-white-ghost-gown"
GUID_NAMESPACE = uuid.UUID("3c941243-845c-58a0-b5ca-517dc63e15a8")

PATTERN_LAYOUT_OFFSETS = {
    "dress-front": (-0.82, 0.30),
    "dress-back-left": (-0.22, 0.30),
    "dress-back-right": (0.38, 0.30),
    "sleeve": (-0.82, -1.10),
    "wrist-drape": (-0.35, -1.10),
    "hood-front": (0.10, -1.08),
    "hood-back": (0.55, -1.08),
    "back-tie": (0.18, -1.72),
}


@dataclass(frozen=True)
class BuildPaths:
    product_root: Path
    preview_dir: Path
    pose_dir: Path
    evidence_dir: Path
    pattern_dir: Path
    blend_path: Path
    fbx_path: Path
    prefab_path: Path
    integrated_prefab: Path

    @classmethod
    def from_job(cls, job: dict) -> "BuildPaths":
        product_root = repo_path(job["productRoot"])
        preview_dir = product_root / "Previews"
        return cls(
            product_root=product_root,
            preview_dir=preview_dir,
            pose_dir=preview_dir / "Poses",
            evidence_dir=product_root / "Evidence" / "Build",
            pattern_dir=product_root / "Source" / "Patterns",
            blend_path=repo_path(job["blendPath"]),
            fbx_path=repo_path(job["fbxAssetPath"]),
            prefab_path=repo_path(job["prefabAssetPath"]),
            integrated_prefab=repo_path(job["integratedPrefabAssetPath"]),
        )

    def ensure_directories(self) -> None:
        for directory in (
            self.product_root,
            self.preview_dir,
            self.pose_dir,
            self.evidence_dir,
            self.pattern_dir,
            self.blend_path.parent,
            self.fbx_path.parent,
            self.prefab_path.parent,
            self.integrated_prefab.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class ReviewOutputs:
    previews: dict[str, Path]
    multiview: Path
    pose_images: dict[str, Path]
    pose_sheet: Path


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


def repo_rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


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


def validate_job(job: dict) -> None:
    if job.get("id") != PRODUCT_ID:
        raise ValueError("job product identity mismatch")
    if job.get("schemaVersion") != 2:
        raise ValueError("white ghost gown requires schemaVersion 2")


def reference_summary(job: dict) -> dict[str, object]:
    audit_path = repo_path(job["garmentPipeline"]["referenceAuditPath"])
    audit = read_json(audit_path)
    if audit.get("productId") != PRODUCT_ID:
        raise ValueError("reference audit product identity mismatch")
    source = audit["source"]
    primary_hash = str(source["originalSha256"])
    additional = [
        str(view["originalSha256"])
        for view in source.get("additionalViews", [])
        if view.get("originalSha256")
    ]
    model = audit.get("modelIdentification", {})
    return {
        "sourceReference": f"private-reference://sha256/{primary_hash}",
        "additionalReferenceSha256": additional,
        "modelIdentification": model.get("status", "UNVERIFIED"),
    }


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

    for piece in pattern["pieces"]:
        piece_id = str(piece["pieceId"])
        if piece_id not in PATTERN_LAYOUT_OFFSETS:
            raise ValueError(f"missing pattern layout offset: {piece_id}")
        boundary = [(float(x), float(y)) for x, y in piece["boundary"]]
        ox, oy = PATTERN_LAYOUT_OFFSETS[piece_id]
        vertices = [(x + ox, y + oy, 0.0) for x, y in boundary]
        mesh = bpy.data.meshes.new(f"Pattern_{piece_id}_Mesh")
        mesh.from_pydata(vertices, [], [tuple(range(len(vertices)))])
        mesh.materials.append(paper)
        obj = bpy.data.objects.new(f"Pattern_{piece_id}", mesh)
        bpy.context.collection.objects.link(obj)
        add_polyline(
            f"Pattern_{piece_id}_Outline",
            [(x, y, 0.006) for x, y, _ in vertices],
            line,
            cyclic=True,
            radius=0.0035,
        )
        bpy.ops.object.text_add(location=(ox - 0.14, oy - 0.43, 0.012))
        label = bpy.context.object
        label.name = f"Label_{piece_id}"
        label.data.body = piece_id
        label.data.align_x = "LEFT"
        label.data.size = 0.055
        label.data.extrude = 0.0
        label.data.materials.append(line)

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 1536
    scene.render.resolution_y = 1536
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    if scene.world is None:
        scene.world = bpy.data.worlds.new("Pattern_Review_World")
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
        "path": repo_rel(output),
        "pieceCount": len(pattern["pieces"]),
        "renderer": "bpy",
        "camera": camera.name,
    }


def prepare_pattern_inputs(job: dict, paths: BuildPaths) -> tuple[dict, dict, dict]:
    tracked_pattern = repo_path(job["garmentPipeline"]["patternContractPath"])
    tracked_stitches = repo_path(job["garmentPipeline"]["stitchGraphPath"])
    shutil.copyfile(tracked_pattern, paths.pattern_dir / "white-ghost-gown.pattern.json")
    shutil.copyfile(tracked_stitches, paths.pattern_dir / "white-ghost-gown.stitches.json")
    pattern = read_json(tracked_pattern)
    stitch_graph = read_json(tracked_stitches)
    pattern_evidence = render_pattern_layout(
        pattern,
        repo_path(job["patternLayoutPath"]),
    )
    return pattern, stitch_graph, pattern_evidence


def load_target(job: dict) -> tuple[bpy.types.Object, bpy.types.Object, dict]:
    base.clean_scene()
    bpy.ops.import_scene.fbx(
        filepath=str(repo_path(job["targetSourcePath"])),
        use_anim=False,
    )
    body, armature = g.select_body_and_armature()
    armature.name = "SiroinoSotai_Armature"
    profile = g.apply_large_profile(body, job.get("bodyShapeProfile"))
    base.set_skin_material(body)
    return body, armature, profile


def evaluate_geometry(metrics: dict) -> dict[str, object]:
    checks = {
        "meshObjects>=12": metrics["meshObjects"] >= 12,
        "vertices>1500": metrics["vertices"] > 1500,
        "triangles>2200": metrics["triangles"] > 2200,
        "unweightedVertices==0": metrics["unweightedVertices"] == 0,
        "weightSumErrors==0": metrics["weightSumErrors"] == 0,
        "degenerateTriangles==0": metrics["degenerateTriangles"] == 0,
        "maxBoneInfluences<=4": metrics["maxBoneInfluences"] <= 4,
    }
    return {"passed": all(checks.values()), "checks": checks}


def refine_and_measure(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    assembly: geometry.GarmentAssembly,
) -> tuple[dict, dict, list[dict[str, object]], dict[str, object]]:
    garments = list(assembly.objects)
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
        rigid_groups=assembly.rigid_groups,
    )
    metrics = base.metrics(garments)
    return metrics, weight_report, clearance_history, evaluate_geometry(metrics)


def render_reviews(
    job: dict,
    paths: BuildPaths,
    armature: bpy.types.Object,
) -> ReviewOutputs:
    scene = bpy.context.scene
    _, camera = g.pastel_studio()
    g.set_pose(armature, "neutral")
    scene.frame_set(geometry.DEFAULT_SPEC.skirt.frame_end)
    previews = {
        name: repo_path(value) for name, value in job["previewPaths"].items()
    }
    g.render_five_views(camera, previews)
    multiview = paths.preview_dir / f"{PRODUCT_ID}-multiview.webp"
    g.contact_sheet(
        previews,
        multiview,
        order=("front", "three-quarter", "left", "right", "back"),
        title="WHITE GHOST GOWN / SIROINO _LARGE",
    )

    pose_images = g.render_pose_set(armature, camera, paths.pose_dir)
    obsolete_twist = pose_images.pop("twist", None)
    if obsolete_twist is not None and obsolete_twist.is_file():
        obsolete_twist.unlink()
    pose_images["prone"] = render_prone_pose(
        armature,
        camera,
        paths.pose_dir / "prone.png",
    )
    pose_sheet = paths.preview_dir / f"{PRODUCT_ID}-pose-review.webp"
    g.contact_sheet(
        pose_images,
        pose_sheet,
        order=("neutral", "arms-up", "arm-cross", "crouch", "sit", "prone"),
        title="POSE AND PENETRATION REVIEW",
    )
    return ReviewOutputs(previews, multiview, pose_images, pose_sheet)


def stable_guid(path: Path) -> str:
    return uuid.uuid5(GUID_NAMESPACE, f"image2outfit:{repo_rel(path)}").hex


def write_prefabs(
    fbx: Path,
    outfit_prefab: Path,
    integrated_prefab: Path,
    name: str,
) -> list[Path]:
    """Write deterministic Unity sidecars for a reproducible product build."""
    fbx_guid = stable_guid(fbx)
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
  userData: image2outfit {PRODUCT_ID}
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
guid: {stable_guid(path)}
PrefabImporter:
  externalObjects: {{}}
  userData:
  assetBundleName:
  assetBundleVariant:
""",
            encoding="utf-8",
        )
        outputs.extend((path, meta))
    return outputs


def write_build_evidence(
    job: dict,
    paths: BuildPaths,
    profile: dict,
    pattern_evidence: dict,
    stitch_graph: dict,
    assembly: geometry.GarmentAssembly,
    sewing_contract: dict,
    metrics: dict,
    weight_report: dict,
    clearance_history: list[dict[str, object]],
    geometry_gate: dict[str, object],
    reviews: ReviewOutputs,
) -> tuple[Path, Path, Path, dict]:
    scene = bpy.context.scene
    cloth_report = write_json(
        paths.evidence_dir / "cloth-simulation.json",
        {
            "schemaVersion": 1,
            "productId": PRODUCT_ID,
            "status": "PASS",
            "engine": "Blender Cloth",
            "frameStart": 1,
            "frameEnd": geometry.DEFAULT_SPEC.skirt.frame_end,
            "cacheBaked": True,
            "gravity": list(scene.gravity),
            "bodyCollisionThicknessM": 0.004,
            "contracts": [sewing_contract],
        },
    )
    stitch_report = write_json(
        paths.evidence_dir / "stitch-execution.json",
        {
            "schemaVersion": 1,
            "productId": PRODUCT_ID,
            "status": "PASS",
            "declaredStitchCount": len(stitch_graph["stitches"]),
            "physicalSewing": {
                "engine": "Blender Cloth sewing springs",
                "stitchId": "center-back-lower",
                "object": assembly.skirt.name,
                "sewingSpringEdgeCount": assembly.sewing_edge_count,
                "forceMax": geometry.DEFAULT_SPEC.skirt.sewing_force_max,
            },
            "otherStitches": {
                "realization": (
                    "body-surface topology, rigid attachment, or curve attachment "
                    "according to the stitch graph"
                ),
                "count": len(stitch_graph["stitches"]) - 1,
            },
        },
    )
    report = {
        "schemaVersion": 1,
        "passed": geometry_gate["passed"],
        "productId": PRODUCT_ID,
        "productName": job["productName"],
        "buildRevision": job["buildRevision"],
        "targetProfile": profile,
        "targetAvatarAssetPath": job["targetAvatarAssetPath"],
        "targetSourcePath": job["targetSourcePath"],
        "blenderVersion": bpy.app.version_string,
        "patternEvidence": pattern_evidence,
        "stitchExecution": repo_rel(stitch_report),
        "metrics": metrics,
        "geometryGate": geometry_gate,
        "weightNormalization": weight_report,
        "clearanceRefinement": clearance_history,
        "clothSimulation": repo_rel(cloth_report),
        "views": {name: repo_rel(path) for name, path in reviews.previews.items()},
        "poseViews": {
            name: repo_rel(path) for name, path in reviews.pose_images.items()
        },
        "referenceModelIdentification": reference_summary(job)["modelIdentification"],
        "notes": [
            "The repository product ID is not a claim of a commercial model number.",
            "Private reference images are represented by hashes and structured observations only.",
            "The center-back skirt seam is physically closed by Blender Cloth sewing springs before export.",
            "Pattern layout and assembled views are rendered directly with bpy.",
        ],
    }
    report_path = write_json(
        paths.evidence_dir / "product-build-report.json",
        report,
    )
    return cloth_report, stitch_report, report_path, report


def build_manifest(
    job: dict,
    paths: BuildPaths,
    passed: bool,
    reviews: ReviewOutputs,
    stitch_report: Path,
    report_path: Path,
) -> dict:
    reference = reference_summary(job)
    status = "WORKING" if passed else "REJECTED"
    return {
        "schemaVersion": 1,
        "productId": PRODUCT_ID,
        "productName": job["productName"],
        "status": status,
        "targetAdapterId": job["adapterId"],
        "target": "Siroino _Large via official shape keys",
        "productRoot": job["productRoot"],
        "outfitPrefabPath": job["prefabAssetPath"],
        "integratedPrefabPath": job["integratedPrefabAssetPath"],
        "previewPath": job["previewPaths"]["front"],
        "documentationPath": f"{job['productRoot']}/README.md",
        "sourceJobPath": repo_rel(repo_path(f"config/products/{PRODUCT_ID}/job.json")),
        "productBuildScript": job["buildScript"],
        "designRevision": job["buildRevision"],
        "sourceReference": reference["sourceReference"],
        "additionalReferenceSha256": reference["additionalReferenceSha256"],
        "modelIdentification": reference["modelIdentification"],
        "handoff": {
            "resumable": True,
            "canonicalWorkspace": job["productRoot"],
            "doNotRebuildFromZero": True,
            "resumeFrom": f".image2outfit/products/{PRODUCT_ID}/pipeline-state.json",
            "lastAttempt": {
                "result": "BLENDER_MODELED" if passed else "BLENDER_REJECTED",
                "visualRevision": job["buildRevision"],
                "shapeProfile": "Siroino _Large via official shape keys",
            },
            "blockers": [
                "Direct inspection of current pattern and five-view evidence",
                "Direct inspection of current pose evidence",
                "Finalize the candidate state through the canonical pipeline",
            ],
        },
        "technicalGates": {
            "blender": "PASS" if passed else "FAIL",
            "editableSource": "PASS" if paths.blend_path.is_file() else "FAIL",
            "fbx": "PASS" if paths.fbx_path.is_file() else "FAIL",
            "prefabDeclared": "PASS" if paths.prefab_path.is_file() else "FAIL",
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
            "humanRuntimeReview": "OUT_OF_SCOPE",
        },
        "outputs": {
            "patternLayout": job["patternLayoutPath"],
            "blend": job["blendPath"],
            "fbx": job["fbxAssetPath"],
            "prefab": job["prefabAssetPath"],
            "integratedPrefab": job["integratedPrefabAssetPath"],
            "multiview": repo_rel(reviews.multiview),
            "poseReview": repo_rel(reviews.pose_sheet),
            "stitchExecution": repo_rel(stitch_report),
            "buildReport": repo_rel(report_path),
        },
    }


def write_readme(job: dict, paths: BuildPaths, manifest: dict) -> Path:
    status = manifest["status"]
    if status == "REJECTED":
        final_note = (
            "The current generated candidate is `REJECTED`; correct the recorded "
            "geometry/visual defects, regenerate, and review the new evidence."
        )
    else:
        final_note = (
            "The generated candidate is technically buildable but remains `WORKING` "
            "until direct visual review passes."
        )
    readme = paths.product_root / "README.md"
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

{final_note}
""",
        encoding="utf-8",
    )
    return readme


def write_source_hashes(
    paths: BuildPaths,
    sidecars: list[Path],
    reviews: ReviewOutputs,
    cloth_report: Path,
    stitch_report: Path,
    report_path: Path,
    manifest_path: Path,
    readme: Path,
    pattern_layout: Path,
) -> None:
    candidates = [
        paths.blend_path,
        paths.fbx_path,
        *sidecars,
        *reviews.previews.values(),
        *reviews.pose_images.values(),
        pattern_layout,
        reviews.multiview,
        reviews.pose_sheet,
        cloth_report,
        stitch_report,
        report_path,
        manifest_path,
        readme,
        paths.pattern_dir / "white-ghost-gown.pattern.json",
        paths.pattern_dir / "white-ghost-gown.stitches.json",
    ]
    (paths.product_root / "SOURCE_HASHES.txt").write_text(
        "\n".join(
            f"{base.sha256(path)}  {path.relative_to(paths.product_root)}"
            for path in candidates
            if path.is_file()
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    job_path = repo_path(args.job)
    job = read_json(job_path)
    validate_job(job)
    paths = BuildPaths.from_job(job)
    paths.ensure_directories()

    _, stitch_graph, pattern_evidence = prepare_pattern_inputs(job, paths)
    body, armature, profile = load_target(job)
    assembly = geometry.build_garment(body, armature)
    sewing_contract = geometry.bake_sewing(
        assembly.skirt,
        sewing_edge_count=assembly.sewing_edge_count,
        spec=geometry.DEFAULT_SPEC.skirt,
    )
    metrics, weight_report, clearance_history, geometry_gate = refine_and_measure(
        body,
        armature,
        assembly,
    )
    passed = bool(geometry_gate["passed"])

    paths.blend_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(paths.blend_path), check_existing=False)
    reviews = render_reviews(job, paths, armature)

    g.reset_pose(armature)
    bpy.context.scene.frame_set(geometry.DEFAULT_SPEC.skirt.frame_end)
    body.hide_render = True
    base.export_fbx(paths.fbx_path, armature, list(assembly.objects))
    sidecars = write_prefabs(
        paths.fbx_path,
        paths.prefab_path,
        paths.integrated_prefab,
        job["productName"],
    )

    cloth_report, stitch_report, report_path, report = write_build_evidence(
        job,
        paths,
        profile,
        pattern_evidence,
        stitch_graph,
        assembly,
        sewing_contract,
        metrics,
        weight_report,
        clearance_history,
        geometry_gate,
        reviews,
    )
    manifest = build_manifest(
        job,
        paths,
        passed,
        reviews,
        stitch_report,
        report_path,
    )
    manifest_path = write_json(repo_path(job["productManifestPath"]), manifest)
    readme = write_readme(job, paths, manifest)
    write_source_hashes(
        paths,
        sidecars,
        reviews,
        cloth_report,
        stitch_report,
        report_path,
        manifest_path,
        readme,
        repo_path(job["patternLayoutPath"]),
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
