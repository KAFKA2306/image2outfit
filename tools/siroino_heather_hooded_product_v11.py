#!/usr/bin/env python3
"""V11 product entrypoint for the Siroino heather hooded bodysuit."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_heather_hooded_v11_support as support

support.install()

import siroino_heather_hooded_pattern_v10 as pattern
import siroino_heather_hooded_product as product

DESIGN_REVISION = "v11-unified-source-topology-fit"
ACTUAL_SEPARATE_GEOMETRY = [
    "Heather_Front_Body_Panel",
    "Heather_Back_Body_Panel",
    "Heather_Long_Sleeve_L",
    "Heather_Long_Sleeve_R",
    "Heather_Rib_Cuff_L",
    "Heather_Rib_Cuff_R",
    "Heather_Hood_Outer_L",
    "Heather_Hood_Outer_R",
    "Heather_Hood_Neck_Band",
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


def preserve_authored_weights(
    garments: list[bpy.types.Object],
    _body: bpy.types.Object,
) -> dict[str, object]:
    return {
        "objects": [obj.name for obj in garments if obj.type == "MESH"],
        "weightSource": (
            "direct SiroinoSotai_PC source topology, UVs and normalized source "
            "skin weights for body panels, sleeves and cuffs; nearest-body or "
            "rigid weights only for authored hood and trim geometry"
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
            failures = [
                {
                    "revision": "v7.1-continuous-shell-fit",
                    "reason": (
                        "actual five-view inspection found sawtooth panel edges, "
                        "elbow/cuff holes, an over-wide neckline, a shield-like rear "
                        "hood and heather moire; evaluated BVH audit reported 6660 "
                        "garment/body triangle overlap pairs across six poses"
                    ),
                },
                {
                    "revision": "v8-smooth-sampled-panels-distance-field-sleeves",
                    "reason": (
                        "actual five-view inspection found discontinuous sampled-panel "
                        "spikes, oversized rectangular cuffs and an inflated spherical "
                        "hood; evaluated BVH audit reported 7133 garment/body triangle "
                        "overlap pairs across six poses"
                    ),
                },
                {
                    "revision": "v9-continuous-interpolation-fitted-cuffs",
                    "reason": (
                        "actual hosted five-view inspection found detached plate-like "
                        "torso panels, large shoulder and underarm gaps, rigid waist "
                        "fins, a broken crotch strip and a floating hood"
                    ),
                },
                {
                    "revision": "v10-body-topology-continuous-panels",
                    "reason": (
                        "actual hosted artifact inspection found the torso improved but "
                        "sleeves and cuffs remained detached, the hood floated behind "
                        "the back, high-cut edges were jagged, and the evaluated six-pose "
                        "BVH audit reported 8490 garment/body triangle overlap pairs"
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
        "Heather_Front_Upper_Panel": "Heather_Front_Body_Panel",
        "Heather_Back_Upper_Panel": "Heather_Back_Body_Panel",
        "Heather_Highcut_Front_Panel": "Heather_Front_Body_Panel",
        "Heather_Highcut_Back_Panel": "Heather_Back_Body_Panel",
        "Heather_Hood_Back_Drape_L": "Heather_Hood_Outer_L",
        "Heather_Hood_Back_Drape_R": "Heather_Hood_Outer_R",
        "Heather_Hood_Cowl": "Heather_Hood_Neck_Band",
    }
    for panel in product.build.evidence.PANELS:
        panel["object"] = replacements.get(panel["object"], panel["object"])


def main() -> int:
    product.pattern = pattern
    product.DESIGN_REVISION = DESIGN_REVISION
    product.preserve_authored_weights = preserve_authored_weights
    product.update_panel_object_contract = update_panel_object_contract
    product.enforce_manifest_contract = enforce_manifest_contract
    product.build.evidence.write_pattern_and_research = wrap_pattern_writer(
        product.build.evidence.write_pattern_and_research
    )
    return product.main()


if __name__ == "__main__":
    raise SystemExit(main())
