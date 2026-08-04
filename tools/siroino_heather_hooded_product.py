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

import siroino_heather_hooded_pattern_v13 as pattern

DESIGN_REVISION = pattern.DESIGN_REVISION
ACTUAL_SEPARATE_GEOMETRY = [
    "Heather_Body_Shell",
    "Heather_Hood_Down_Cowl",
    "Heather_Henley_Placket",
    "Heather_Henley_Button_01",
    "Heather_Henley_Button_02",
    "Heather_Henley_Button_03",
    "Heather_Hood_Drawcord_L",
    "Heather_Hood_Drawcord_R",
]

REJECTED_REVISIONS = [
    {
        "revision": "v7.1-continuous-shell-fit",
        "reason": (
            "actual five-view inspection found sawtooth panel edges, elbow/cuff "
            "holes, an over-wide neckline, a shield-like rear hood and heather "
            "moire; evaluated BVH audit reported 6660 overlap pairs"
        ),
    },
    {
        "revision": "v8-smooth-sampled-panels-distance-field-sleeves",
        "reason": (
            "actual five-view inspection found sampled-panel spikes, oversized "
            "rectangular cuffs and an inflated hood; evaluated BVH audit reported "
            "7133 overlap pairs"
        ),
    },
    {
        "revision": "v9-continuous-interpolation-fitted-cuffs",
        "reason": (
            "actual hosted inspection found detached torso plates, shoulder and "
            "underarm gaps, waist fins, a broken crotch strip and a floating hood"
        ),
    },
    {
        "revision": "v10-body-topology-continuous-panels",
        "reason": (
            "actual hosted inspection found detached sleeves and cuffs, a floating "
            "hood and jagged high-cut edges; evaluated BVH audit reported 8490 "
            "overlap pairs"
        ),
    },
    {
        "revision": "v11-unified-source-topology-fit",
        "reason": (
            "actual hosted inspection still found shoulder, elbow and cuff "
            "discontinuities, sawtooth edges and a bag-like hood; evaluated BVH "
            "audit reported 12845 overlap pairs"
        ),
    },
    {
        "revision": "v12-continuous-source-shell",
        "reason": (
            "actual hosted inspection found metre-scale bevel miter spikes, chest "
            "and waist collapse, a hanging crotch sheet and hood penetration; "
            "evaluated BVH audit reported 28593 overlap pairs"
        ),
    },
    {
        "revision": "v13-bevel-safe-continuous-shell",
        "reason": (
            "actual hosted inspection removed metre-scale spikes but still found "
            "waist fins, a ruptured high-cut front, back and sleeve holes, detached "
            "hood strips and 2506 neutral-pose triangle overlap pairs"
        ),
    },
    {
        "revision": "v14-source-topology-highcut-shell",
        "reason": (
            "actual hosted inspection found elbow holes, jagged leg openings, "
            "detached oversized cuffs and an umbrella-like hood; every required "
            "pose failed, with 268 neutral and 1418 arms-up overlap pairs"
        ),
    },
    {
        "revision": "v15-refined-topology-folded-hood",
        "reason": (
            "the executable pre-export gate detected three disconnected primary "
            "shell components and nine boundary loops across 572 edges; both sleeves "
            "remained detached at the shoulder and rendering was correctly stopped"
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
    """Preserve refined source weights and nearest-body accessory weights."""
    return {
        "objects": [obj.name for obj in garments if obj.type == "MESH"],
        "weightSource": (
            "one-level subdivided SiroinoSotai_PC topology with interpolated UVs "
            "and normalized source skin weights for the shoulder-bridged connected "
            "body shell; nearest-body weights for the folded hood and trim geometry"
        ),
        "rebound": False,
    }


def wrap_pattern_writer(original):
    def wrapped(*args, **kwargs):
        pattern_path, research_path = original(*args, **kwargs)
        contract = json.loads(pattern_path.read_text(encoding="utf-8"))
        contract["separateGeometry"] = ACTUAL_SEPARATE_GEOMETRY
        contract["designRevision"] = DESIGN_REVISION
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
        manifest_path = root / job["productManifestPath"]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["schemaVersion"] = 1
        manifest["designRevision"] = DESIGN_REVISION
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
            rejected = report.setdefault("rejectedHistory", [])
            existing = {item.get("revision") for item in rejected}
            rejected.extend(
                item for item in REJECTED_REVISIONS if item["revision"] not in existing
            )
            report["notes"] = [
                "The fitted garment is extracted from a one-level subdivided "
                "SiroinoSotai_PC source shell.",
                "The torso and arm capsules overlap through an explicit shoulder "
                "bridge so the high-cut body and both sleeves form one mesh.",
                "The primary shell must have one component and at most five expected "
                "garment opening loops.",
                "The hood is represented as a compact folded cowl behind the neck.",
                "Buttons, Henley placket and drawcords are separate geometry.",
                "All exported vertices are limited to four normalized bone influences.",
                "Five views are actual Blender Cycles renders of generated geometry.",
                "Required pose, Unity and runtime review remain separate gates.",
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
        "Heather_Long_Sleeve_L": "Heather_Body_Shell",
        "Heather_Long_Sleeve_R": "Heather_Body_Shell",
        "Heather_Rib_Cuff_L": "Heather_Body_Shell",
        "Heather_Rib_Cuff_R": "Heather_Body_Shell",
        "Heather_Hood_Back_Drape_L": "Heather_Hood_Down_Cowl",
        "Heather_Hood_Back_Drape_R": "Heather_Hood_Down_Cowl",
        "Heather_Hood_Outer_L": "Heather_Hood_Down_Cowl",
        "Heather_Hood_Outer_R": "Heather_Hood_Down_Cowl",
        "Heather_Hood_Cowl": "Heather_Hood_Down_Cowl",
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
