#!/usr/bin/env python3
"""Stable entrypoint for the v28 fused-roll hooded bodysuit candidate."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_heather_fused_roll_v28 as fused_roll
import siroino_heather_hooded_product as product

fused_roll.install(product.pattern)
product.DESIGN_REVISION = fused_roll.DESIGN_REVISION
product.CLOSED_COMPONENTS_TRIAL = str(fused_roll.RESEARCH_OUTPUT).replace("\\", "/")
product.REJECTED_REVISIONS.append(
    {
        "revision": "v27-closed-saddle-sleevecap-folded-hood",
        "reason": (
            "direct artifact review found a rectangular neckline, bulky folded "
            "sleeve roots, a broad shoulder flap instead of a hood, pointed lower "
            "panels and 15,753 body-overlap pairs across six required poses"
        ),
    }
)

_ORIGINAL_PRESERVE = product.preserve_authored_weights
_ORIGINAL_PATTERN_WRITER = product.wrap_pattern_writer
_ORIGINAL_MANIFEST_WRITER = product.enforce_manifest_contract


def preserve_authored_weights(
    garments: list[bpy.types.Object],
    body: bpy.types.Object,
) -> dict[str, object]:
    result = _ORIGINAL_PRESERVE(garments, body)
    result["weightSource"] = (
        "v27 polar torso statistics and garment-native mesh helpers are retained; "
        "v28 replaces the underbody with a fifteen-column flat saddle, uses a "
        "small-to-large-to-tapered sleeve-cap radius profile and replaces the hood "
        "sheet with a U-shaped rear-neck roll; bounded clearance remains post-topology"
    )
    result["pelvicSaddleColumns"] = 15
    result["visualMechanismRevision"] = fused_roll.DESIGN_REVISION
    return result


def wrap_pattern_writer(original):
    wrapped = _ORIGINAL_PATTERN_WRITER(original)

    def output(*args, **kwargs):
        pattern_path, research_path = wrapped(*args, **kwargs)
        contract = json.loads(pattern_path.read_text(encoding="utf-8"))
        contract["designRevision"] = fused_roll.DESIGN_REVISION
        contract["representation"] = {
            "canonical": "polar torso with flat saddle, contoured sleeve caps and hood roll",
            "bodyTopologyCopied": False,
            "boundedClearanceProjection": True,
            "components": [
                "smoothed height-by-angle torso field",
                "short continuous shoulder yoke and neck ring",
                "fifteen-column flat pelvic saddle",
                "contoured small-root shoulder-cap sleeve tubes",
                "left and right fitted cuffs",
                "U-shaped folded hood roll around rear neck",
            ],
            "bodyRole": "polar statistics, bounded clearance and skin-weight reference",
        }
        contract["researchTrialEvidence"] = product.CLOSED_COMPONENTS_TRIAL
        pattern_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return pattern_path, research_path

    return output


def enforce_manifest_contract(original):
    wrapped = _ORIGINAL_MANIFEST_WRITER(original)

    def output(*args, **kwargs):
        result = wrapped(*args, **kwargs)
        job = args[0]
        root = Path(__file__).resolve().parents[1]
        trial_path = root / product.CLOSED_COMPONENTS_TRIAL
        trial = json.loads(trial_path.read_text(encoding="utf-8"))
        manifest_path = root / job["productManifestPath"]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["designRevision"] = fused_roll.DESIGN_REVISION
        manifest["status"] = "WORKING"
        manifest["technicalGates"]["researchTrial"] = trial["result"]
        manifest["technicalGates"]["visualAppearanceReview"] = "PENDING"
        manifest["outputs"]["researchTrial"] = product.CLOSED_COMPONENTS_TRIAL
        manifest["research"] = {
            "result": trial["result"],
            "evidence": product.CLOSED_COMPONENTS_TRIAL,
            "representation": (
                "polar torso with flat saddle, contoured sleeve caps and hood roll"
            ),
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
            report["designRevision"] = fused_roll.DESIGN_REVISION
            report["researchTrial"] = manifest["research"]
            report["notes"] = [
                "The validated v27 polar profile and clearance helpers are reused.",
                "The lower front/back boundary is flattened and widened before a "
                "fifteen-column saddle is bridged with only 12 mm central sag.",
                "Torso subdivision is disabled to prevent open-boundary wing curl.",
                "Sleeves start with a small inner ring, expand at the shoulder and "
                "then taper down the arm instead of using a bulky constant cap.",
                "The rejected sheet hood is replaced by a U-shaped rear-neck roll.",
                "Pose cameras are widened independently so every required image "
                "contains the full review subject.",
                "Visual review remains a blocking gate; runtime systems are OUT_OF_SCOPE.",
            ]
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return result

    return output


product.preserve_authored_weights = preserve_authored_weights
product.wrap_pattern_writer = wrap_pattern_writer
product.enforce_manifest_contract = enforce_manifest_contract


def main() -> int:
    return product.main()


if __name__ == "__main__":
    raise SystemExit(main())
