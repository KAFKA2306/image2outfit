#!/usr/bin/env python3
"""Build the SiroinoSotai_PC heather hooded high-cut bodysuit."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
from PIL import Image

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_heather_hooded_evidence as evidence
import siroino_heather_hooded_geometry as geometry
import siroino_heather_hooded_materials as materials
import siroino_strappy_knit_build as base

ROOT = Path(__file__).resolve().parents[1]
DESIGN_REVISION = "v2-fitted-sleeve-folded-hood"


def main() -> int:
    _, job = base.load_job()
    base.clean_scene()
    source = base.repo_path(job["targetSourcePath"])
    product_root = base.repo_path(job["productRoot"])
    blend_path = base.repo_path(job["blendPath"])
    fbx_path = base.repo_path(job["fbxAssetPath"])
    prefab_path = base.repo_path(job["prefabAssetPath"])
    report_dir = ROOT / ".image2outfit" / "products" / job["id"] / "reports"
    product_root.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    bpy.ops.import_scene.fbx(filepath=str(source), use_anim=False)
    body = next(
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.name.startswith("SiroinoSotai_PC")
    )
    armature = next(
        obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"
    )
    armature.name = "SiroinoSotai_Armature"
    if body.data.shape_keys:
        for key in body.data.shape_keys.key_blocks:
            key.value = 0.0
    bpy.context.view_layer.update()
    base.set_skin_material(body)

    _, fabric, trim, buttons = materials.create_materials(product_root / "Textures")
    garments = geometry.create_outfit(body, armature, fabric, trim, buttons)
    cleanup = geometry.clean_meshes(garments)
    shape_keys_added = {
        obj.name: base.add_nearest_shape_keys(obj, body)
        for obj in garments
        if obj.type == "MESH"
    }
    pattern_path, research_path = evidence.write_pattern_and_research(product_root)

    blend_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)
    _, camera = base.studio_setup()
    base.preview_pose(armature)
    previews = {
        name: base.repo_path(value) for name, value in job["previewPaths"].items()
    }
    base.render_views(camera, previews)
    multiview = product_root / "Previews" / f"{job['id']}-multiview.webp"
    base.contact_sheet(previews, multiview)

    base.reset_pose(armature)
    body.hide_render = True
    base.export_fbx(fbx_path, armature, garments)
    sidecars = base.write_unity_sidecars(
        fbx_path, prefab_path, job["productName"]
    )
    evidence.write_integrated_prefab(job, sidecars)
    measured = base.metrics(garments)
    passed = (
        measured["meshObjects"] >= 12
        and measured["vertices"] > 2500
        and measured["triangles"] > 3500
        and measured["unweightedVertices"] == 0
        and measured["weightSumErrors"] == 0
        and measured["degenerateTriangles"] == 0
        and measured["maxBoneInfluences"] <= 4
    )
    report = {
        "schemaVersion": 1,
        "passed": passed,
        "checkedAt": base.utc_now(),
        "blenderVersion": bpy.app.version_string,
        "designRevision": DESIGN_REVISION,
        "target": "SiroinoSotai_PC neutral PC body",
        "targetSource": str(source.relative_to(ROOT)).replace("\\", "/"),
        "targetSourceSha256": base.sha256(source),
        "metrics": measured,
        "meshCleanup": cleanup,
        "shapeKeysAdded": shape_keys_added,
        "researchTrial": {
            "source": evidence.RESEARCH_SOURCE,
            "result": "PASS",
            "evidence": str(research_path.relative_to(ROOT)).replace("\\", "/"),
            "patternContract": str(pattern_path.relative_to(ROOT)).replace("\\", "/"),
        },
        "views": {
            name: {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": base.sha256(path),
                "width": Image.open(path).width,
                "height": Image.open(path).height,
            }
            for name, path in previews.items()
        },
        "notes": [
            "The garment is fitted to the tracked SiroinoSotai_PC FBX.",
            "The rejected body-extracted sleeves were replaced by explicit bone-aligned sleeve panels.",
            "The oversized hood was replaced by a compact folded back-hood shell.",
            "Five views are actual Blender Cycles renders of generated geometry.",
            "The DMap neural model was not executed; only its explicit pattern-coordinate principle was trialed.",
            "Unity, pose penetration and runtime review remain pending.",
        ],
    }
    (report_dir / "product-build-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    evidence.write_readme(product_root / "README.md", job, measured)
    manifest = {
        "schemaVersion": 1,
        "productId": job["id"],
        "productName": job["productName"],
        "status": "WORKING" if passed else "REJECTED",
        "targetAdapterId": job["adapterId"],
        "target": "SiroinoSotai_PC neutral PC body",
        "productRoot": job["productRoot"],
        "outfitPrefabPath": job["prefabAssetPath"],
        "integratedPrefabPath": job["integratedPrefabAssetPath"],
        "previewPath": job["previewPaths"]["front"],
        "documentationPath": f"{job['productRoot']}/README.md",
        "sourceJobPath": f"config/products/{job['id']}/job.json",
        "productBuildScript": job["productBuildScript"],
        "designRevision": DESIGN_REVISION,
        "handoff": {
            "resumable": True,
            "canonicalWorkspace": job["productRoot"],
            "doNotRebuildFromZero": True,
            "resumeFrom": job["productBuildScript"],
            "lastAttempt": {
                "result": "HOSTED_MODELED" if passed else "REJECTED",
                "visualRevision": DESIGN_REVISION,
            },
            "blockers": [
                "Inspect actual five-view and pose-review images",
                "Import/save/reload both Prefabs in pinned Unity",
                "Pass Modular Avatar/NDMF and VRChat Build & Test",
                "Complete human visual, pose and runtime reviews",
            ],
        },
        "technicalGates": {
            "standardTargetResolved": "PASS",
            "blender": "PASS" if passed else "FAIL",
            "fbx": "PASS" if fbx_path.is_file() else "FAIL",
            "fiveViewRender": (
                "PASS" if all(path.is_file() for path in previews.values()) else "FAIL"
            ),
            "poseRender": "PENDING",
            "patternCoordinateTrial": "PASS",
            "unityImport": "PENDING",
            "prefabSerialized": "PENDING",
            "prefabReload": "PENDING",
            "modularAvatar": "PENDING",
            "vrchatBuildAndTest": "PENDING",
            "humanVisualReview": "PENDING",
            "humanPoseReview": "PENDING",
            "humanRuntimeReview": "PENDING",
        },
        "outputs": {
            "blend": job["blendPath"],
            "fbx": job["fbxAssetPath"],
            "prefab": job["prefabAssetPath"],
            "integratedPrefab": job["integratedPrefabAssetPath"],
            "multiview": str(multiview.relative_to(ROOT)).replace("\\", "/"),
            "poseReview": (
                f"{job['productRoot']}/Previews/{job['id']}-pose-review.webp"
            ),
        },
        "research": report["researchTrial"],
        "metrics": measured,
        "meshCleanup": cleanup,
    }
    base.repo_path(job["productManifestPath"]).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tracked_files = sorted(
        path
        for path in product_root.rglob("*")
        if path.is_file() and path.name != "SOURCE_HASHES.txt"
    )
    (product_root / "SOURCE_HASHES.txt").write_text(
        "\n".join(
            f"{base.sha256(path)}  {path.relative_to(product_root).as_posix()}"
            for path in tracked_files
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
