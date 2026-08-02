#!/usr/bin/env python3
"""Build Cyber Kawaii for Siroino _Large with a tracked production contract."""
from __future__ import annotations

from dataclasses import asdict
import json
import math
from pathlib import Path
from typing import Any

import bpy
from mathutils.kdtree import KDTree

import cyber_kawaii_skirt_contract as skirt_contract
import siroino_cyber_kawaii_standard_build as standard

ROOT = Path(__file__).resolve().parents[1]
PATTERN_CONTRACT_PATH = (
    ROOT
    / "Assets/GenWorks/siroino-cyber-kawaii-large/Source/Patterns/"
    "cyber-kawaii-skirt.pattern.json"
)
PATTERN_CONTRACT = skirt_contract.load_contract(PATTERN_CONTRACT_PATH)

ORIGINAL_CONTACT_SHEET = standard.legacy.g.contact_sheet
ORIGINAL_APPLY_LARGE_PROFILE = standard.legacy.g.apply_large_profile
ORIGINAL_CREATE_OUTFIT = standard.create_outfit
ORIGINAL_REWRITE_HANDOFF = standard.rewrite_handoff
LAST_TARGET_PROFILE: dict[str, Any] = {}
SKIRT_OBJECTS = set(skirt_contract.REQUIRED_LAYERS)
SILHOUETTE_PROFILES = skirt_contract.silhouette_profiles(PATTERN_CONTRACT)


def contact_sheet(images, output, *, order, title):
    if title == "CYBER KAWAII LAYERED SET / SIROINO _LARGE":
        title = "CYBER KAWAII LAYERED SET / SIROINO _LARGE (FITTED SILHOUETTE)"
    return ORIGINAL_CONTACT_SHEET(images, output, order=order, title=title)


def apply_configured_shape_profile(body, requested=None) -> dict[str, object]:
    global LAST_TARGET_PROFILE
    requested = requested or {
        "All_L": 1.0,
        "Chest_L": 1.0,
        "Hips_01_L": 1.0,
        "UpperLeg_L": 1.0,
        "Breasts_L": 0.65,
    }
    result = ORIGINAL_APPLY_LARGE_PROFILE(body, requested)
    result.update(
        {
            "profile": "Siroino _Large via official shape keys",
            "sourceBody": "Assets/SiroinoWorks/SiroinoSotai/FBX/SiroinoSotai_PC.fbx",
            "profileMode": "shape-key-bake",
            "requestedShapeKeys": {
                name: float(value) for name, value in requested.items()
            },
        }
    )
    LAST_TARGET_PROFILE = dict(result)
    return result


def reshape_skirt_shell(garment) -> dict[str, float | int]:
    profile = SILHOUETTE_PROFILES[garment.name]
    vertices = list(garment.data.vertices)
    z_min = min(vertex.co.z for vertex in vertices)
    z_max = max(vertex.co.z for vertex in vertices)
    z_span = max(1e-6, z_max - z_min)

    rings: dict[float, list] = {}
    for vertex in vertices:
        rings.setdefault(round(float(vertex.co.z), 5), []).append(vertex)

    for ring in rings.values():
        rx = max(abs(float(vertex.co.x)) for vertex in ring)
        ry = max(abs(float(vertex.co.y)) for vertex in ring)
        rx = max(rx, 1e-6)
        ry = max(ry, 1e-6)
        for vertex in ring:
            height = max(
                0.0,
                min(1.0, (float(vertex.co.z) - z_min) / z_span),
            )
            fitted_height = height * height * (3.0 - 2.0 * height)
            radial_scale = profile["bottomScale"] + (
                profile["topScale"] - profile["bottomScale"]
            ) * fitted_height
            normalized_radius = math.sqrt(
                (float(vertex.co.x) / rx) ** 2
                + (float(vertex.co.y) / ry) ** 2
            )
            if normalized_radius > 1e-8:
                softened_radius = 1.0 + profile["pleatScale"] * (
                    normalized_radius - 1.0
                )
                correction = softened_radius / normalized_radius
            else:
                correction = 1.0
            vertex.co.x *= radial_scale * correction
            vertex.co.y *= radial_scale * correction
            vertex.co.z += profile["zOffset"]

    garment.data.update(calc_edges=True)
    return {
        "vertices": len(vertices),
        "ringCount": len(rings),
        "topScale": profile["topScale"],
        "bottomScale": profile["bottomScale"],
        "pleatScale": profile["pleatScale"],
        "zOffset": profile["zOffset"],
    }


def transfer_deforming_weights(body, armature, garment) -> dict[str, float | int]:
    tree = KDTree(len(body.data.vertices))
    for vertex in body.data.vertices:
        tree.insert(body.matrix_world @ vertex.co, vertex.index)
    tree.balance()
    for group in list(garment.vertex_groups):
        garment.vertex_groups.remove(group)
    groups = {
        group.name: garment.vertex_groups.new(name=group.name)
        for group in body.vertex_groups
    }
    if "Hips" not in groups:
        groups["Hips"] = garment.vertex_groups.new(name="Hips")
    garment.parent = armature
    modifier = next(
        (item for item in garment.modifiers if item.type == "ARMATURE"),
        None,
    )
    if modifier is None:
        modifier = garment.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True
    z_values = [vertex.co.z for vertex in garment.data.vertices]
    z_min = min(z_values)
    z_span = max(1e-6, max(z_values) - z_min)
    fallback_vertices = 0
    maximum_influences = 0
    for vertex in garment.data.vertices:
        _, source_index, _ = tree.find(garment.matrix_world @ vertex.co)
        source_weights: dict[str, float] = {}
        for assignment in body.data.vertices[source_index].groups:
            name = body.vertex_groups[assignment.group].name
            if assignment.weight > 1e-8:
                source_weights[name] = source_weights.get(name, 0.0) + float(
                    assignment.weight
                )
        height = max(0.0, min(1.0, (vertex.co.z - z_min) / z_span))
        hip_anchor = 0.42 + 0.46 * height
        side_factor = min(1.0, abs(vertex.co.x) / 0.070)
        leg_anchor = 0.30 * (1.0 - height) * side_factor
        source_scale = max(0.0, 1.0 - hip_anchor - leg_anchor)
        weights = {
            name: weight * source_scale
            for name, weight in source_weights.items()
            if name in groups
        }
        weights["Hips"] = weights.get("Hips", 0.0) + hip_anchor
        side_group = "UpperLeg_L" if vertex.co.x >= 0.0 else "UpperLeg_R"
        if side_group in groups:
            weights[side_group] = weights.get(side_group, 0.0) + leg_anchor
        else:
            weights["Hips"] += leg_anchor
        ranked = sorted(
            (
                (name, weight)
                for name, weight in weights.items()
                if weight > 1e-8
            ),
            key=lambda item: item[1],
            reverse=True,
        )[:4]
        total = sum(weight for _, weight in ranked)
        if total <= 1e-8:
            ranked = [("Hips", 1.0)]
            total = 1.0
            fallback_vertices += 1
        normalized = {
            name: weight / total
            for name, weight in ranked
            if weight / total > 1e-5
        }
        maximum_influences = max(maximum_influences, len(normalized))
        for name, weight in normalized.items():
            groups[name].add([vertex.index], weight, "REPLACE")
    return {
        "vertices": len(garment.data.vertices),
        "fallbackVertices": fallback_vertices,
        "maximumInfluences": maximum_influences,
        "minimumHipAnchor": 0.42,
        "maximumHipAnchor": 0.88,
        "maximumLegAnchor": 0.30,
    }


def create_deforming_outfit(body, armature, materials):
    garments = ORIGINAL_CREATE_OUTFIT(body, armature, materials)
    weight_audits = {}
    silhouette_audits = {}
    for garment in garments:
        if garment.name in SKIRT_OBJECTS:
            silhouette_audits[garment.name] = reshape_skirt_shell(garment)
            weight_audits[garment.name] = transfer_deforming_weights(
                body,
                armature,
                garment,
            )
    if set(weight_audits) != SKIRT_OBJECTS:
        raise RuntimeError(
            "Required deforming skirt objects missing: "
            f"{sorted(SKIRT_OBJECTS - set(weight_audits))}"
        )
    bpy.context.scene["cyberKawaiiSkirtWeightAudit"] = json.dumps(
        weight_audits,
        sort_keys=True,
    )
    bpy.context.scene["cyberKawaiiSilhouetteAudit"] = json.dumps(
        silhouette_audits,
        sort_keys=True,
    )
    return garments


def rewrite_shape_profile_handoff(job: dict, return_code: int) -> None:
    ORIGINAL_REWRITE_HANDOFF(job, return_code)
    profile = dict(LAST_TARGET_PROFILE)
    if not profile:
        raise RuntimeError(
            "Cyber Kawaii build completed without target shape-profile evidence"
        )
    report_path = standard.repo_path(job["artifactDir"]) / "product-build-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    skirt_audit = json.loads(
        bpy.context.scene.get("cyberKawaiiSkirtWeightAudit", "{}")
    )
    silhouette_audit = json.loads(
        bpy.context.scene.get("cyberKawaiiSilhouetteAudit", "{}")
    )
    pipeline_evidence = asdict(
        skirt_contract.evidence_state(
            ROOT,
            PATTERN_CONTRACT_PATH,
            PATTERN_CONTRACT,
        )
    )
    report["targetProfile"] = profile
    report["skirtWeightTransfer"] = skirt_audit
    report["skirtSilhouette"] = silhouette_audit
    report["productionPipeline"] = pipeline_evidence
    report["visualRevision"] = "v6-large-fitted-skirt-silhouette"
    report["notes"] = [
        "The tracked SiroinoSotai_PC FBX is the source body.",
        "Official Siroino _Large shape keys are baked before garment extraction and fitting.",
        "The reviewed v6 silhouette values now come from the tracked panel and seam contract.",
        "The skirt stays close to the hips through the upper section and flares only toward the hem.",
        "Skirt shells use nearest official body weights plus stronger Hips and side upper-leg anchors.",
        "Each generated vertex is reduced to at most four normalized bone influences.",
        "GarmentCode, ZOZO Contact Solver, and Material Maker remain PENDING until their required source evidence exists.",
    ]
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest_path = standard.repo_path(job["productManifestPath"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "productName": job["productName"],
            "targetAdapterId": job["adapterId"],
            "target": profile["profile"],
            "designRevision": "v6-large-fitted-skirt-silhouette",
            "shapeProfile": profile,
            "skirtWeightTransfer": skirt_audit,
            "skirtSilhouette": silhouette_audit,
            "productionPipeline": pipeline_evidence,
        }
    )
    manifest["handoff"]["lastAttempt"] = {
        "result": (
            "HOSTED_MODELED"
            if return_code == 0 and report.get("passed")
            else "REJECTED"
        ),
        "visualRevision": "v6-large-fitted-skirt-silhouette",
        "shapeProfile": profile["profile"],
    }
    gates = manifest["technicalGates"]
    gates["shapeProfileApplied"] = (
        "PASS" if profile.get("appliedShapeKeys") else "FAIL"
    )
    gates["skirtWeightTransfer"] = (
        "PASS" if len(skirt_audit) == len(SKIRT_OBJECTS) else "FAIL"
    )
    gates["skirtSilhouette"] = (
        "PASS" if len(silhouette_audit) == len(SKIRT_OBJECTS) else "FAIL"
    )
    gates["patternContract"] = pipeline_evidence["pattern_contract"]
    gates["garmentCode"] = pipeline_evidence["garment_code"]
    gates["zozoContactSolver"] = pipeline_evidence["zozo_contact_solver"]
    gates["materialMakerSource"] = pipeline_evidence["material_maker_source"]
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    standard.refresh_hashes(standard.repo_path(job["productRoot"]))


def main() -> int:
    standard.legacy.g.contact_sheet = contact_sheet
    standard.apply_standard_profile = apply_configured_shape_profile
    standard.create_outfit = create_deforming_outfit
    standard.rewrite_handoff = rewrite_shape_profile_handoff
    return standard.main()


if __name__ == "__main__":
    raise SystemExit(main())
