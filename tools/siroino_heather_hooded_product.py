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
import siroino_heather_hooded_pattern as pattern

DESIGN_REVISION = "v9-continuous-interpolation-fitted-cuffs"
ACTUAL_SEPARATE_GEOMETRY = [
    "Heather_Henley_Placket",
    "Heather_Henley_Button_01",
    "Heather_Henley_Button_02",
    "Heather_Henley_Button_03",
    "Heather_Hood_Drawcord_L",
    "Heather_Hood_Drawcord_R",
    "Heather_Side_Tie_L",
    "Heather_Side_Tie_R",
    "Heather_Center_Front_Seam",
    "Heather_Center_Back_Seam",
    "Heather_Hood_Center_Seam",
]


def normalize_four_influences(
    objects: list[bpy.types.Object],
    maximum: int = 4,
) -> dict[str, int]:
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
    return {
        "objects": [obj.name for obj in garments if obj.type == "MESH"],
        "weightSource": (
            "nearest tracked SiroinoSotai_PC weights for continuous sampled panels and accessories; "
            "direct source-vertex weights for fitted sleeves; explicit lower-arm/hand weights for cuffs"
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
            root / ".image2outfit" / "products" / job["id"] / "reports" / "product-build-report.json"
        )
        if report_path.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["designRevision"] = DESIGN_REVISION
            rejected = report.setdefault("rejectedHistory", [])
            failures = [
                {
                    "revision": "v7.1-continuous-shell-fit",
                    "reason": (
                        "actual five-view inspection found sawtooth panel edges, elbow/cuff holes, "
                        "an over-wide neckline, a shield-like rear hood and heather moire; evaluated "
                        "BVH audit reported 6660 garment/body triangle overlap pairs across six poses"
                    ),
                },
                {
                    "revision": "v8-smooth-sampled-panels-distance-field-sleeves",
                    "reason": (
                        "actual five-view inspection found discontinuous sampled-panel spikes, oversized "
                        "rectangular cuffs and an inflated spherical hood; evaluated BVH audit reported "
                        "7133 garment/body triangle overlap pairs across six poses"
                    ),
                },
            ]
            existing = {item.get("revision") for item in rejected}
            rejected.extend(item for item in failures if item["revision"] not in existing)
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return result

    return wrapped


def update_panel_object_contract() -> None:
    replacements = {
        "Heather_Hood_Back_Drape_L": "Heather_Hood_Outer_L",
        "Heather_Hood_Back_Drape_R": "Heather_Hood_Outer_R",
        "Heather_Hood_Cowl": "Heather_Hood_Neck_Band",
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
