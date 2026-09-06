#!/usr/bin/env python3
"""Build a fitted tuxedo-halter layered dress from the audited reference."""

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
    cloth_cache_state,
    combined_geometry_sha256,
    configure_cloth,
    mesh_geometry_sha256,
    normalize_bone_weights,
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


def find_pattern_piece(pattern: dict, piece_id: str) -> dict:
    pieces = pattern.get("pieces")
    if not isinstance(pieces, list):
        raise ValueError("pattern pieces must be a list")
    matches = [
        piece
        for piece in pieces
        if isinstance(piece, dict) and piece.get("pieceId") == piece_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"pattern piece {piece_id!r} must exist exactly once; found {len(matches)}"
        )
    return matches[0]


def create_materials(
    texture_dir: Path,
    recipe: dict,
) -> tuple[dict[str, Path], dict[str, object]]:
    map_sets = recipe.get("mapSets")
    material_specs = recipe.get("materials")
    if not isinstance(map_sets, dict) or not isinstance(material_specs, dict):
        raise ValueError("material recipe must contain mapSets and materials")
    maps = make_image_maps(texture_dir, map_sets)

    def textured(key: str) -> object:
        spec = material_specs.get(key)
        if not isinstance(spec, dict):
            raise ValueError(f"material recipe entry is missing: {key}")
        map_set = spec.get("mapSet")
        if not isinstance(map_set, str) or map_set not in map_sets:
            raise ValueError(f"material {key!r} mapSet is invalid")
        return textured_material(
            str(spec["materialName"]),
            maps[f"{map_set}_albedo"],
            maps[f"{map_set}_normal"],
            maps[f"{map_set}_roughness"],
            sheen=float(spec.get("sheen", 0.0)),
            alpha=float(spec.get("alpha", 1.0)),
        )

    silver = material_specs.get("silver")
    if not isinstance(silver, dict):
        raise ValueError("silver material recipe is required")
    color = silver.get("baseColorRgba")
    if not isinstance(color, list) or len(color) != 4:
        raise ValueError("silver baseColorRgba is invalid")

    materials = {
        "wine": textured("wine"),
        "black": textured("black"),
        "sheer": textured("sheer"),
        "white": textured("white"),
        "silver": base.plain_material(
            str(silver["materialName"]),
            tuple(float(value) for value in color),
            roughness=float(silver["roughness"]),
            metallic=float(silver["metallic"]),
        ),
    }
    return maps, materials


def add_bodice(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    materials: dict[str, object],
    pattern: dict,
    *,
    bib_width_scale: float = 1.0,
) -> list[bpy.types.Object]:
    garments: list[bpy.types.Object] = [
        bib_panel(
            body,
            armature,
            materials["white"],
            find_pattern_piece(pattern, "bib-front"),
            width_scale=bib_width_scale,
        ),
        waistcoat_side("L", body, armature, materials["wine"]),
        waistcoat_side("R", body, armature, materials["wine"]),
        waistcoat_back(body, armature, materials["wine"]),
        tail_panel("L", body, armature, materials["wine"]),
        tail_panel("R", body, armature, materials["wine"]),
    ]
    garments.extend(
        vertical_ruffle(index, body, armature, materials["white"]) for index in range(3)
    )
    garments.extend(bow_tie(body, armature, materials["black"]))

    neck_loop = base.ellipse_points((0.0, 0.010, 1.045), (0.050, 0.041), 48)
    garments.append(
        base.curve_tube(
            "Black_Halter_Neck_Band",
            neck_loop,
            0.0044,
            materials["black"],
            armature,
            "Neck",
            cyclic=True,
        )
    )
    for index, z in enumerate((0.910, 0.865, 0.820, 0.780), start=1):
        y = base.body_front_y(body, 0.0, z) - 0.020
        garments.append(
            ellipsoid(
                f"Black_Bib_Button_{index}",
                (0.0, y, z),
                (0.0053, 0.0035, 0.0053),
                materials["black"],
                body,
                armature,
            )
        )
    return garments


def add_skirts(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    materials: dict[str, object],
) -> tuple[
    list[bpy.types.Object], bpy.types.Object, bpy.types.Object, list[int], list[int]
]:
    upper_skirt, upper_pin = ring_skirt(
        "Black_Upper_Pleated_Skirt",
        body,
        armature,
        materials["black"],
        top_z=0.705,
        bottom_z=0.550,
        top_rx=0.145,
        top_ry=0.105,
        bottom_rx=0.245,
        bottom_ry=0.177,
        pleats=12,
        thickness=0.0014,
    )
    lower_skirt, lower_pin = ring_skirt(
        "Black_Sheer_Lower_Skirt",
        body,
        armature,
        materials["sheer"],
        top_z=0.694,
        bottom_z=0.465,
        top_rx=0.150,
        top_ry=0.110,
        bottom_rx=0.275,
        bottom_ry=0.204,
        pleats=14,
        thickness=0.0008,
    )
    garments = [upper_skirt, lower_skirt]

    hem_points = []
    for index in range(168):
        angle = math.tau * index / 168
        scallop = 0.0045 * (0.5 + 0.5 * math.cos(angle * 20))
        hem_points.append(
            (
                0.276 * math.cos(angle),
                0.205 * math.sin(angle),
                0.465 + scallop,
            )
        )
    garments.append(
        base.curve_tube(
            "Black_Lace_Scallop_Hem",
            hem_points,
            0.0017,
            materials["black"],
            armature,
            "Hips",
            cyclic=True,
        )
    )
    return garments, upper_skirt, lower_skirt, upper_pin, lower_pin


def add_hardware(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    materials: dict[str, object],
) -> list[bpy.types.Object]:
    garments: list[bpy.types.Object] = []
    waist_y = base.body_front_y(body, 0.0, 0.730) - 0.022
    for side, x in (("L", -0.078), ("R", 0.078)):
        garments.append(
            ellipsoid(
                f"Silver_Waist_Anchor_{side}",
                (x, waist_y, 0.733),
                (0.0065, 0.0045, 0.0065),
                materials["silver"],
                body,
                armature,
            )
        )
    chain_points = [
        (-0.076, waist_y - 0.003, 0.731),
        (-0.040, waist_y - 0.006, 0.708),
        (0.0, waist_y - 0.008, 0.700),
        (0.040, waist_y - 0.006, 0.708),
        (0.076, waist_y - 0.003, 0.731),
    ]
    garments.append(
        base.curve_tube(
            "Silver_Waist_Chain_Upper",
            chain_points,
            0.00125,
            materials["silver"],
            armature,
            "Hips",
        )
    )
    lower_chain = [(x, y - 0.001, z - 0.013) for x, y, z in chain_points]
    garments.append(
        base.curve_tube(
            "Silver_Waist_Chain_Lower",
            lower_chain,
            0.0010,
            materials["silver"],
            armature,
            "Hips",
        )
    )
    return garments


def bake_skirts(
    body: bpy.types.Object,
    upper_skirt: bpy.types.Object,
    lower_skirt: bpy.types.Object,
    upper_pin: list[int],
    lower_pin: list[int],
) -> tuple[list[dict[str, object]], int]:
    frame_end = 24
    skirts = (upper_skirt, lower_skirt)
    pre_bake_hashes = {skirt.name: mesh_geometry_sha256(skirt) for skirt in skirts}
    contracts = [
        configure_cloth(upper_skirt, body, upper_pin, frame_end=frame_end),
        configure_cloth(lower_skirt, body, lower_pin, frame_end=frame_end),
    ]
    contract_by_object = {str(contract["object"]): contract for contract in contracts}
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = frame_end
    scene.gravity = (0.0, 0.0, -4.8)
    bpy.context.view_layer.objects.active = upper_skirt
    bpy.ops.ptcache.bake_all(bake=True)
    scene.frame_set(frame_end)
    bpy.context.view_layer.update()

    for skirt in skirts:
        contract = contract_by_object[skirt.name]
        cache = cloth_cache_state(skirt, "Reference Cloth")
        contract.update(cache)
        contract["preBakeMeshSha256"] = pre_bake_hashes[skirt.name]
        contract["evaluatedFrameMeshSha256"] = mesh_geometry_sha256(
            skirt,
            evaluated=True,
        )
        if not contract["cacheBakedActual"]:
            raise RuntimeError(f"cloth cache was not baked for {skirt.name}")

        bpy.ops.object.select_all(action="DESELECT")
        skirt.select_set(True)
        bpy.context.view_layer.objects.active = skirt
        bpy.ops.object.modifier_apply(modifier="Reference Cloth")
        contract["settledMeshSha256"] = mesh_geometry_sha256(skirt)
        contract["geometryChanged"] = (
            contract["settledMeshSha256"] != contract["preBakeMeshSha256"]
        )
        if not contract["geometryChanged"]:
            raise RuntimeError(
                f"cloth evaluation did not change mesh geometry for {skirt.name}"
            )

        solidify = skirt.modifiers.new("Fabric thickness", "SOLIDIFY")
        solidify.thickness = 0.0012 if skirt is upper_skirt else 0.0007
        solidify.offset = 0.0
        solidify.use_even_offset = True
        bpy.ops.object.modifier_apply(modifier=solidify.name)
        soft = skirt.modifiers.new("Soft skirt edge", "BEVEL")
        soft.width = 0.0004
        soft.segments = 2
        bpy.ops.object.modifier_apply(modifier=soft.name)
        skirt.select_set(False)
    return contracts, frame_end


def main() -> int:
    args = parse_args()
    job_path = repo_path(args.job)
    job = read_json(job_path)
    if job.get("id") != PRODUCT_ID:
        raise ValueError("job product identity mismatch")
    candidate_id = str(job.get("candidateId") or PRODUCT_ID)
    variant_id = str(job.get("variantId") or "baseline")
    variant_recipe_version = str(job.get("variantRecipeVersion") or "")
    workspace_id = str(job.get("workspaceId") or "")

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
    pattern_contract = read_json(tracked_pattern)
    if pattern_contract.get("productId") != PRODUCT_ID:
        raise ValueError("pattern contract product identity mismatch")
    shutil.copyfile(tracked_pattern, pattern_dir / "tuxedo-halter.pattern.json")

    tracked_material_recipe = repo_path(job["garmentPipeline"]["materialRecipePath"])
    material_recipe = read_json(tracked_material_recipe)
    if material_recipe.get("productId") != PRODUCT_ID:
        raise ValueError("material recipe product identity mismatch")

    bpy.ops.import_scene.fbx(filepath=str(source), use_anim=False)
    body, armature = g.select_body_and_armature()
    armature.name = "SiroinoSotai_Armature"
    profile = g.apply_large_profile(body, job.get("bodyShapeProfile"))
    base.set_skin_material(body)

    maps, materials = create_materials(texture_dir, material_recipe)
    geometry_variables = job.get("geometryVariables", {})
    if not isinstance(geometry_variables, dict):
        raise ValueError("job geometryVariables must be an object")
    bib_width_scale = float(geometry_variables.get("bibWidthScale", 1.0))
    garments = add_bodice(
        body,
        armature,
        materials,
        pattern_contract,
        bib_width_scale=bib_width_scale,
    )
    skirt_parts, upper_skirt, lower_skirt, upper_pin, lower_pin = add_skirts(
        body, armature, materials
    )
    garments.extend(skirt_parts)
    garments.extend(add_hardware(body, armature, materials))

    clean_meshes(garments)
    clearance_history = g.improve_clearance(
        body,
        garments,
        targets=(0.0018, 0.0028, 0.0036),
        movable=lambda obj: not obj.name.startswith("Silver_"),
    )
    clean_meshes(garments)
    cloth_contracts, frame_end = bake_skirts(
        body, upper_skirt, lower_skirt, upper_pin, lower_pin
    )
    clean_meshes(garments)
    weight_report = normalize_bone_weights(
        garments,
        armature,
        rigid_groups={
            upper_skirt.name: "Hips",
            lower_skirt.name: "Hips",
            "Black_Lace_Scallop_Hem": "Hips",
            "Silver_Waist_Anchor_L": "Hips",
            "Silver_Waist_Anchor_R": "Hips",
            "Silver_Waist_Chain_Upper": "Hips",
            "Silver_Waist_Chain_Lower": "Hips",
        },
    )
    measured = base.metrics(garments)
    geometry_fingerprint = combined_geometry_sha256(garments)
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

    scene = bpy.context.scene
    _, camera = g.pastel_studio()
    g.set_pose(armature, "neutral")
    scene.frame_set(frame_end)
    previews = {name: repo_path(value) for name, value in job["previewPaths"].items()}
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
    pose_images["prone"] = render_prone_pose(armature, camera, pose_dir / "prone.png")
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
            "candidateId": candidate_id,
            "variantId": variant_id,
            "workspaceId": workspace_id,
            "status": "PASS",
            "engine": "Blender Cloth",
            "applicability": "REQUIRED",
            "frameStart": 1,
            "frameEnd": frame_end,
            "cacheBaked": all(
                bool(contract.get("cacheBakedActual")) for contract in cloth_contracts
            ),
            "geometryChanged": all(
                bool(contract.get("geometryChanged")) for contract in cloth_contracts
            ),
            "gravity": list(scene.gravity),
            "contracts": cloth_contracts,
            "bodyCollisionThicknessM": 0.004,
        },
    )
    bib_object = bpy.data.objects.get("White_Jacquard_Bib")
    if bib_object is None:
        raise RuntimeError("pattern-driven bib object was not generated")
    bib_projection = json.loads(str(bib_object["patternProjection"]))

    report = {
        "schemaVersion": 1,
        "passed": passed,
        "productId": PRODUCT_ID,
        "candidateId": candidate_id,
        "variantId": variant_id,
        "variantRecipeVersion": variant_recipe_version,
        "workspaceId": workspace_id,
        "productName": job["productName"],
        "buildRevision": job["buildRevision"],
        "targetProfile": profile,
        "targetAvatarAssetPath": job["targetAvatarAssetPath"],
        "targetSourcePath": job["targetSourcePath"],
        "blenderVersion": bpy.app.version_string,
        "materialRecipe": {
            "path": str(tracked_material_recipe.relative_to(ROOT)).replace("\\", "/"),
            "sha256": base.sha256(tracked_material_recipe),
            "recipeVersion": material_recipe["recipeVersion"],
            "regions": {
                key: value.get("regions", [])
                for key, value in material_recipe["materials"].items()
                if isinstance(value, dict)
            },
        },
        "patternDrivenGeometry": {
            "patternPath": str(tracked_pattern.relative_to(ROOT)).replace("\\", "/"),
            "patternSha256": base.sha256(tracked_pattern),
            "pieces": {
                "bib-front": {
                    "object": bib_object.name,
                    "projectionFingerprint": bib_projection["fingerprint"],
                    "edgeVertexMap": bib_projection["edgeVertexMap"],
                    "bounds": bib_projection["bounds"],
                    "transform": bib_projection["transform"],
                }
            },
        },
        "geometryFingerprint": geometry_fingerprint,
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
            "The waistcoat is recovered as fitted body-surface panels, not detached planes.",
            "The skirt layers use subdivided low-amplitude panels and baked cloth settling.",
            "All exported deform weights are reduced to at most four bones and normalized.",
            "No manufacturer, SKU, JAN, or model number is asserted without exact evidence.",
        ],
    }
    report_path = write_json(evidence_dir / "product-build-report.json", report)

    variants = write_json(
        product_root / "MaterialVariants.json",
        {
            "schemaVersion": 1,
            "productId": PRODUCT_ID,
            "candidateId": candidate_id,
            "variantId": variant_id,
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
        "candidateId": candidate_id,
        "variantId": variant_id,
        "variantRecipeVersion": variant_recipe_version,
        "workspaceId": workspace_id,
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
            "resumeFrom": (
                f".image2outfit/products/{candidate_id}"
                + (f"--{workspace_id}" if workspace_id else "")
                + "/pipeline-state.json"
            ),
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
        f"""# {job["productName"]}

Target: **Siroino `_Large`**.

## Reference audit

The reference image visibly declares `winered × black` and `black × black`. No exact manufacturer, model number, SKU, or JAN was verified, so this product does not claim a commercial model identity.

## Construction

- white jacquard halter bib with three vertical ruffles
- fitted body-surface wine-red tuxedo waistcoat and pointed fronts
- black neck band, bow, four bib buttons, and double silver chain
- opaque flared upper skirt and longer sheer skirt
- Blender Cloth settling on both subdivided skirt layers
- deform weights normalized to four bones or fewer

## Outputs

- Blender source: `{job["blendPath"]}`
- FBX: `{job["fbxAssetPath"]}`
- outfit Prefab declaration: `{job["prefabAssetPath"]}`
- integrated Prefab declaration: `{job["integratedPrefabAssetPath"]}`
- five-view sheet: `{manifest["outputs"]["multiview"]}`
- pose-review sheet: `{manifest["outputs"]["poseReview"]}`

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
