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
DESIGN_REVISION = "v6-fitted-sleeves-split-hood-seam-graph"


def rebind_dynamic_parts(
    garments: list[bpy.types.Object],
    body: bpy.types.Object,
) -> dict[str, object]:
    prefixes = (
        "Heather_Long_Sleeve_",
        "Heather_Rib_Cuff_",
        "Heather_Hood_Cowl",
        "Heather_Hood_Back_Drape_",
        "Heather_Editable_Seams",
    )
    rebound = []
    for obj in garments:
        if obj.type == "MESH" and obj.name.startswith(prefixes):
            base.transfer_nearest_body_weights(obj, body)
            rebound.append(obj.name)
    return {
        "objects": rebound,
        "weightSource": "nearest tracked SiroinoSotai_PC body vertices",
    }


def limit_bone_influences(
    objects: list[bpy.types.Object],
    maximum: int = 4,
) -> dict[str, int]:
    pruned: dict[str, int] = {}
    for obj in objects:
        if obj.type != "MESH":
            continue
        affected = 0
        for vertex in obj.data.vertices:
            assignments = [
                (obj.vertex_groups[item.group].name, float(item.weight))
                for item in vertex.groups
                if item.weight > 1e-8
            ]
            if len(assignments) <= maximum:
                continue
            ranked = sorted(
                assignments,
                key=lambda item: item[1],
                reverse=True,
            )[:maximum]
            total = sum(weight for _, weight in ranked) or 1.0
            for group_name, _ in assignments:
                obj.vertex_groups[group_name].remove([vertex.index])
            for group_name, weight in ranked:
                obj.vertex_groups[group_name].add(
                    [vertex.index],
                    weight / total,
                    "REPLACE",
                )
            affected += 1
        pruned[obj.name] = affected
    return pruned


def write_report_and_manifest(
    job: dict,
    source: Path,
    product_root: Path,
    previews: dict[str, Path],
    multiview: Path,
    measured: dict,
    cleanup: dict,
    dynamic_rebind: dict,
    influence_pruning: dict,
    shape_keys_added: dict,
    pattern_path: Path,
    research_path: Path,
    passed: bool,
) -> None:
    report_dir = ROOT / ".image2outfit" / "products" / job["id"] / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    research_trial = json.loads(research_path.read_text(encoding="utf-8"))
    report = {
        "schemaVersion": 2,
        "passed": passed,
        "checkedAt": base.utc_now(),
        "blenderVersion": bpy.app.version_string,
        "designRevision": DESIGN_REVISION,
        "target": "SiroinoSotai_PC neutral PC body",
        "targetSource": str(source.relative_to(ROOT)).replace("\\", "/"),
        "targetSourceSha256": base.sha256(source),
        "metrics": measured,
        "dynamicRebind": dynamic_rebind,
        "influencePruning": influence_pruning,
        "meshCleanup": cleanup,
        "shapeKeysAdded": shape_keys_added,
        "researchTrial": {
            "source": evidence.RESEARCH_SOURCE,
            "result": research_trial["result"],
            "decision": research_trial["productionDecision"],
            "baselineF1": research_trial["baseline"]["metrics"]["f1"],
            "semanticGraphF1": research_trial["semanticGraph"]["metrics"]["f1"],
            "deltaF1": research_trial["deltaF1"],
            "evidence": str(research_path.relative_to(ROOT)).replace("\\", "/"),
            "patternContract": str(pattern_path.relative_to(ROOT)).replace(
                "\\",
                "/",
            ),
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
        "rejectedHistory": [
            {
                "revision": "v1-body-extracted-sleeves",
                "reason": "oversized hood, sleeve spikes and split crotch silhouette",
            },
            {
                "revision": "v2-manual-segmented-sleeves",
                "reason": "sleeves remained detached in rest-pose space",
            },
            {
                "revision": "v3-body-weighted-fitted-sleeves",
                "reason": ("elbow gaps, lateral hood wings and bifurcated lower panel"),
            },
            {
                "revision": "v5-rounded-hood-pointed-highcut",
                "reason": (
                    "visual inspection found inflated sleeves, short cuffs, a wide "
                    "neckline and detached shield-like rear hood"
                ),
            },
        ],
        "notes": [
            "The garment is fitted to the tracked SiroinoSotai_PC FBX.",
            "All exported vertices are limited to four normalized bone influences.",
            "Five views are actual Blender Cycles renders of generated geometry.",
            "The 2026 paper trial is an independent deterministic ablation.",
            "Required pose, Unity and runtime review remain separate gates.",
        ],
    }
    (report_dir / "product-build-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    evidence.write_readme(product_root / "README.md", job, measured)
    manifest = {
        "schemaVersion": 2,
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
                "Inspect actual five-view and required-pose images",
                "Resolve every pose penetration reported by fit-audit.json",
                "Import/save/reload both Prefabs in pinned Unity",
                "Pass Modular Avatar/NDMF and VRChat Build & Test",
                "Complete human visual, pose and runtime reviews",
            ],
        },
        "technicalGates": {
            "standardTargetResolved": "PASS",
            "blender": "PASS" if passed else "FAIL",
            "fbx": (
                "PASS" if base.repo_path(job["fbxAssetPath"]).is_file() else "FAIL"
            ),
            "fiveViewRender": (
                "PASS" if all(path.is_file() for path in previews.values()) else "FAIL"
            ),
            "poseRender": "PENDING",
            "seamCorrespondenceTrial": research_trial["result"],
            "fourInfluenceLimit": (
                "PASS" if measured["maxBoneInfluences"] <= 4 else "FAIL"
            ),
            "fitPenetration": "PENDING",
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
            "fitAudit": f"{job['productRoot']}/Tests/fit-audit.json",
        },
        "research": report["researchTrial"],
        "metrics": measured,
        "dynamicRebind": dynamic_rebind,
        "influencePruning": influence_pruning,
        "meshCleanup": cleanup,
    }
    base.repo_path(job["productManifestPath"]).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    _, job = base.load_job()
    base.clean_scene()
    source = base.repo_path(job["targetSourcePath"])
    product_root = base.repo_path(job["productRoot"])
    blend_path = base.repo_path(job["blendPath"])
    fbx_path = base.repo_path(job["fbxAssetPath"])
    prefab_path = base.repo_path(job["prefabAssetPath"])
    product_root.mkdir(parents=True, exist_ok=True)

    bpy.ops.import_scene.fbx(filepath=str(source), use_anim=False)
    body = next(
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.name.startswith("SiroinoSotai_PC")
    )
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    armature.name = "SiroinoSotai_Armature"
    if body.data.shape_keys:
        for key in body.data.shape_keys.key_blocks:
            key.value = 0.0
    bpy.context.view_layer.update()
    base.set_skin_material(body)

    _, fabric, trim, buttons = materials.create_materials(product_root / "Textures")
    garments = geometry.create_outfit(body, armature, fabric, trim, buttons)
    dynamic_rebind = rebind_dynamic_parts(garments, body)
    cleanup = geometry.clean_meshes(garments)
    influence_pruning = limit_bone_influences(garments, 4)
    shape_keys_added = {
        obj.name: base.add_nearest_shape_keys(obj, body)
        for obj in garments
        if obj.type == "MESH"
    }
    pattern_path, research_path = evidence.write_pattern_and_research(product_root)
    research_trial = json.loads(research_path.read_text(encoding="utf-8"))

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
    sidecars = base.write_unity_sidecars(fbx_path, prefab_path, job["productName"])
    evidence.write_integrated_prefab(job, sidecars)
    measured = base.metrics(garments)

    required_objects = {
        "Heather_Body_Shell",
        "Heather_Hood_Folded_Roll",
        "Heather_Henley_Placket",
        "Heather_Henley_Button_01",
        "Heather_Henley_Button_02",
        "Heather_Henley_Button_03",
        "Heather_Hood_Drawcord_L",
        "Heather_Hood_Drawcord_R",
    }
    garment_names = {obj.name for obj in garments if obj.type == "MESH"}
    missing_objects = sorted(required_objects - garment_names)
    passed = (
        not missing_objects
        and measured["meshObjects"] >= len(required_objects)
        and measured["vertices"] > 6000
        and measured["triangles"] > 12000
        and measured["unweightedVertices"] == 0
        and measured["weightSumErrors"] == 0
        and measured["degenerateTriangles"] == 0
        and measured["maxBoneInfluences"] <= 4
        and research_trial["result"] == "PASS"
    )
    write_report_and_manifest(
        job,
        source,
        product_root,
        previews,
        multiview,
        measured,
        cleanup,
        dynamic_rebind,
        influence_pruning,
        shape_keys_added,
        pattern_path,
        research_path,
        passed,
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
    print(
        json.dumps(
            {
                "passed": passed,
                "designRevision": DESIGN_REVISION,
                "missingRequiredObjects": missing_objects,
                "metrics": measured,
                "researchTrial": research_trial["result"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
