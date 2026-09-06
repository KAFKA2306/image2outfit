#!/usr/bin/env python3
"""Generate and verify Tuxedo color/size variants without overwriting the base."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "siroino-tuxedo-halter-dress-large"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    parser.add_argument("--blender", required=True)
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT)).replace("\\", "/")


def run_command(command: list[str], *, label: str) -> tuple[float, str]:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        raise RuntimeError(
            f"{label} failed with exit code {completed.returncode}\n"
            + completed.stdout[-3000:]
            + completed.stderr[-3000:]
        )
    return elapsed, completed.stdout


def variant_output_root(workspace: str, variant_id: str) -> Path:
    return (
        ROOT
        / ".image2outfit"
        / "products"
        / PRODUCT_ID
        / "variants"
        / workspace
        / variant_id
    )


def make_size_job(
    base_job: dict[str, Any],
    *,
    workspace: str,
    variant: dict[str, Any],
) -> Path:
    variant_id = str(variant["id"])
    root = variant_output_root(workspace, variant_id)
    job = copy.deepcopy(base_job)
    job["variantId"] = variant_id
    job["buildRevision"] = f"{base_job['buildRevision']}+{variant_id}"
    job["productRoot"] = relative(root)
    job["productManifestPath"] = relative(root / "ProductManifest.json")
    job["blendPath"] = relative(
        root / "Source" / "Blender" / "SiroinoTuxedoHalterDressLarge.blend"
    )
    job["fbxAssetPath"] = relative(
        root / "Models" / "SiroinoTuxedoHalterDressLarge.fbx"
    )
    job["prefabAssetPath"] = relative(
        root / "Prefab" / "SiroinoTuxedoHalterDressLarge.prefab"
    )
    job["integratedPrefabAssetPath"] = relative(
        root / "Prefab" / "Siroino_Large_TuxedoHalterDress.prefab"
    )
    geometry = dict(job.get("geometryVariables", {}))
    geometry.update(variant["geometryVariables"])
    job["geometryVariables"] = geometry
    job["materialOverrides"] = {"waistcoat": "wine"}
    job["previewPaths"] = {
        name: relative(root / "Previews" / f"{name}.png")
        for name in ("front", "back", "left", "right", "three-quarter")
    }
    job["posePaths"] = {
        name: relative(root / "Previews" / "Poses" / f"{name}.png")
        for name in ("neutral", "arms-up", "arm-cross", "crouch", "sit", "prone")
    }
    job_path = root / "variant-job.json"
    return write_json(job_path, job)


def run_size_variant(
    blender: str,
    base_job: dict[str, Any],
    variant: dict[str, Any],
    *,
    workspace: str,
) -> dict[str, Any]:
    job_path = make_size_job(base_job, workspace=workspace, variant=variant)
    root = job_path.parent
    command = [
        blender,
        "--python-use-system-env",
        "--background",
        "--factory-startup",
        "--python-exit-code",
        "1",
        "--python",
        str(ROOT / "tools" / "siroino_tuxedo_halter_dress_large_build.py"),
        "--",
        "--job",
        str(job_path),
    ]
    elapsed, _ = run_command(
        command,
        label=f"size variant {variant['id']} / {workspace}",
    )
    report_path = root / "Evidence" / "Build" / "product-build-report.json"
    report = read_json(report_path)
    if report.get("passed") is not True:
        raise RuntimeError(f"size variant did not pass: {variant['id']}")
    if not report.get("poseViews") or not report.get("weightNormalization"):
        raise RuntimeError("size variant did not rerun pose/weight verification")
    return {
        "workspace": workspace,
        "variantId": variant["id"],
        "elapsedSeconds": elapsed,
        "reportPath": relative(report_path),
        "report": report,
    }


def run_color_variant(
    blender: str,
    base_job_path: Path,
    base_job: dict[str, Any],
    base_report_path: Path,
    variant: dict[str, Any],
    *,
    workspace: str,
    proof_only: bool,
) -> dict[str, Any]:
    root = variant_output_root(workspace, str(variant["id"]))
    root.mkdir(parents=True, exist_ok=True)
    command = [
        blender,
        "--python-use-system-env",
        "--background",
        str((ROOT / base_job["blendPath"]).resolve()),
        "--python-exit-code",
        "1",
        "--python",
        str(ROOT / "tools" / "tuxedo_color_variant_build.py"),
        "--",
        "--job",
        str(base_job_path),
        "--base-report",
        str(base_report_path),
        "--output-root",
        str(root),
        "--variant-id",
        str(variant["id"]),
        "--waistcoat-material",
        str(variant["materialOverrides"]["waistcoat"]),
    ]
    if proof_only:
        command.append("--proof-only")
    elapsed, _ = run_command(
        command,
        label=f"color variant {variant['id']} / {workspace}",
    )
    report_path = root / "Evidence" / "Build" / "product-build-report.json"
    report = read_json(report_path)
    if report.get("passed") is not True:
        raise RuntimeError(f"color variant did not pass: {variant['id']}")
    return {
        "workspace": workspace,
        "variantId": variant["id"],
        "elapsedSeconds": elapsed,
        "reportPath": relative(report_path),
        "report": report,
    }


def main() -> int:
    args = parse_args()
    job_path = Path(args.job).resolve()
    job = read_json(job_path)
    if job.get("id") != PRODUCT_ID:
        raise ValueError("variant proof product identity mismatch")
    pipeline = job.get("garmentPipeline", {})
    if not isinstance(pipeline, dict):
        raise ValueError("garmentPipeline must be an object")
    variant_path = (ROOT / str(pipeline["variantSpecPath"])).resolve()
    variant_spec = read_json(variant_path)
    if variant_spec.get("productId") != PRODUCT_ID:
        raise ValueError("variant spec product identity mismatch")

    base_report_path = (
        ROOT
        / job["productRoot"]
        / "Evidence"
        / "Build"
        / "product-build-report.json"
    ).resolve()
    base_report = read_json(base_report_path)
    base_blend = (ROOT / job["blendPath"]).resolve()
    base_blend_sha = sha256(base_blend)
    base_geometry = str(base_report["geometrySha256"])
    base_bib_width = float(
        base_report["patternDrivenGeometry"]["pieces"]["bib-front"]["bounds"]["width"]
    )

    variants = variant_spec.get("variants")
    if not isinstance(variants, list):
        raise ValueError("variant spec variants must be a list")
    color = next(item for item in variants if item.get("kind") == "color")
    size = next(item for item in variants if item.get("kind") == "size")

    color_a = run_color_variant(
        args.blender,
        job_path,
        job,
        base_report_path,
        color,
        workspace="workspace-a",
        proof_only=False,
    )
    size_a = run_size_variant(
        args.blender,
        job,
        size,
        workspace="workspace-a",
    )
    color_b = run_color_variant(
        args.blender,
        job_path,
        job,
        base_report_path,
        color,
        workspace="workspace-b",
        proof_only=True,
    )
    size_b = run_size_variant(
        args.blender,
        job,
        size,
        workspace="workspace-b",
    )

    color_geometry_a = str(color_a["report"]["geometrySha256"])
    color_geometry_b = str(color_b["report"]["geometrySha256"])
    if color_geometry_a != base_geometry or color_geometry_b != base_geometry:
        raise RuntimeError("color variant did not reuse base geometry")

    size_geometry = str(size_a["report"]["geometrySha256"])
    if size_geometry == base_geometry:
        raise RuntimeError("size variant did not change geometry")
    size_bib_width = float(
        size_a["report"]["patternDrivenGeometry"]["pieces"]["bib-front"]["bounds"][
            "width"
        ]
    )
    ratio = size_bib_width / base_bib_width
    if abs(ratio - 1.1) > 1e-6:
        raise RuntimeError(f"size projection ratio is not 1.1: {ratio}")

    second_size_width = float(
        size_b["report"]["patternDrivenGeometry"]["pieces"]["bib-front"]["bounds"][
            "width"
        ]
    )
    if abs(second_size_width - size_bib_width) > 1e-9:
        raise RuntimeError("separate size workspace produced a different projection")

    negative_root = variant_output_root("negative", "invalid-color")
    negative_root.mkdir(parents=True, exist_ok=True)
    negative_command = [
        args.blender,
        "--python-use-system-env",
        "--background",
        str(base_blend),
        "--python-exit-code",
        "1",
        "--python",
        str(ROOT / "tools" / "tuxedo_color_variant_build.py"),
        "--",
        "--job",
        str(job_path),
        "--base-report",
        str(base_report_path),
        "--output-root",
        str(negative_root),
        "--variant-id",
        "invalid-color",
        "--waistcoat-material",
        "not-a-tracked-preset",
        "--proof-only",
    ]
    negative = subprocess.run(
        negative_command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if negative.returncode == 0:
        raise RuntimeError("intentional invalid color variant unexpectedly passed")
    if sha256(base_blend) != base_blend_sha:
        raise RuntimeError("failed derivative modified the canonical base blend")

    proof = {
        "schemaVersion": 1,
        "productId": PRODUCT_ID,
        "status": "PASS",
        "recipeVersion": variant_spec["recipeVersion"],
        "baseVariant": variant_spec["baseVariant"],
        "base": {
            "geometrySha256": base_geometry,
            "blendSha256BeforeFailure": base_blend_sha,
            "bibWidthM": base_bib_width,
        },
        "production": {
            "successfulCandidates": 3,
            "attemptedCandidates": 3,
            "retryCount": 0,
            "color": {
                "variantId": color["id"],
                "geometrySha256": color_geometry_a,
                "geometryReused": True,
                "elapsedSeconds": color_a["elapsedSeconds"],
                "reportPath": color_a["reportPath"],
            },
            "size": {
                "variantId": size["id"],
                "geometrySha256": size_geometry,
                "geometryChanged": True,
                "bibWidthM": size_bib_width,
                "bibWidthRatio": ratio,
                "fitWeightsPosesRerun": True,
                "elapsedSeconds": size_a["elapsedSeconds"],
                "reportPath": size_a["reportPath"],
            },
        },
        "reproducibility": {
            "workspaceA": {
                "colorReport": color_a["reportPath"],
                "sizeReport": size_a["reportPath"],
            },
            "workspaceB": {
                "colorReport": color_b["reportPath"],
                "sizeReport": size_b["reportPath"],
            },
            "colorGeometryMatches": color_geometry_b == color_geometry_a,
            "sizeProjectionMatches": abs(second_size_width - size_bib_width) <= 1e-9,
        },
        "negativeIsolation": {
            "variantId": "invalid-color",
            "expectedFailureObserved": True,
            "returnCode": negative.returncode,
            "baseBlendSha256AfterFailure": sha256(base_blend),
            "basePreserved": sha256(base_blend) == base_blend_sha,
        },
    }
    proof_path = write_json(
        ROOT
        / ".image2outfit"
        / "products"
        / PRODUCT_ID
        / "variants"
        / "variant-proof.json",
        proof,
    )
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    print(f"variant proof: {relative(proof_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
