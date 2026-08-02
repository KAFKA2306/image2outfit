#!/usr/bin/env python3
"""Build Cyber Kawaii for Siroino _Large with a body-measured skirt contract."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import bpy
from mathutils.kdtree import KDTree

import cyber_kawaii_skirt_contract as pattern_contract
import siroino_cyber_kawaii_standard_build as standard

ROOT = Path(__file__).resolve().parents[1]
PATTERN_PATH = (
    ROOT
    / "Assets/GenWorks/siroino-cyber-kawaii-large/Source/Patterns/"
    "cyber-kawaii-skirt.pattern.json"
)
SOLVER_MESH_PATH = (
    ROOT
    / "Assets/GenWorks/siroino-cyber-kawaii-large/Source/Solver/"
    "cyber-kawaii-skirt-solved.obj"
)
SOLVER_REPORT_PATH = (
    ROOT
    / "Assets/GenWorks/siroino-cyber-kawaii-large/Evidence/Commercial/"
    "penetration-report.json"
)
MATERIAL_SOURCE_ROOT = (
    ROOT
    / "Assets/GenWorks/siroino-cyber-kawaii-large/Source/Materials"
)

ORIGINAL_CONTACT_SHEET = standard.legacy.g.contact_sheet
ORIGINAL_APPLY_LARGE_PROFILE = standard.legacy.g.apply_large_profile
ORIGINAL_CREATE_OUTFIT = standard.create_outfit
ORIGINAL_REWRITE_HANDOFF = standard.rewrite_handoff
LAST_TARGET_PROFILE: dict[str, Any] = {}
LAST_PATTERN_AUDIT: dict[str, Any] = {}
SKIRT_OBJECTS = set(pattern_contract.REQUIRED_LAYER_IDS)


def contact_sheet(images, output, *, order, title):
    if title == "CYBER KAWAII LAYERED SET / SIROINO _LARGE":
        title = "CYBER KAWAII LAYERED SET / SIROINO _LARGE (PATTERN FIT)"
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


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        raise RuntimeError("cannot calculate a body section from zero vertices")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _body_section(
    body: bpy.types.Object,
    *,
    z: float,
    half_band: float,
) -> tuple[float, float, int]:
    points = [
        vertex.co
        for vertex in body.data.vertices
        if abs(float(vertex.co.z) - z) <= half_band
    ]
    if len(points) < 24:
        points = sorted(
            (vertex.co for vertex in body.data.vertices),
            key=lambda point: abs(float(point.z) - z),
        )[:96]
    radius_x = _quantile([abs(float(point.x)) for point in points], 0.98)
    radius_y = _quantile([abs(float(point.y)) for point in points], 0.98)
    if radius_x <= 0.0 or radius_y <= 0.0:
        raise RuntimeError(f"invalid body section at z={z}")
    return radius_x, radius_y, len(points)


def _interpolate_radii(
    rings: tuple[tuple[float, float, float], ...],
    z: float,
) -> tuple[float, float]:
    if z >= rings[0][0]:
        return rings[0][1], rings[0][2]
    if z <= rings[-1][0]:
        return rings[-1][1], rings[-1][2]
    for upper, lower in zip(rings, rings[1:]):
        if upper[0] >= z >= lower[0]:
            span = max(1e-9, upper[0] - lower[0])
            amount = (upper[0] - z) / span
            return (
                upper[1] * (1.0 - amount) + lower[1] * amount,
                upper[2] * (1.0 - amount) + lower[2] * amount,
            )
    raise RuntimeError(f"could not interpolate pattern ring at z={z}")


def _section_extents(
    garment: bpy.types.Object,
    *,
    z: float,
    half_band: float,
) -> tuple[float, float]:
    points = [
        vertex.co
        for vertex in garment.data.vertices
        if abs(float(vertex.co.z) - z) <= half_band
    ]
    if len(points) < 8:
        points = sorted(
            (vertex.co for vertex in garment.data.vertices),
            key=lambda point: abs(float(point.z) - z),
        )[: max(16, len(garment.data.vertices) // 8)]
    return (
        max(abs(float(point.x)) for point in points),
        max(abs(float(point.y)) for point in points),
    )


def _fit_shell_to_pattern(
    garment: bpy.types.Object,
    rings: tuple[tuple[float, float, float], ...],
) -> dict[str, Any]:
    source_extents = [
        _section_extents(garment, z=z, half_band=0.004)
        for z, _, _ in rings
    ]
    source_rings = tuple(
        (ring[0], extent[0], extent[1])
        for ring, extent in zip(rings, source_extents)
    )
    for vertex in garment.data.vertices:
        z = float(vertex.co.z)
        target_x, target_y = _interpolate_radii(rings, z)
        current_x, current_y = _interpolate_radii(source_rings, z)
        vertex.co.x *= target_x / max(current_x, 1e-9)
        vertex.co.y *= target_y / max(current_y, 1e-9)
    garment.data.update(calc_edges=True)
    return {
        "objectName": garment.name,
        "resolvedRings": [
            {"z": z, "radiusX": radius_x, "radiusY": radius_y}
            for z, radius_x, radius_y in rings
        ],
        "sourceExtents": [
            {"z": ring[0], "radiusX": extent[0], "radiusY": extent[1]}
            for ring, extent in zip(rings, source_extents)
        ],
        "frontBackReductionApplied": any(
            target[2] < source[1]
            for target, source in zip(rings, source_extents)
        ),
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
        (item for item in garment.modifiers if item.type == "ARMATURE"), None
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
    global LAST_PATTERN_AUDIT
    pattern = pattern_contract.load_contract(PATTERN_PATH)
    body_sections: dict[str, tuple[float, float]] = {}
    section_audit: dict[str, dict[str, float | int]] = {}
    for anchor_id, spec in pattern["bodyAnchors"].items():
        radius_x, radius_y, samples = _body_section(
            body,
            z=float(spec["z"]),
            half_band=float(spec["halfBand"]),
        )
        body_sections[anchor_id] = (radius_x, radius_y)
        section_audit[anchor_id] = {
            "z": float(spec["z"]),
            "radiusX": radius_x,
            "radiusY": radius_y,
            "samples": samples,
        }

    garments = ORIGINAL_CREATE_OUTFIT(body, armature, materials)
    by_name = {garment.name: garment for garment in garments}
    pattern_audits: dict[str, Any] = {}
    weight_audits: dict[str, Any] = {}
    for layer in pattern_contract.layer_specs(pattern):
        garment = by_name.get(layer.object_name)
        if garment is None:
            raise RuntimeError(f"Required pattern layer missing: {layer.object_name}")
        resolved = pattern_contract.resolve_rings(layer, body_sections)
        pattern_audits[layer.object_name] = _fit_shell_to_pattern(garment, resolved)
        weight_audits[layer.object_name] = transfer_deforming_weights(
            body, armature, garment
        )

    if set(weight_audits) != SKIRT_OBJECTS:
        raise RuntimeError(
            f"Required deforming skirt objects missing: "
            f"{sorted(SKIRT_OBJECTS - set(weight_audits))}"
        )

    LAST_PATTERN_AUDIT = {
        "schemaVersion": 1,
        "patternPath": PATTERN_PATH.relative_to(ROOT).as_posix(),
        "patternSha256": pattern_contract.contract_sha256(PATTERN_PATH),
        "bodySections": section_audit,
        "layers": pattern_audits,
        "solverMode": (
            "zozo-contact-solver-output-present"
            if SOLVER_MESH_PATH.exists()
            else "body-measured-pattern-fit"
        ),
        "solverMeshPresent": SOLVER_MESH_PATH.exists(),
        "solverReportPresent": SOLVER_REPORT_PATH.exists(),
        "materialMakerSourcePresent": MATERIAL_SOURCE_ROOT.exists()
        and any(MATERIAL_SOURCE_ROOT.glob("*.ptex")),
    }
    bpy.context.scene["cyberKawaiiPatternAudit"] = json.dumps(
        LAST_PATTERN_AUDIT, sort_keys=True
    )
    bpy.context.scene["cyberKawaiiSkirtWeightAudit"] = json.dumps(
        weight_audits, sort_keys=True
    )
    return garments


def rewrite_shape_profile_handoff(job: dict, return_code: int) -> None:
    ORIGINAL_REWRITE_HANDOFF(job, return_code)
    profile = dict(LAST_TARGET_PROFILE)
    if not profile:
        raise RuntimeError("Cyber Kawaii build completed without target shape evidence")
    if not LAST_PATTERN_AUDIT:
        raise RuntimeError("Cyber Kawaii build completed without pattern-fit evidence")

    report_path = standard.repo_path(job["artifactDir"]) / "product-build-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    skirt_audit = json.loads(
        bpy.context.scene.get("cyberKawaiiSkirtWeightAudit", "{}")
    )
    report["targetProfile"] = profile
    report["patternPipeline"] = LAST_PATTERN_AUDIT
    report["skirtWeightTransfer"] = skirt_audit
    report["visualRevision"] = "v6-large-body-measured-pattern-fit"
    report["notes"] = [
        "The tracked SiroinoSotai_PC FBX is the source body.",
        "Official Siroino _Large shape keys are baked before garment fitting.",
        "Skirt radii are resolved from measured waist and hip sections.",
        "Front/back ease is lower than side ease to correct the right-view oversize silhouette.",
        "Skirt shells use nearest official body weights plus continuous hip and upper-leg anchors.",
        "Each generated vertex is reduced to at most four normalized bone influences.",
        "ZOZO Contact Solver is PASS only with both solved mesh and penetration report.",
        "Material Maker is PASS only with an editable .ptex source.",
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
            "designRevision": "v6-large-body-measured-pattern-fit",
            "shapeProfile": profile,
            "patternPipeline": LAST_PATTERN_AUDIT,
            "skirtWeightTransfer": skirt_audit,
        }
    )
    manifest["handoff"]["lastAttempt"] = {
        "result": (
            "HOSTED_MODELED"
            if return_code == 0 and report.get("passed")
            else "REJECTED"
        ),
        "visualRevision": "v6-large-body-measured-pattern-fit",
        "shapeProfile": profile["profile"],
    }
    gates = manifest["technicalGates"]
    gates["shapeProfileApplied"] = (
        "PASS" if profile.get("appliedShapeKeys") else "FAIL"
    )
    gates["patternContract"] = "PASS"
    gates["skirtWeightTransfer"] = (
        "PASS" if len(skirt_audit) == len(SKIRT_OBJECTS) else "FAIL"
    )
    gates["zozoContactSolver"] = (
        "PASS"
        if LAST_PATTERN_AUDIT["solverMeshPresent"]
        and LAST_PATTERN_AUDIT["solverReportPresent"]
        else "PENDING"
    )
    gates["materialMakerSource"] = (
        "PASS" if LAST_PATTERN_AUDIT["materialMakerSourcePresent"] else "PENDING"
    )
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
