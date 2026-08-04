#!/usr/bin/env python3
"""Stable product entrypoint for the Siroino heather hooded bodysuit."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_heather_hooded_bodysuit_build as build
import siroino_heather_hooded_v11_support as support

support.install()

import siroino_heather_cross_section_cage_v25 as cross_section_cage
import siroino_heather_hooded_pattern_v13 as pattern

cross_section_cage.install(pattern)

DESIGN_REVISION = pattern.DESIGN_REVISION
CROSS_SECTION_TRIAL = (
    "Assets/GenWorks/siroino-heather-hooded-bodysuit/Research/"
    "cross-sectional-cage-trial.json"
)
ACTUAL_SEPARATE_GEOMETRY = [
    "Heather_Body_Shell",
    "Heather_Long_Sleeve_L",
    "Heather_Long_Sleeve_R",
    "Heather_Rib_Cuff_L",
    "Heather_Rib_Cuff_R",
    "Heather_Hood_Folded_Roll",
    "Heather_Henley_Placket",
    "Heather_Henley_Button_01",
    "Heather_Henley_Button_02",
    "Heather_Henley_Button_03",
    "Heather_Hood_Drawcord_L",
    "Heather_Hood_Drawcord_R",
]

REJECTED_REVISIONS = [
    {
        "revision": "v22-dama-inspired-body-anchored-shell",
        "reason": (
            "positive body-normal clearance did not repair incorrect garment region "
            "selection, long crotch tabs, jagged boundaries or pose deformation"
        ),
    },
    {
        "revision": "v23-dama-anchor-lobomap-residual-fit",
        "reason": (
            "the local residual RMS improved from 3.548 to 2.975 mm, but direct "
            "five-view and pose inspection still found floating hood parts, dark "
            "surface defects, a pointed crotch flap and collapsed crouch/sit/prone "
            "silhouettes"
        ),
    },
    {
        "revision": "v24-structured-template-cage",
        "reason": (
            "the primary shell no longer copied body topology, but its binary "
            "front/back surface parameterization folded repeated x,z samples onto "
            "the same body points, producing a collapsed front, large back openings, "
            "a Y-shaped crotch flap and detached shoulder/cowl silhouettes"
        ),
    },
]


def normalize_four_influences(
    objects: list[bpy.types.Object],
    maximum: int = 4,
) -> dict[str, int]:
    """Normalize every vertex, pruning to the VRChat four-influence limit."""
    changed: dict[str, int] = {}
    for obj in objects:
        if obj.type != "MESH":
            continue
        fallback = obj.vertex_groups.get("Hips")
        if fallback is None:
            fallback = obj.vertex_groups.new(name="Hips")
        affected = 0
        for vertex in obj.data.vertices:
            assignments = [
                (obj.vertex_groups[item.group].name, float(item.weight))
                for item in list(vertex.groups)
                if item.weight > 1e-10
            ]
            ranked = sorted(
                assignments,
                key=lambda item: item[1],
                reverse=True,
            )[:maximum]
            if not ranked:
                ranked = [(fallback.name, 1.0)]
            total = sum(weight for _, weight in ranked)
            if total <= 1e-12:
                ranked = [(fallback.name, 1.0)]
                total = 1.0
            requires_change = (
                len(assignments) != len(ranked)
                or abs(sum(weight for _, weight in assignments) - 1.0) > 1e-6
            )
            for group_name, _ in assignments:
                obj.vertex_groups[group_name].remove([vertex.index])
            for group_name, weight in ranked:
                obj.vertex_groups[group_name].add(
                    [vertex.index],
                    weight / total,
                    "REPLACE",
                )
            if requires_change:
                affected += 1
        changed[obj.name] = affected
    return changed


def preserve_authored_weights(
    garments: list[bpy.types.Object],
    _body: bpy.types.Object,
) -> dict[str, object]:
    """Preserve cage weights transferred during component construction."""
    return {
        "objects": [obj.name for obj in garments if obj.type == "MESH"],
        "weightSource": (
            "garment topology is reconstructed from smoothed avatar cross-section "
            "statistics rather than avatar faces; SiroinoSotai_PC is used as a "
            "statistical shape and nearest-body skin-weight reference; four normalized "
            "influences are enforced after construction"
        ),
        "bodyTopologyCopied": False,
        "binaryFrontBackSamplingUsedForPrimarySurface": False,
        "rebound": False,
    }


def wrap_pattern_writer(original):
    def wrapped(*args, **kwargs):
        pattern_path, research_path = original(*args, **kwargs)
        contract = json.loads(pattern_path.read_text(encoding="utf-8"))
        contract["separateGeometry"] = ACTUAL_SEPARATE_GEOMETRY
        contract["designRevision"] = DESIGN_REVISION
        contract["representation"] = {
            "canonical": "cross-sectional statistical cage",
            "bodyTopologyCopied": False,
            "binaryFrontBackSamplingUsedForPrimarySurface": False,
            "components": [
                "smoothed height-indexed torso ellipse cage",
                "shared-edge U-shaped gusset",
                "left and right arm tubes",
                "left and right cuffs",
                "analytic attached cowl",
            ],
            "bodyRole": "cross-section statistics and skin-weight reference",
        }
        contract["researchTrialEvidence"] = CROSS_SECTION_TRIAL
        pattern_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return pattern_path, research_path

    return wrapped


def enforce_manifest_contract(original):
    """Keep generated reports truthful about the current lifecycle boundary."""

    def wrapped(*args, **kwargs):
        result = original(*args, **kwargs)
        job = args[0]
        root = Path(__file__).resolve().parents[1]
        trial_path = root / CROSS_SECTION_TRIAL
        trial = (
            json.loads(trial_path.read_text(encoding="utf-8"))
            if trial_path.is_file()
            else {"result": "FAIL", "status": "MISSING"}
        )

        manifest_path = root / job["productManifestPath"]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["schemaVersion"] = 1
        manifest["designRevision"] = DESIGN_REVISION
        manifest["status"] = "WORKING"
        manifest["technicalGates"]["researchTrial"] = trial.get("result", "FAIL")
        manifest["technicalGates"]["visualAppearanceReview"] = "PENDING"
        manifest["technicalGates"]["fitPenetration"] = "NON_BLOCKING_PENDING"
        for key in (
            "unityImport",
            "unitySaveReload",
            "prefabReload",
            "modularAvatar",
            "ndmf",
            "vrchatBuildTest",
            "vrchatRuntime",
            "humanRuntimeReview",
        ):
            manifest["technicalGates"][key] = "OUT_OF_SCOPE"
        manifest["outputs"]["researchTrial"] = CROSS_SECTION_TRIAL
        manifest["research"] = {
            "result": trial.get("result", "FAIL"),
            "evidence": CROSS_SECTION_TRIAL,
            "representation": "cross-sectional statistical cage",
            "authorsImplementationExecuted": False,
            "authorsCodeCopied": False,
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        report_path = (
            root
            / ".image2outfit"
            / "products"
            / job["id"]
            / "reports"
            / "product-build-report.json"
        )
        if report_path.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["designRevision"] = DESIGN_REVISION
            report["researchTrial"] = manifest["research"]
            rejected = report.setdefault("rejectedHistory", [])
            existing = {item.get("revision") for item in rejected}
            rejected.extend(
                item for item in REJECTED_REVISIONS if item["revision"] not in existing
            )
            report["notes"] = [
                "Body-face selection, DAMA anchoring, LoBoMap residual smoothing and "
                "binary front/back circumferential sampling are not in the active path.",
                "The primary topology is reconstructed from robust avatar vertex "
                "cross-section quantiles and smoothed across height.",
                "The lower torso boundary is analytic and is split into two leg "
                "openings by a shared-edge U-shaped gusset.",
                "Sleeves and cuffs are smaller regular tubes along arm bone centerlines, "
                "with an inward shoulder extension for controlled torso overlap.",
                "The cowl is analytic and attached; it does not use the failed body "
                "front/back surface sampler.",
                "Required five-view and pose renders plus direct visual review remain "
                "completion gates; Unity and VRChat runtime validation are OUT_OF_SCOPE.",
            ]
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return result

    return wrapped


def update_panel_object_contract() -> None:
    replacements = {
        "Heather_Front_Upper_Panel": "Heather_Body_Shell",
        "Heather_Back_Upper_Panel": "Heather_Body_Shell",
        "Heather_Highcut_Front_Panel": "Heather_Body_Shell",
        "Heather_Highcut_Back_Panel": "Heather_Body_Shell",
        "Heather_Long_Sleeve_L": "Heather_Long_Sleeve_L",
        "Heather_Long_Sleeve_R": "Heather_Long_Sleeve_R",
        "Heather_Rib_Cuff_L": "Heather_Rib_Cuff_L",
        "Heather_Rib_Cuff_R": "Heather_Rib_Cuff_R",
        "Heather_Hood_Back_Drape_L": "Heather_Hood_Folded_Roll",
        "Heather_Hood_Back_Drape_R": "Heather_Hood_Folded_Roll",
        "Heather_Hood_Outer_L": "Heather_Hood_Folded_Roll",
        "Heather_Hood_Outer_R": "Heather_Hood_Folded_Roll",
        "Heather_Hood_Cowl": "Heather_Hood_Folded_Roll",
    }
    for panel in build.evidence.PANELS:
        panel["object"] = replacements.get(panel["object"], panel["object"])


def main() -> int:
    build.geometry = pattern
    build.DESIGN_REVISION = DESIGN_REVISION
    build.limit_bone_influences = normalize_four_influences
    build.rebind_dynamic_parts = preserve_authored_weights
    update_panel_object_contract()
    build.evidence.write_pattern_and_research = wrap_pattern_writer(
        build.evidence.write_pattern_and_research
    )
    build.write_report_and_manifest = enforce_manifest_contract(
        build.write_report_and_manifest
    )
    return build.main()


if __name__ == "__main__":
    raise SystemExit(main())
