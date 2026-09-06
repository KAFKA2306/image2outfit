#!/usr/bin/env python3
"""Build and verify a small production-variant batch with the canonical product builder."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from image2outfit.variant_production import materialize_all_variants

BASE_PRODUCT_ID = "siroino-tuxedo-halter-dress-large"
BASE_JOB = ROOT / "config" / "products" / BASE_PRODUCT_ID / "job.json"
BASE_REQUEST = ROOT / "config" / "pipeline" / "requests" / f"{BASE_PRODUCT_ID}.json"
BASE_MATERIAL = ROOT / "config" / "products" / BASE_PRODUCT_ID / "material-recipe.json"
DEFAULT_RECIPE = (
    ROOT / "config" / "products" / BASE_PRODUCT_ID / "production-variants.json"
)


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def blender_executable() -> str:
    configured = os.environ.get("IMAGE2OUTFIT_BLENDER", "").strip()
    for candidate in (
        configured,
        str(ROOT / ".image2outfit" / "blender" / "blender"),
        shutil.which("blender") or "",
    ):
        if candidate and Path(candidate).is_file():
            return candidate
    raise FileNotFoundError("Blender executable was not found")


def build_candidate(item: dict[str, Any], *, blender: str) -> dict[str, Any]:
    job = read_object(item["jobPath"])
    expected = item["variantContract"]["expectedResult"]
    log_path = item["contractPath"].parent / "blender.log"
    command = [
        blender,
        "--python-use-system-env",
        "--background",
        "--factory-startup",
        "--python-exit-code",
        "1",
        "--python",
        str(ROOT / job["buildScript"]),
        "--",
        "--job",
        str(item["jobPath"]),
    ]
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    elapsed = time.monotonic() - started
    log_path.write_text(
        completed.stdout + "\n--- STDERR ---\n" + completed.stderr,
        encoding="utf-8",
    )

    product_root = ROOT / job["productRoot"]
    report_path = product_root / "Evidence" / "Build" / "product-build-report.json"
    result: dict[str, Any] = {
        "candidateId": item["candidateId"],
        "variantId": item["variantId"],
        "workspaceId": item["workspaceId"],
        "expectedResult": expected,
        "returnCode": completed.returncode,
        "elapsedSeconds": round(elapsed, 3),
        "attempts": 1,
        "logPath": log_path.relative_to(ROOT).as_posix(),
        "productRoot": job["productRoot"],
        "reportPath": (
            report_path.relative_to(ROOT).as_posix()
            if report_path.is_file()
            else None
        ),
    }

    if expected == "FAIL":
        if completed.returncode == 0:
            raise RuntimeError(
                f"negative-control variant unexpectedly succeeded: {item['variantId']}"
            )
        result["status"] = "EXPECTED_FAIL"
        result["errorTail"] = "\n".join(
            (completed.stderr or completed.stdout).splitlines()[-12:]
        )
        return result

    if completed.returncode != 0:
        raise RuntimeError(
            f"variant {item['variantId']} failed with exit code "
            f"{completed.returncode}; see {log_path}"
        )
    if not report_path.is_file():
        raise FileNotFoundError(report_path)
    report = read_object(report_path)
    if report.get("candidateId") != item["candidateId"]:
        raise ValueError(f"candidate identity mismatch for {item['variantId']}")
    fingerprint = report.get("geometryFingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise ValueError(f"geometry fingerprint missing for {item['variantId']}")
    pose_views = report.get("poseViews")
    if not isinstance(pose_views, dict) or len(pose_views) < 6:
        raise ValueError(f"pose evidence incomplete for {item['variantId']}")
    for relative in pose_views.values():
        if not (ROOT / str(relative)).is_file():
            raise FileNotFoundError(relative)

    result.update(
        {
            "status": "PASS",
            "geometryFingerprint": fingerprint,
            "reportSha256": sha256(report_path),
            "materialRecipeSha256": report["materialRecipe"]["sha256"],
            "poseEvidenceCount": len(pose_views),
            "geometryPassed": bool(report.get("passed")),
        }
    )
    if report.get("passed") is not True:
        raise RuntimeError(
            f"variant {item['variantId']} generated artifacts but failed geometry gates"
        )
    return result


def verify_workspace(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_variant = {result["variantId"]: result for result in results}
    required = {"baseline", "black-black", "compact-large", "invalid-zero-bib"}
    if set(by_variant) != required:
        raise ValueError("variant batch does not contain the canonical proof set")

    baseline = by_variant["baseline"]
    color = by_variant["black-black"]
    size = by_variant["compact-large"]
    negative = by_variant["invalid-zero-bib"]
    if baseline["status"] != color["status"] or baseline["status"] != size["status"]:
        raise ValueError("successful production variants did not all PASS")
    if baseline["geometryFingerprint"] != color["geometryFingerprint"]:
        raise ValueError("color variant changed geometry")
    if baseline["materialRecipeSha256"] == color["materialRecipeSha256"]:
        raise ValueError("color variant did not change the material recipe")
    if baseline["geometryFingerprint"] == size["geometryFingerprint"]:
        raise ValueError("size variant did not change geometry")
    if negative["status"] != "EXPECTED_FAIL":
        raise ValueError("negative-control variant did not fail as expected")

    baseline_report = ROOT / str(baseline["reportPath"])
    if sha256(baseline_report) != baseline["reportSha256"]:
        raise ValueError("failed variant corrupted the baseline candidate")

    return {
        "colorGeometryMatchesBaseline": True,
        "colorMaterialChanged": True,
        "sizeGeometryChanged": True,
        "negativeControlFailed": True,
        "baselinePreservedAfterFailure": True,
        "successfulCandidates": 3,
        "totalAttempts": 4,
        "retryCount": 0,
        "elapsedSeconds": round(
            sum(float(result["elapsedSeconds"]) for result in results),
            3,
        ),
    }


def run_workspace(
    workspace_id: str,
    *,
    recipe: dict[str, Any],
    blender: str,
    include_variants: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    items = materialize_all_variants(
        ROOT,
        base_job=read_object(BASE_JOB),
        base_request=read_object(BASE_REQUEST),
        base_material_recipe=read_object(BASE_MATERIAL),
        production_recipe=recipe,
        workspace_id=workspace_id,
    )
    if include_variants is not None:
        items = [item for item in items if item["variantId"] in include_variants]
    results = [build_candidate(item, blender=blender) for item in items]
    proof = verify_workspace(results) if include_variants is None else None
    return results, proof


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe", type=Path, default=DEFAULT_RECIPE)
    parser.add_argument("--workspace", default="proof-a")
    parser.add_argument("--replay-workspace")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".image2outfit/variant-production/report.json"),
    )
    args = parser.parse_args()

    recipe_path = args.recipe if args.recipe.is_absolute() else ROOT / args.recipe
    recipe = read_object(recipe_path)
    blender = blender_executable()

    primary_results, primary_proof = run_workspace(
        args.workspace,
        recipe=recipe,
        blender=blender,
    )
    replay_results: list[dict[str, Any]] = []
    replay_proof: dict[str, Any] | None = None
    if args.replay_workspace:
        replay_results, _ = run_workspace(
            args.replay_workspace,
            recipe=recipe,
            blender=blender,
            include_variants={"black-black", "compact-large"},
        )
        first = {item["variantId"]: item for item in primary_results}
        replay = {item["variantId"]: item for item in replay_results}
        for variant_id in ("black-black", "compact-large"):
            if (
                first[variant_id]["geometryFingerprint"]
                != replay[variant_id]["geometryFingerprint"]
            ):
                raise ValueError(
                    f"replay geometry fingerprint mismatch: {variant_id}"
                )
            if first[variant_id]["geometryPassed"] != replay[variant_id]["geometryPassed"]:
                raise ValueError(f"replay geometry gate mismatch: {variant_id}")
        replay_proof = {
            "workspace": args.replay_workspace,
            "variants": ["black-black", "compact-large"],
            "sameGeometryFingerprints": True,
            "sameGeometryGateResults": True,
            "successfulCandidates": 2,
            "totalAttempts": 2,
            "retryCount": 0,
            "elapsedSeconds": round(
                sum(float(result["elapsedSeconds"]) for result in replay_results),
                3,
            ),
        }

    report = {
        "schemaVersion": 1,
        "baseProductId": BASE_PRODUCT_ID,
        "recipePath": recipe_path.relative_to(ROOT).as_posix(),
        "recipeSha256": sha256(recipe_path),
        "recipeVersion": recipe["recipeVersion"],
        "workspace": args.workspace,
        "primary": primary_results,
        "primaryProof": primary_proof,
        "replay": replay_results,
        "replayProof": replay_proof,
        "productionSuccessCount": 3 + (2 if replay_results else 0),
        "productionAttemptCount": 4 + (2 if replay_results else 0),
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
