#!/usr/bin/env python3
"""Build Cyber Kawaii for Siroino _Large with shape keys and deforming skirt weights."""
from __future__ import annotations

import json
from typing import Any

import bpy
from mathutils.kdtree import KDTree

import siroino_cyber_kawaii_standard_build as standard

ORIGINAL_CONTACT_SHEET = standard.legacy.g.contact_sheet
ORIGINAL_APPLY_LARGE_PROFILE = standard.legacy.g.apply_large_profile
ORIGINAL_CREATE_OUTFIT = standard.create_outfit
ORIGINAL_REWRITE_HANDOFF = standard.rewrite_handoff
LAST_TARGET_PROFILE: dict[str, Any] = {}
SKIRT_OBJECTS = {
    "Black_Pink_Plaid_Pleated_Skirt",
    "White_Ruffle_Underskirt",
    "Black_Skirt_Waistband",
    "Pink_Underskirt_Hem",
}


def contact_sheet(images, output, *, order, title):
    if title == "CYBER KAWAII LAYERED SET / SIROINO _LARGE":
        title = "CYBER KAWAII LAYERED SET / SIROINO _LARGE (SHAPE PROFILE)"
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
            "requestedShapeKeys": {name: float(value) for name, value in requested.items()},
        }
    )
    LAST_TARGET_PROFILE = dict(result)
    return result


def transfer_deforming_weights(body, armature, garment) -> dict[str, float | int]:
    tree = KDTree(len(body.data.vertices))
    for vertex in body.data.vertices:
        tree.insert(body.matrix_world @ vertex.co, vertex.index)
    tree.balance()
    for group in list(garment.vertex_groups):
        garment.vertex_groups.remove(group)
    groups = {group.name: garment.vertex_groups.new(name=group.name) for group in body.vertex_groups}
    if "Hips" not in groups:
        groups["Hips"] = garment.vertex_groups.new(name="Hips")
    garment.parent = armature
    modifier = next((item for item in garment.modifiers if item.type == "ARMATURE"), None)
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
                source_weights[name] = source_weights.get(name, 0.0) + float(assignment.weight)
        height = max(0.0, min(1.0, (vertex.co.z - z_min) / z_span))
        hip_anchor = 0.34 + 0.46 * height
        side_factor = min(1.0, abs(vertex.co.x) / 0.075)
        leg_anchor = 0.22 * (1.0 - height) * side_factor
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
            ((name, weight) for name, weight in weights.items() if weight > 1e-8),
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
        "minimumHipAnchor": 0.34,
        "maximumHipAnchor": 0.80,
        "maximumLegAnchor": 0.22,
    }


def create_deforming_outfit(body, armature, materials):
    garments = ORIGINAL_CREATE_OUTFIT(body, armature, materials)
    audits = {}
    for garment in garments:
        if garment.name in SKIRT_OBJECTS:
            audits[garment.name] = transfer_deforming_weights(body, armature, garment)
    if set(audits) != SKIRT_OBJECTS:
        raise RuntimeError(f"Required deforming skirt objects missing: {sorted(SKIRT_OBJECTS - set(audits))}")
    bpy.context.scene["cyberKawaiiSkirtWeightAudit"] = json.dumps(audits, sort_keys=True)
    return garments


def rewrite_shape_profile_handoff(job: dict, return_code: int) -> None:
    ORIGINAL_REWRITE_HANDOFF(job, return_code)
    profile = dict(LAST_TARGET_PROFILE)
    if not profile:
        raise RuntimeError("Cyber Kawaii build completed without target shape-profile evidence")
    report_path = standard.repo_path(job["artifactDir"]) / "product-build-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    skirt_audit = json.loads(bpy.context.scene.get("cyberKawaiiSkirtWeightAudit", "{}"))
    report["targetProfile"] = profile
    report["skirtWeightTransfer"] = skirt_audit
    report["visualRevision"] = "v5-large-shape-profile-deforming-skirt"
    report["notes"] = [
        "The tracked SiroinoSotai_PC FBX is the source body.",
        "Official Siroino _Large shape keys are baked before garment extraction and fitting.",
        "Skirt shells use nearest official body weights plus continuous Hips and side upper-leg anchors.",
        "Each generated vertex is reduced to at most four normalized bone influences.",
        "Configured shape keys are required and never silently replaced by the neutral body.",
    ]
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_path = standard.repo_path(job["productManifestPath"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "productName": job["productName"],
            "targetAdapterId": job["adapterId"],
            "target": profile["profile"],
            "designRevision": "v5-large-shape-profile-deforming-skirt",
            "shapeProfile": profile,
            "skirtWeightTransfer": skirt_audit,
        }
    )
    manifest["handoff"]["lastAttempt"] = {
        "result": "HOSTED_MODELED" if return_code == 0 and report.get("passed") else "REJECTED",
        "visualRevision": "v5-large-shape-profile-deforming-skirt",
        "shapeProfile": profile["profile"],
    }
    manifest["technicalGates"]["shapeProfileApplied"] = "PASS" if profile.get("appliedShapeKeys") else "FAIL"
    manifest["technicalGates"]["skirtWeightTransfer"] = "PASS" if len(skirt_audit) == len(SKIRT_OBJECTS) else "FAIL"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    standard.refresh_hashes(standard.repo_path(job["productRoot"]))


def main() -> int:
    standard.legacy.g.contact_sheet = contact_sheet
    standard.apply_standard_profile = apply_configured_shape_profile
    standard.create_outfit = create_deforming_outfit
    standard.rewrite_handoff = rewrite_shape_profile_handoff
    return standard.main()


if __name__ == "__main__":
    raise SystemExit(main())
