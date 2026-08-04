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

import siroino_heather_closed_components_v27 as closed_components
import siroino_heather_hooded_pattern_v13 as pattern

closed_components.install(pattern)

DESIGN_REVISION = pattern.DESIGN_REVISION
CLOSED_COMPONENTS_TRIAL = (
    "Assets/GenWorks/siroino-heather-hooded-bodysuit/Research/"
    "closed-components-clearance-trial.json"
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
    {
        "revision": "v25-cross-sectional-statistical-cage",
        "reason": (
            "the smoothed ellipse cage removed the v24 folding, but direct artifact "
            "review still found exposed upper-back regions, detached inflated sleeve "
            "roots, a non-hood transverse cowl band and long pointed crotch panels; "
            "all six required poses intersected for 15,897 total overlap pairs"
        ),
    },
    {
        "revision": "v26-angular-polar-yoke-hood",
        "reason": (
            "the angular body field stabilized the torso and reduced total overlaps to "
            "14,192, but direct artifact review still found upper-back body holes, open "
            "sleeve roots, an oversized dome hood and pointed two-column crotch flaps"
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
            ranked = sorted(assignments, key=lambda item: item[1], reverse=True)[:maximum]
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
                    [vertex.index], weight / total, "REPLACE"
                )
            if requires_change:
                affected += 1
        changed[obj.name] = affected
    return changed


def preserve_authored_weights(
    garments: list[bpy.types.Object],
    _body: bpy.types.Object,
) -> dict[str, object]:
    """Preserve garment-native weights transferred during construction."""
    return {
        "objects": [obj.name for obj in garments if obj.type == "MESH"],
        "weightSource": (
            "the torso envelope is reconstructed from smoothed height-by-angle body "
            "statistics; the yoke, eleven-column pelvic saddle, overlapping sleeve "
            "caps, cuffs and folded-back hood are garment-native components; bounded "
            "body-clearance projection is applied only after topology construction; "
            "four normalized influences are enforced after construction"
        ),
        "bodyTopologyCopied": False,
        "boundedClearanceProjection": True,
        "pelvicSaddleColumns": 11,
        "rebound": False,
    }


def wrap_pattern_writer(original):
    def wrapped(*args, **kwargs):
        pattern_path, research_path = original(*args, **kwargs)
        contract = json.loads(pattern_path.read_text(encoding="utf-8"))
        contract["separateGeometry"] = ACTUAL_SEPARATE_GEOMETRY
        contract["designRevision"] = DESIGN_REVISION
        contract["representation"] = {
            "canonical": "polar torso with closed garment-native components",
            "bodyTopologyCopied": False,
            "boundedClearanceProjection": True,
            "components": [
                "smoothed height-by-angle torso field",
                "continuous shoulder yoke and neck ring",
                "eleven-column pelvic saddle",
                "overlapping left and right sleeve caps and tubes",
                "left and right cuffs",
                "low folded-back hood shell",
            ],
            "bodyRole": "polar statistics, bounded clearance and skin-weight reference",
        }
        contract["researchTrialEvidence"] = CLOSED_COMPONENTS_TRIAL
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
        trial_path = root / CLOSED_COMPONENTS_TRIAL
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
        manifest["outputs"]["researchTrial"] = CLOSED_COMPONENTS_TRIAL
        manifest["research"] = {
            "result": trial.get("result", "FAIL"),
            "evidence": CLOSED_COMPONENTS_TRIAL,
            "representation": "polar torso with closed garment-native components",
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
                "The stable angular torso field is retained, but all v26 blocking "
                "component mechanisms are replaced.",
                "The underbody is an eleven-column surface saddle rather than a single "
                "two-vertex-wide strip.",
                "Sleeve caps start farther beneath the yoke and use enlarged root rings "
                "that overlap the shoulder shell.",
                "The hood is a low folded-back rear-neck shell instead of a head-sized "
                "dome.",
                "A bounded nearest-body clearance projection is applied only after "
                "garment-native topology exists, so it cannot redefine garment regions.",
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
