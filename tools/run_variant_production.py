#!/usr/bin/env python3
"""Build and verify production variants with the canonical product builder."""

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


def base_paths(recipe: dict[str, Any]) -> dict[str, Path]:
    product_id = recipe.get("baseProductId")
    if not isinstance(product_id, str) or not product_id:
        raise ValueError("production recipe baseProductId is required")
    product = ROOT / "config" / "products" / product_id
    return {
        "job": product / "job.json",
        "request": ROOT / "config" / "pipeline" / "requests" / f"{product_id}.json",
        "material": product / "material-recipe.json",
    }


def build_candidate(item: dict[str, Any], *, blender: str) -> dict[str, Any]:
    job = read_object(item["jobPath"])
    contract = item["variantContract"]
    expected = contract["expectedResult"]
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
        "proofRole": contract["proofRole"],
        "workspaceId": item["workspaceId"],
        "expectedResult": expected,
        "returnCode": completed.returncode,
        "elapsedSeconds": round(elapsed, 3),
        "attempts": 1,
        "logPath": log_path.relative_to(ROOT).as_posix(),
        "productRoot": job["productRoot"],
        "reportPath": (
            report_path.relative_to(ROOT).as_posix() if report_path.is_file() else None
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

    target_profile = report.get("targetProfile")
    weight_normalization = report.get("weightNormalization")
    if not isinstance(target_profile, dict):
        raise ValueError(f"target profile evidence missing for {item['variantId']}")
    if not isinstance(weight_normalization, dict):
        raise ValueError(
            f"weight normalization evidence missing for {item['variantId']}"
        )
    if int(weight_normalization.get("vertices", 0)) <= 0:
        raise ValueError(
            f"weight normalization processed no vertices for {item['variantId']}"
        )
    if int(weight_normalization.get("maximumInfluences", 99)) > 4:
        raise ValueError(
            f"weight normalization exceeded four influences for {item['variantId']}"
        )

    result.update(
        {
            "status": "PASS",
            "geometryFingerprint": fingerprint,
            "reportSha256": sha256(report_path),
            "materialRecipeSha256": report["materialRecipe"]["sha256"],
            "poseEvidenceCount": len(pose_views),
            "geometryPassed": bool(report.get("passed")),
            "shapeProfileEvidence": target_profile,
            "weightNormalizationEvidence": {
                "objects": weight_normalization.get("objects"),
                "vertices": weight_normalization.get("vertices"),
                "maximumInfluences": weight_normalization.get("maximumInfluences"),
                "fallbackVertices": weight_normalization.get("fallbackVertices"),
            },
        }
    )
    if report.get("passed") is not True:
        raise RuntimeError(
            f"variant {item['variantId']} generated artifacts but failed geometry gates"
        )
    return result


def by_role(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for result in results:
        role = str(result["proofRole"])
        if role in mapped:
            raise ValueError(f"duplicate proof role: {role}")
        mapped[role] = result
    return mapped


def verify_workspace(results: list[dict[str, Any]]) -> dict[str, Any]:
    roles = by_role(results)
    required = {"BASELINE", "COLOR", "SIZE", "NEGATIVE"}
    if set(roles) != required:
        raise ValueError("variant batch does not contain the canonical proof roles")

    baseline = roles["BASELINE"]
    color = roles["COLOR"]
    size = roles["SIZE"]
    negative = roles["NEGATIVE"]
    if baseline["status"] != "PASS" or color["status"] != "PASS":
        raise ValueError("baseline/color production candidate did not PASS")
    if size["status"] != "PASS":
        raise ValueError("size production candidate did not PASS")
    if baseline["geometryFingerprint"] != color["geometryFingerprint"]:
        raise ValueError("color variant changed geometry")
    if baseline["materialRecipeSha256"] == color["materialRecipeSha256"]:
        raise ValueError("color variant did not change the material recipe")
    if baseline["geometryFingerprint"] == size["geometryFingerprint"]:
        raise ValueError("size variant did not change geometry")
    if size.get("poseEvidenceCount", 0) < 6:
        raise ValueError("size variant did not regenerate all required pose evidence")
    size_profile = size.get("shapeProfileEvidence")
    if not isinstance(size_profile, dict):
        raise ValueError("size variant shape profile evidence is missing")
    applied_shape_keys = size_profile.get("appliedShapeKeys")
    if not isinstance(applied_shape_keys, dict) or applied_shape_keys.get("All_L") != 0.85:
        raise ValueError("size variant did not apply the requested shape profile")
    size_weights = size.get("weightNormalizationEvidence")
    if not isinstance(size_weights, dict) or int(size_weights.get("vertices", 0)) <= 0:
        raise ValueError("size variant did not rerun weight normalization")
    if int(size_weights.get("maximumInfluences", 99)) > 4:
        raise ValueError("size variant weight normalization is invalid")
    if negative["status"] != "EXPECTED_FAIL":
        raise ValueError("negative-control variant did not fail as expected")

    baseline_report = ROOT / str(baseline["reportPath"])
    if sha256(baseline_report) != baseline["reportSha256"]:
        raise ValueError("failed variant corrupted the baseline candidate")

    return {
        "colorGeometryMatchesBaseline": True,
        "colorMaterialChanged": True,
        "sizeGeometryChanged": True,
        "sizeFitRevalidated": True,
        "sizeWeightsRevalidated": True,
        "sizePoseEvidenceRevalidated": True,
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


def materialized_items(
    recipe: dict[str, Any],
    *,
    workspace_id: str,
) -> list[dict[str, Any]]:
    paths = base_paths(recipe)
    return materialize_all_variants(
        ROOT,
        base_job=read_object(paths["job"]),
        base_request=read_object(paths["request"]),
        base_material_recipe=read_object(paths["material"]),
        production_recipe=recipe,
        workspace_id=workspace_id,
    )


def run_workspace(
    workspace_id: str,
    *,
    recipe: dict[str, Any],
    blender: str,
    include_roles: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    items = materialized_items(recipe, workspace_id=workspace_id)
    if include_roles is not None:
        items = [
            item
            for item in items
            if item["variantContract"]["proofRole"] in include_roles
        ]
    results = [build_candidate(item, blender=blender) for item in items]
    proof = verify_workspace(results) if include_roles is None else None
    return results, proof


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--workspace", default="proof-a")
    parser.add_argument("--replay-workspace")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    recipe_path = args.recipe if args.recipe.is_absolute() else ROOT / args.recipe
    recipe = read_object(recipe_path)
    product_id = str(recipe["baseProductId"])
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
            include_roles={"COLOR", "SIZE"},
        )
        first = by_role(primary_results)
        replay = by_role(replay_results)
        for role in ("COLOR", "SIZE"):
            if (
                first[role]["geometryFingerprint"]
                != replay[role]["geometryFingerprint"]
            ):
                raise ValueError(f"replay geometry fingerprint mismatch: {role}")
            if first[role]["geometryPassed"] != replay[role]["geometryPassed"]:
                raise ValueError(f"replay geometry gate mismatch: {role}")
        replay_proof = {
            "workspace": args.replay_workspace,
            "roles": ["COLOR", "SIZE"],
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
        "baseProductId": product_id,
        "recipePath": recipe_path.relative_to(ROOT).as_posix(),
        "recipeSha256": sha256(recipe_path),
        "recipeVersion": recipe["recipeVersion"],
        "workspace": args.workspace,
        "primary": primary_results,
        "primaryProof": primary_proof,
        "replay": replay_results,
        "replayProof": replay_proof,
        "productionSuccessCount": sum(
            result["status"] == "PASS" for result in [*primary_results, *replay_results]
        ),
        "productionAttemptCount": len(primary_results) + len(replay_results),
    }
    output = args.output
    if output is None:
        output = (
            Path(".image2outfit") / "variant-production" / product_id / "report.json"
        )
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
