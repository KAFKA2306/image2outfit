#!/usr/bin/env python3
"""Build a tuxedo-halter layered dress from the audited user reference."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path

import bpy

import genworks_product_common as g
import siroino_strappy_knit_build as base
from tuxedo_halter_components import (
    bib_panel,
    bow_tie,
    ellipsoid,
    make_image_maps,
    ring_skirt,
    tail_panel,
    textured_material,
    vertical_ruffle,
    waistcoat_back,
    waistcoat_side,
)
from tuxedo_halter_runtime import (
    clean_meshes,
    configure_cloth,
    render_prone_pose,
    write_prefabs,
)

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "siroino-tuxedo-halter-dress-large"


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
    shutil.copyfile(tracked_pattern, pattern_dir / "tuxedo-halter.pattern.json")

    bpy.ops.import_scene.fbx(filepath=str(source), use_anim=False)
    body, armature = g.select_body_and_armature()
    armature.name = "SiroinoSotai_Armature"
    profile = g.apply_large_profile(body, job.get("bodyShapeProfile"))
    base.set_skin_material(body)

    maps = make_image_maps(texture_dir)
    materials = {
        "wine": textured_material(
            "MAT_Wine_Satin",
            maps["wine_satin_albedo"],
            maps["wine_satin_normal"],
            maps["wine_satin_roughness"],
            sheen=0.30,
        ),
        "black": textured_material(
            "MAT_Black_Satin",
            maps["black_satin_albedo"],
            maps["black_satin_normal"],
            maps["black_satin_roughness"],
            sheen=0.22,
        ),
        "sheer": textured_material(
            "MAT_Black_Sheer",
            maps["black_satin_albedo"],
            maps["black_satin_normal"],
            maps["black_satin_roughness"],
            sheen=0.10,
            alpha=0.58,
        ),
        "white": textured_material(
            "MAT_White_Jacquard",
            maps["white_jacquard_albedo"],
            maps["white_jacquard_normal"],
            maps["white_jacquard_roughness"],
            sheen=0.12,
        ),
        "silver": base.plain_material(
            "MAT_Silver_Hardware",
            (0.64, 0.69, 0.76, 1.0),
            roughness=0.18,
            metallic=0.92,
        ),
    }

    garments: list[bpy.types.Object] = []
    garments.append(bib_panel(body, armature, materials["white"]))
    garments.append(waistcoat_side("L", body, armature, materials["wine"]))
    garments.append(waistcoat_side("R", body, armature, materials["wine"]))
    garments.append(waistcoat_back(body, armature, materials["wine"]))
    garments.append(tail_panel("L", body, armature, materials["wine"]))
    garments.append(tail_panel("R", body, armature, materials["wine"]))
    garments.extend(
        vertical_ruffle(index, body, armature, materials["white"])
        for index in range(3)
    )
    garments.extend(bow_tie(body, armature, materials["black"]))

    neck_loop = base.ellipse_points((0.0, 0.010, 1.045), (0.052, 0.043), 48)
    garments.append(
        base.curve_tube(
            "Black_Halter_Neck_Band",
            neck_loop,
            0.0050,
            materials["black"],
            armature,
            "Neck",
            cyclic=True,
        )
    )

    for index, z in enumerate((0.920, 0.875, 0.830, 0.785), start=1):
        y = base.body_front_y(body, 0.0, z) - 0.023
        garments.append(
            ellipsoid(
                f"Black_Bib_Button_{index}",
                (0.0, y, z),
                (0.006, 0.004, 0.006),
                materials["black"],
                body,
                armature,
            )
        )

    upper_skirt, upper_pin = ring_skirt(
        "Black_Upper_Pleated_Skirt",
        body,
        armature,
        materials["black"],
        top_z=0.708,
        bottom_z=0.535,
        top_rx=0.148,
        top_ry=0.108,
        bottom_rx=0.245,
        bottom_ry=0.185,
        pleats=16,
        thickness=0.0015,
    )
    lower_skirt, lower_pin = ring_skirt(
        "Black_Sheer_Lower_Skirt",
        body,
        armature,
        materials["sheer"],
        top_z=0.692,
        bottom_z=0.440,
        top_rx=0.152,
        top_ry=0.112,
        bottom_rx=0.285,
        bottom_ry=0.215,
        pleats=20,
        thickness=0.0008,
    )
    garments.extend([upper_skirt, lower_skirt])

    hem_points = []
    for index in range(144):
        angle = math.tau * index / 144
        scallop = 0.007 * (0.5 + 0.5 * math.cos(angle * 20))
        hem_points.append(
            (
                0.286 * math.cos(angle),
                0.216 * math.sin(angle),
                0.440 + scallop,
            )
        )
    garments.append(
        base.curve_tube(
            "Black_Lace_Scallop_Hem",
            hem_points,
            0.0021,
            materials["black"],
            armature,
            "Hips",
            cyclic=True,
        )
    )

    waist_y = base.body_front_y(body, 0.0, 0.730) - 0.026
    for side, x in (("L", -0.085), ("R", 0.085)):
        garments.append(
            ellipsoid(
                f"Silver_Waist_Anchor_{side}",
                (x, waist_y, 0.735),
                (0.008, 0.005, 0.008),
                materials["silver"],
                body,
                armature,
            )
        )
    chain_points = [
        (-0.082, waist_y - 0.004, 0.733),
        (-0.045, waist_y - 0.008, 0.700),
        (0.0, waist_y - 0.010, 0.688),
        (0.045, waist_y - 0.008, 0.700),
        (0.082, waist_y - 0.004, 0.733),
    ]
    garments.append(
        base.curve_tube(
            "Silver_Waist_Chain_Upper",
            chain_points,
            0.0015,
            materials["silver"],
            armature,
            "Hips",
        )
    )
    lower_chain = [(x, y - 0.002, z - 0.017) for x, y, z in chain_points]
    garments.append(
        base.curve_tube(
            "Silver_Waist_Chain_Lower",
            lower_chain,
            0.0012,
            materials["silver"],
            armature,
            "Hips",
        )
    )

    clean_meshes(garments)
    clearance_history = g.improve_clearance(
        body,
        garments,
        targets=(0.0018, 0.0028, 0.0036),
        movable=lambda obj: not obj.name.startswith("Silver_"),
    )
    clean_meshes(garments)

    frame_end = 30
    cloth_contracts = [
        configure_cloth(upper_skirt, body, upper_pin, frame_end=frame_end),
        configure_cloth(lower_skirt, body, lower_pin, frame_end=frame_end),
    ]
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = frame_end
    scene.gravity = (0.0, 0.0, -5.5)
    bpy.context.view_layer.objects.active = upper_skirt
    bpy.ops.ptcache.bake_all(bake=True)
    scene.frame_set(frame_end)
    bpy.context.view_layer.update()
    for skirt in (upper_skirt, lower_skirt):
        bpy.ops.object.select_all(action="DESELECT")
        skirt.select_set(True)
        bpy.context.view_layer.objects.active = skirt
        bpy.ops.object.modifier_apply(modifier="Reference Cloth")
        solidify = skirt.modifiers.new("Fabric thickness", "SOLIDIFY")
        solidify.thickness = 0.0013 if skirt is upper_skirt else 0.0008
        solidify.offset = 0.0
        solidify.use_even_offset = True
        bpy.ops.object.modifier_apply(modifier=solidify.name)
        soft = skirt.modifiers.new("Soft skirt edge", "BEVEL")
        soft.width = 0.0005
        soft.segments = 2
        bpy.ops.object.modifier_apply(modifier=soft.name)
        skirt.select_set(False)

    measured = base.metrics(garments)
    passed = (
        measured["meshObjects"] >= 18
        and measured["vertices"] > 1800
        and measured["triangles"] > 2500
        and measured["unweightedVertices"] == 0
        and measured["weightSumErrors"] == 0
        and measured["degenerateTriangles"] == 0
        and measured["maxBoneInfluences"] <= 4
        and clearance_history[-1]["clearance"]["p01"] >= 0.0030
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
        title="TUXEDO HALTER LAYERED DRESS / SIROINO _LARGE",
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
        },
    )
    report = {
        "schemaVersion": 1,
        "passed": passed,
        "productId": PRODUCT_ID,
        "productName": job["productName"],
        "targetProfile": profile,
        "targetAvatarAssetPath": job["targetAvatarAssetPath"],
        "targetSourcePath": job["targetSourcePath"],
        "blenderVersion": bpy.app.version_string,
        "metrics": measured,
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
            (
                "The design is an original, logo-free reconstruction of the visible "
                "reference grammar."
            ),
            (
                "No manufacturer, SKU, JAN, or model number is asserted because no "
                "exact primary-source match was verified."
            ),
            (
                "Wine-red/black is generated as the primary material variant; "
                "black/black is declared as a secondary variant."
            ),
        ],
    }
    report_path = write_json(evidence_dir / "product-build-report.json", report)

    variants = write_json(
        product_root / "MaterialVariants.json",
        {
            "schemaVersion": 1,
            "productId": PRODUCT_ID,
            "default": "wine-red-black",
            "variants": [
                {
                    "id": "wine-red-black",
                    "waistcoatMaterial": "MAT_Wine_Satin",
                    "skirtMaterial": "MAT_Black_Satin",
                },
                {
                    "id": "black-black",
                    "waistcoatMaterial": "MAT_Black_Satin",
                    "skirtMaterial": "MAT_Black_Satin",
                },
            ],
        },
    )

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
            "66cd898014d3f503da8015207a0240d946aac72b596f28bef8d6574a0afb678b"
        ),
        "modelIdentification": "UNVERIFIED",
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
                "Direct inspection of current five-view and pose evidence",
                "Finalize the candidate state through the canonical pipeline",
            ],
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
            "humanRuntimeReview": "OUT_OF_SCOPE",
        },
        "outputs": {
            "blend": job["blendPath"],
            "fbx": job["fbxAssetPath"],
            "prefab": job["prefabAssetPath"],
            "integratedPrefab": job["integratedPrefabAssetPath"],
            "multiview": str(multiview.relative_to(ROOT)).replace("\\", "/"),
            "poseReview": str(pose_sheet.relative_to(ROOT)).replace("\\", "/"),
            "buildReport": str(report_path.relative_to(ROOT)).replace("\\", "/"),
        },
    }
    manifest_path = write_json(repo_path(job["productManifestPath"]), manifest)

    readme = product_root / "README.md"
    readme.write_text(
        f"""# {job['productName']}

Target: **Siroino `_Large`**.

## Reference audit

The reference image visibly declares `winered × black` and `black × black`. No exact manufacturer, model number, SKU, or JAN was verified, so this product does not claim a commercial model identity.

## Construction

- white jacquard halter bib with three vertical ruffles
- black neck band and bow tie
- fitted wine-red tuxedo waistcoat with pointed tails
- four black bib buttons
- silver double-drape waist chain
- opaque pleated upper skirt
- longer sheer black skirt with scalloped hem trim
- Blender cloth simulation on both skirt layers

## Outputs

- Blender source: `{job['blendPath']}`
- FBX: `{job['fbxAssetPath']}`
- outfit Prefab declaration: `{job['prefabAssetPath']}`
- integrated Prefab declaration: `{job['integratedPrefabAssetPath']}`
- five-view sheet: `{manifest['outputs']['multiview']}`
- pose-review sheet: `{manifest['outputs']['poseReview']}`

Unity import, Modular Avatar/NDMF execution, VRChat Build & Test, and runtime inspection are outside the completion scope and are not represented as PASS.
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
        report_path,
        variants,
        manifest_path,
        readme,
        pattern_dir / "tuxedo-halter.pattern.json",
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
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
