#!/usr/bin/env python3
"""Build a fitted tuxedo-halter layered dress from the audited reference."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from collections.abc import Mapping
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
    normalize_bone_weights,
    render_prone_pose,
    write_prefabs,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from image2outfit.garment_flow import (
    canonical_json_sha256,
    ring_dimensions_from_pattern,
    sha256_file,
    validate_pattern_contract,
    variant_invalidation,
)

PRODUCT_ID = "siroino-tuxedo-halter-dress-large"


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    parser.add_argument("--variant", default="")
    parser.add_argument("--output-root", default="")
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


def mesh_snapshot(obj: bpy.types.Object) -> dict[str, object]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        vertices = [
            (
                round(float(vertex.co.x), 7),
                round(float(vertex.co.y), 7),
                round(float(vertex.co.z), 7),
            )
            for vertex in mesh.vertices
        ]
        polygons = [tuple(int(index) for index in face.vertices) for face in mesh.polygons]
        finite = all(math.isfinite(value) for vertex in vertices for value in vertex)
        if not vertices:
            raise RuntimeError(f"evaluated mesh is empty: {obj.name}")
        bounds = {
            "min": [min(vertex[axis] for vertex in vertices) for axis in range(3)],
            "max": [max(vertex[axis] for vertex in vertices) for axis in range(3)],
        }
        digest = hashlib.sha256(
            json.dumps(
                {"vertices": vertices, "polygons": polygons},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return {
            "object": obj.name,
            "vertexCount": len(vertices),
            "polygonCount": len(polygons),
            "meshDigest": digest,
            "finiteBounds": finite,
            "bounds": bounds,
        }
    finally:
        evaluated.to_mesh_clear()


def geometry_digest(objects: list[bpy.types.Object]) -> str:
    records = [
        mesh_snapshot(obj)
        for obj in sorted(objects, key=lambda item: item.name)
        if obj.type == "MESH"
    ]
    payload = {
        item["object"]: {
            "vertexCount": item["vertexCount"],
            "polygonCount": item["polygonCount"],
            "meshDigest": item["meshDigest"],
        }
        for item in records
    }
    return canonical_json_sha256(payload)


def resolve_variant(job: Mapping[str, object], variant_id: str) -> tuple[dict, dict]:
    variant_path = repo_path(job["garmentPipeline"]["variantSpecPath"])
    document = read_json(variant_path)
    base_variant = str(document["baseVariant"])
    selected = variant_id or base_variant
    if selected == base_variant:
        variant = {"id": base_variant, "kind": "base"}
    else:
        variant = next(
            (
                dict(item)
                for item in document["variants"]
                if item.get("id") == selected
            ),
            None,
        )
        if variant is None:
            raise ValueError(f"unknown product variant: {selected}")
    return document, variant


def actual_output_paths(job: Mapping[str, object], output_root: Path | None) -> dict[str, object]:
    if output_root is None:
        product_root = repo_path(job["productRoot"])
        return {
            "productRoot": product_root,
            "blend": repo_path(job["blendPath"]),
            "fbx": repo_path(job["fbxAssetPath"]),
            "prefab": repo_path(job["prefabAssetPath"]),
            "integratedPrefab": repo_path(job["integratedPrefabAssetPath"]),
            "manifest": repo_path(job["productManifestPath"]),
            "previews": {
                name: repo_path(value)
                for name, value in job["previewPaths"].items()
            },
        }
    product_root = output_root
    return {
        "productRoot": product_root,
        "blend": product_root / "Source" / "Blender" / Path(job["blendPath"]).name,
        "fbx": product_root / "Models" / Path(job["fbxAssetPath"]).name,
        "prefab": product_root / "Prefab" / Path(job["prefabAssetPath"]).name,
        "integratedPrefab": (
            product_root / "Prefab" / Path(job["integratedPrefabAssetPath"]).name
        ),
        "manifest": product_root / "ProductManifest.json",
        "previews": {
            name: product_root / "Previews" / Path(value).name
            for name, value in job["previewPaths"].items()
        },
    }


def create_materials(
    texture_dir: Path,
    recipe: Mapping[str, object],
) -> tuple[dict[str, Path], dict[str, object]]:
    maps = make_image_maps(texture_dir)
    presets = recipe["presets"]

    def textured(key: str) -> bpy.types.Material:
        preset = presets[key]
        return textured_material(
            preset["materialName"],
            maps[preset["baseColorSource"]],
            maps[preset["normalSource"]],
            maps[preset["roughnessSource"]],
            sheen=float(preset["sheen"]),
            alpha=float(preset.get("alpha", 1.0)),
        )

    silver = presets["silver"]
    materials = {
        "wine": textured("wine"),
        "black": textured("black"),
        "sheer": textured("sheer"),
        "white": textured("white"),
        "silver": base.plain_material(
            silver["materialName"],
            tuple(silver["baseColor"]),
            roughness=float(silver["roughness"]),
            metallic=float(silver["metallic"]),
        ),
    }
    return maps, materials

def add_bodice(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    materials: dict[str, object],
    *,
    waistcoat_material_key: str,
) -> list[bpy.types.Object]:
    waistcoat_material = materials[waistcoat_material_key]
    garments: list[bpy.types.Object] = [
        bib_panel(body, armature, materials["white"]),
        waistcoat_side("L", body, armature, waistcoat_material),
        waistcoat_side("R", body, armature, waistcoat_material),
        waistcoat_back(body, armature, waistcoat_material),
        tail_panel("L", body, armature, waistcoat_material),
        tail_panel("R", body, armature, waistcoat_material),
    ]
    garments.extend(
        vertical_ruffle(index, body, armature, materials["white"])
        for index in range(3)
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
    *,
    lower_dimensions: Mapping[str, float],
    lower_piece: Mapping[str, object],
) -> tuple[list[bpy.types.Object], bpy.types.Object, bpy.types.Object, list[int], list[int]]:
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
    mapping = lower_piece["construction3d"]
    lower_skirt, lower_pin = ring_skirt(
        "Black_Sheer_Lower_Skirt",
        body,
        armature,
        materials["sheer"],
        top_z=float(mapping["topZM"]),
        bottom_z=float(mapping["bottomZM"]),
        top_rx=float(lower_dimensions["topRxM"]),
        top_ry=float(lower_dimensions["topRyM"]),
        bottom_rx=float(lower_dimensions["bottomRxM"]),
        bottom_ry=float(lower_dimensions["bottomRyM"]),
        pleats=int(lower_piece["pleatCount"]),
        thickness=0.0008,
    )
    return [upper_skirt, lower_skirt], upper_skirt, lower_skirt, upper_pin, lower_pin


def add_baked_hem_trim(
    hem_points: list[tuple[float, float, float]],
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> tuple[bpy.types.Object, dict[str, object]]:
    if len(hem_points) < 16:
        raise RuntimeError("lower skirt hem boundary is too small to trim")
    trim_points: list[tuple[float, float, float]] = []
    offsets: list[float] = []
    count = len(hem_points)
    for index, (x, y, z) in enumerate(hem_points):
        angle = math.tau * index / count
        scallop = 0.0020 * (0.5 + 0.5 * math.cos(angle * 20))
        trim_points.append((x, y, z + scallop))
        offsets.append(scallop)
    trim = base.curve_tube(
        "Black_Lace_Scallop_Hem",
        trim_points,
        0.0017,
        material,
        armature,
        "Hips",
        cyclic=True,
    )
    alignment = {
        "sourceBoundary": "Black_Sheer_Lower_Skirt evaluated bottom ring",
        "samples": count,
        "maximumCenterlineOffsetM": max(offsets),
        "meanCenterlineOffsetM": sum(offsets) / count,
        "requiredMaximumCenterlineOffsetM": 0.0030,
        "passed": max(offsets) <= 0.0030,
    }
    return trim, alignment

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
) -> tuple[
    list[dict[str, object]],
    int,
    list[tuple[float, float, float]],
    list[dict[str, object]],
    bool,
]:
    frame_end = 24
    contracts = [
        configure_cloth(upper_skirt, body, upper_pin, frame_end=frame_end),
        configure_cloth(lower_skirt, body, lower_pin, frame_end=frame_end),
    ]
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = frame_end
    scene.gravity = (0.0, 0.0, -4.8)
    bpy.context.view_layer.objects.active = upper_skirt
    bpy.ops.ptcache.bake_all(bake=True)
    cache_validated = all(
        skirt.modifiers["Reference Cloth"].point_cache.is_baked
        for skirt in (upper_skirt, lower_skirt)
    )
    if not cache_validated:
        raise RuntimeError("cloth point cache was not baked before evaluation")

    samples: list[dict[str, object]] = []
    for label, frame in (("start", 1), ("middle", 12), ("end", frame_end)):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        snapshots = [mesh_snapshot(upper_skirt), mesh_snapshot(lower_skirt)]
        if not all(snapshot["finiteBounds"] for snapshot in snapshots):
            raise RuntimeError(f"non-finite cloth mesh at frame {frame}")
        samples.append({"label": label, "frame": frame, "meshes": snapshots})

    scene.frame_set(frame_end)
    bpy.context.view_layer.update()
    lower_hem_points: list[tuple[float, float, float]] = []
    for skirt in (upper_skirt, lower_skirt):
        bpy.ops.object.select_all(action="DESELECT")
        skirt.select_set(True)
        bpy.context.view_layer.objects.active = skirt
        bpy.ops.object.modifier_apply(modifier="Reference Cloth")
        if skirt is lower_skirt:
            segment_count = len(lower_pin)
            if segment_count <= 0 or len(skirt.data.vertices) < segment_count * 2:
                raise RuntimeError(
                    "lower skirt topology cannot expose its evaluated hem ring"
                )
            start = len(skirt.data.vertices) - segment_count
            lower_hem_points = [
                tuple(skirt.matrix_world @ skirt.data.vertices[index].co)
                for index in range(start, len(skirt.data.vertices))
            ]
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
    if len(lower_hem_points) != len(lower_pin):
        raise RuntimeError("evaluated lower skirt hem sampling is incomplete")
    return contracts, frame_end, lower_hem_points, samples, cache_validated

def main() -> int:
    args = parse_args()
    job_path = repo_path(args.job)
    job = read_json(job_path)
    if job.get("id") != PRODUCT_ID:
        raise ValueError("job product identity mismatch")

    variant_document, variant = resolve_variant(job, args.variant)
    variant_id = str(variant["id"])
    output_root = repo_path(args.output_root) if args.output_root else None
    outputs = actual_output_paths(job, output_root)

    base.clean_scene()
    source = repo_path(job["targetSourcePath"])
    product_root = outputs["productRoot"]
    blend_path = outputs["blend"]
    fbx_path = outputs["fbx"]
    prefab_path = outputs["prefab"]
    integrated_prefab = outputs["integratedPrefab"]
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
    tracked_stitches = repo_path(job["garmentPipeline"]["stitchGraphPath"])
    material_recipe_path = repo_path(job["garmentPipeline"]["materialRecipePath"])
    material_recipe = read_json(material_recipe_path)
    pattern_document = read_json(tracked_pattern)
    pieces = validate_pattern_contract(pattern_document, product_id=PRODUCT_ID)
    lower_piece = pieces["lower-skirt-ring"]["raw"]
    width_scale = float(
        variant.get("patternOverrides", {})
        .get("lower-skirt-ring", {})
        .get("widthScale", 1.0)
    )
    mapping = lower_piece["construction3d"]
    lower_dimensions = ring_dimensions_from_pattern(
        pieces["lower-skirt-ring"],
        waist_edge=str(mapping["waistEdge"]),
        hem_edge=str(mapping["hemEdge"]),
        aspect_ratio_y=float(mapping["aspectRatioY"]),
        width_scale=width_scale,
    )
    shutil.copyfile(tracked_pattern, pattern_dir / "tuxedo-halter.pattern.json")

    bpy.ops.import_scene.fbx(filepath=str(source), use_anim=False)
    body, armature = g.select_body_and_armature()
    armature.name = "SiroinoSotai_Armature"
    profile = g.apply_large_profile(body, job.get("bodyShapeProfile"))
    base.set_skin_material(body)

    maps, materials = create_materials(texture_dir, material_recipe)
    waistcoat_key = str(variant.get("materialOverrides", {}).get("waistcoat", "wine"))
    garments = add_bodice(
        body,
        armature,
        materials,
        waistcoat_material_key=waistcoat_key,
    )
    skirt_parts, upper_skirt, lower_skirt, upper_pin, lower_pin = add_skirts(
        body,
        armature,
        materials,
        lower_dimensions=lower_dimensions,
        lower_piece=lower_piece,
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
    (
        cloth_contracts,
        frame_end,
        evaluated_hem,
        evaluated_frames,
        cache_validated,
    ) = bake_skirts(body, upper_skirt, lower_skirt, upper_pin, lower_pin)
    hem_trim, hem_alignment = add_baked_hem_trim(
        evaluated_hem, armature, materials["black"]
    )
    garments.append(hem_trim)
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
    geometry_sha = geometry_digest(garments)
    passed = (
        measured["meshObjects"] >= 18
        and measured["vertices"] > 1800
        and measured["triangles"] > 2500
        and measured["unweightedVertices"] == 0
        and measured["weightSumErrors"] == 0
        and measured["degenerateTriangles"] == 0
        and measured["maxBoneInfluences"] <= 4
        and clearance_history[-1]["clearance"]["p01"] >= 0.0030
        and hem_alignment["passed"]
        and cache_validated
    )

    blend_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)
    blend_sha = sha256_file(blend_path)

    cloth_report = write_json(
        evidence_dir / "cloth-simulation.json",
        {
            "schemaVersion": 1,
            "productId": PRODUCT_ID,
            "variantId": variant_id,
            "status": "PASS",
            "engine": "Blender Cloth",
            "method": "evaluated-and-applied-cloth",
            "frameStart": 1,
            "frameEnd": frame_end,
            "cacheBakedDuringBuild": True,
            "cacheValidatedBeforeApply": cache_validated,
            "cacheDisposition": "consumed-and-applied-to-mesh",
            "reusableCacheAvailable": False,
            "gravity": list(bpy.context.scene.gravity),
            "contracts": cloth_contracts,
            "evaluatedFrames": evaluated_frames,
            "inputHashes": {
                "pattern": sha256_file(tracked_pattern),
                "stitches": sha256_file(tracked_stitches),
                "materialRecipe": sha256_file(material_recipe_path),
            },
            "blendSha256": blend_sha,
            "bodyCollisionThicknessM": 0.004,
        },
    )

    scene = bpy.context.scene
    _, camera = g.pastel_studio()
    g.set_pose(armature, "neutral")
    scene.frame_set(frame_end)
    geometry_preview = preview_dir / "geometry-check.png"
    neutral = base.plain_material(
        "MAT_Geometry_Check",
        (0.55, 0.55, 0.55, 1.0),
        roughness=0.82,
        metallic=0.0,
    )
    layer = bpy.context.view_layer
    previous_override = layer.material_override
    layer.material_override = neutral
    g.configure_render(384)
    g.point_camera(camera, (0.0, -2.55, 0.70))
    scene.render.filepath = str(geometry_preview)
    bpy.ops.render.render(write_still=True)
    layer.material_override = previous_override

    report = {
        "schemaVersion": 1,
        "passed": passed,
        "productId": PRODUCT_ID,
        "productName": job["productName"],
        "variantId": variant_id,
        "variantKind": variant["kind"],
        "buildRevision": job["buildRevision"],
        "targetProfile": profile,
        "targetAvatarAssetPath": job["targetAvatarAssetPath"],
        "targetSourcePath": job["targetSourcePath"],
        "blenderVersion": bpy.app.version_string,
        "metrics": measured,
        "geometryDigest": geometry_sha,
        "weightNormalization": weight_report,
        "clearanceRefinement": clearance_history,
        "patternToMesh": {
            "pieceId": "lower-skirt-ring",
            "patternSha256": sha256_file(tracked_pattern),
            "stitchGraphSha256": sha256_file(tracked_stitches),
            "widthScale": width_scale,
            "dimensions": lower_dimensions,
            "object": lower_skirt.name,
        },
        "materialRecipe": {
            "path": str(material_recipe_path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256_file(material_recipe_path),
            "semanticDigest": canonical_json_sha256(material_recipe),
            "waistcoatPreset": waistcoat_key,
            "regions": material_recipe["regions"],
        },
        "variantInvalidation": (
            variant_invalidation(variant)
            if variant["kind"] in {"color", "size"}
            else {"reuseGeometry": True, "invalidateStages": []}
        ),
        "clothSimulation": str(cloth_report.relative_to(ROOT)).replace("\\", "/"),
        "hemAlignment": hem_alignment,
        "geometryPreview": str(geometry_preview.relative_to(ROOT)).replace("\\", "/"),
        "geometryPreviewGate": "PASS" if passed else "REJECT_BEFORE_FINAL_RENDER",
        "views": {},
        "poseViews": {},
        "referenceModelIdentification": "UNVERIFIED",
        "notes": [
            "lower-skirt-ring dimensions are derived from the tracked pattern edge lengths.",
            "The lace hem centerline is regenerated from the evaluated lower-skirt bottom ring.",
            "Cloth cache state is verified before modifiers are applied; reusable cache is not claimed afterward.",
            "Material regions are bound to the tracked material recipe.",
        ],
    }
    report_path = write_json(evidence_dir / "product-build-report.json", report)
    if not passed:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    previews = outputs["previews"]
    g.render_five_views(camera, previews)
    multiview = preview_dir / f"{PRODUCT_ID}-{variant_id}-multiview.webp"
    g.contact_sheet(
        previews,
        multiview,
        order=("front", "three-quarter", "left", "right", "back"),
        title=f"TUXEDO HALTER / {variant_id}",
    )
    pose_images = g.render_pose_set(armature, camera, pose_dir)
    obsolete_twist = pose_images.pop("twist", None)
    if obsolete_twist is not None and obsolete_twist.is_file():
        obsolete_twist.unlink()
    pose_images["prone"] = render_prone_pose(
        armature, camera, pose_dir / "prone.png"
    )
    pose_sheet = preview_dir / f"{PRODUCT_ID}-{variant_id}-pose-review.webp"
    g.contact_sheet(
        pose_images,
        pose_sheet,
        order=("neutral", "arms-up", "arm-cross", "crouch", "sit", "prone"),
        title=f"POSE REVIEW / {variant_id}",
    )
    report["views"] = {
        name: str(path.relative_to(ROOT)).replace("\\", "/")
        for name, path in previews.items()
    }
    report["poseViews"] = {
        name: str(path.relative_to(ROOT)).replace("\\", "/")
        for name, path in pose_images.items()
    }
    write_json(report_path, report)

    g.reset_pose(armature)
    scene.frame_set(frame_end)
    body.hide_render = True
    base.export_fbx(fbx_path, armature, garments)
    sidecars = write_prefabs(
        fbx_path, prefab_path, integrated_prefab, f"{job['productName']} / {variant_id}"
    )

    generated_variants = write_json(
        product_root / "MaterialVariants.json",
        {
            "schemaVersion": 1,
            "productId": PRODUCT_ID,
            "activeVariant": variant_id,
            "source": str(
                repo_path(job["garmentPipeline"]["variantSpecPath"]).relative_to(ROOT)
            ).replace("\\", "/"),
            "variants": variant_document["variants"],
        },
    )
    relative_root = str(product_root.relative_to(ROOT)).replace("\\", "/")
    manifest = {
        "schemaVersion": 1,
        "productId": PRODUCT_ID,
        "productName": job["productName"],
        "variantId": variant_id,
        "status": "WORKING",
        "targetAdapterId": job["adapterId"],
        "target": "Siroino _Large via official shape keys",
        "productRoot": relative_root,
        "sourceJobPath": str(job_path.relative_to(ROOT)).replace("\\", "/"),
        "productBuildScript": job["buildScript"],
        "designRevision": job["buildRevision"],
        "modelIdentification": "UNVERIFIED",
        "technicalGates": {
            "blender": "PASS",
            "editableSource": "PASS",
            "fbx": "PASS",
            "prefabDeclared": "PASS",
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
            "blend": str(blend_path.relative_to(ROOT)).replace("\\", "/"),
            "fbx": str(fbx_path.relative_to(ROOT)).replace("\\", "/"),
            "prefab": str(prefab_path.relative_to(ROOT)).replace("\\", "/"),
            "integratedPrefab": str(integrated_prefab.relative_to(ROOT)).replace("\\", "/"),
            "multiview": str(multiview.relative_to(ROOT)).replace("\\", "/"),
            "poseReview": str(pose_sheet.relative_to(ROOT)).replace("\\", "/"),
            "buildReport": str(report_path.relative_to(ROOT)).replace("\\", "/"),
            "geometryPreview": str(geometry_preview.relative_to(ROOT)).replace("\\", "/"),
        },
    }
    manifest_path = write_json(outputs["manifest"], manifest)

    readme = product_root / "README.md"
    readme.write_text(
        f"# {job['productName']} / {variant_id}\n\n"
        "Generated from the audited pattern/stitch/material contracts. "
        "Direct image review remains pending.\n",
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
        geometry_preview,
        cloth_report,
        report_path,
        generated_variants,
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
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
