#!/usr/bin/env python3
"""Cyber Kawaii build using the standard Siroino FBX plus official size shape keys."""
from __future__ import annotations

import json
from typing import Any

import siroino_cyber_kawaii_standard_build as standard

ORIGINAL_CONTACT_SHEET = standard.legacy.g.contact_sheet
ORIGINAL_APPLY_LARGE_PROFILE = standard.legacy.g.apply_large_profile
ORIGINAL_REWRITE_HANDOFF = standard.rewrite_handoff
LAST_TARGET_PROFILE: dict[str, Any] = {}


def contact_sheet(images, output, *, order, title):
    if title == "CYBER KAWAII LAYERED SET / SIROINO _LARGE":
        title = "CYBER KAWAII LAYERED SET / SIROINO _LARGE (SHAPE PROFILE)"
    return ORIGINAL_CONTACT_SHEET(images, output, order=order, title=title)


def apply_configured_shape_profile(body, requested=None) -> dict[str, object]:
    """Bake configured official Siroino shape keys before garment extraction.

    The tracked source remains the standard SiroinoSotai_PC FBX. When the job
    defines a bodyShapeProfile, every required key is applied through the
    shared strict profile baker. A configured profile is never silently
    replaced by the neutral body.
    """
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


def rewrite_shape_profile_handoff(job: dict, return_code: int) -> None:
    """Preserve the actual applied profile in reports and resumable metadata."""
    ORIGINAL_REWRITE_HANDOFF(job, return_code)
    profile = dict(LAST_TARGET_PROFILE)
    if not profile:
        raise RuntimeError("Cyber Kawaii build completed without target shape-profile evidence")

    report_path = standard.repo_path(job["artifactDir"]) / "product-build-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["targetProfile"] = profile
    report["visualRevision"] = "v4-large-shape-profile"
    report["notes"] = [
        "The tracked SiroinoSotai_PC FBX is the source body.",
        "Official Siroino _Large shape keys are baked before garment extraction and fitting.",
        "The build fails instead of silently using the neutral body when configured keys are unavailable.",
        "Five-view and pose images are actual Blender renders of the shape-profiled generated scene.",
    ]
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest_path = standard.repo_path(job["productManifestPath"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["productName"] = job["productName"]
    manifest["targetAdapterId"] = job["adapterId"]
    manifest["target"] = profile["profile"]
    manifest["designRevision"] = "v4-large-shape-profile"
    manifest["shapeProfile"] = profile
    manifest["handoff"]["lastAttempt"] = {
        "result": "HOSTED_MODELED" if return_code == 0 and report.get("passed") else "REJECTED",
        "visualRevision": "v4-large-shape-profile",
        "shapeProfile": profile["profile"],
    }
    manifest["technicalGates"]["shapeProfileApplied"] = (
        "PASS" if profile.get("appliedShapeKeys") else "FAIL"
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    applied = ", ".join(
        f"{name}={value:g}" for name, value in profile.get("appliedShapeKeys", {}).items()
    )
    product_root = standard.repo_path(job["productRoot"])
    (product_root / "README.md").write_text(
        f"""# {job['productName']}

Target: **Siroino `_Large` via official shape keys** baked from the tracked standard `SiroinoSotai_PC` FBX before garment extraction.

Applied profile: `{applied}`

## Visual revision v4

- shape-profiled body used for all surface extraction and clearance measurements
- closed, non-degenerate plaid skirt shell weighted to the pelvis
- body-weighted shoulder and forearm sleeves for pose stability
- ankle-safe thigh-high stockings that do not cover the feet
- fitted black waistband and pink underskirt hem
- compact chest bow without free-floating waist/thigh ornaments

## Outputs

- Blender source: `{job['blendPath']}`
- FBX: `{job['fbxAssetPath']}`
- outfit Prefab: `{job['prefabAssetPath']}`
- integrated Prefab: `{job['integratedPrefabAssetPath']}`
- five-view render: `{job['productRoot']}/Previews/{job['id']}-multiview.webp`
- pose review: `{job['productRoot']}/Previews/{job['id']}-pose-review.webp`

Unity import, Prefab reload, Modular Avatar/NDMF, VRChat Build & Test, and runtime review remain explicit gates.
""",
        encoding="utf-8",
    )
    standard.refresh_hashes(product_root)


def main() -> int:
    standard.legacy.g.contact_sheet = contact_sheet
    standard.apply_standard_profile = apply_configured_shape_profile
    standard.rewrite_handoff = rewrite_shape_profile_handoff
    return standard.main()


if __name__ == "__main__":
    raise SystemExit(main())
