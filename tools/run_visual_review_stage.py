#!/usr/bin/env python3
"""Record a completed direct visual review without conflating verdict with execution."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from run_reference_product_stage import emit, read_object, repo_path
import visual_review_bundle


def build_review_bundle(job_path: Path, request_path: Path) -> dict[str, Any]:
    """Build the Stage 12 hash-bound review bundle using the canonical helper."""
    return visual_review_bundle.build_review_bundle(job_path, request_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    return parser.parse_args()


def validate_review(
    payload: Mapping[str, Any], *, product_id: str, revision: str
) -> str:
    required = {
        "schemaVersion": 1,
        "productId": product_id,
        "reviewMethod": "direct-image-inspection",
        "reviewedRevision": revision,
    }
    mismatches = {
        key: {"found": payload.get(key), "expected": expected}
        for key, expected in required.items()
        if payload.get(key) != expected
    }
    if mismatches:
        raise ValueError(f"visual review contract mismatch: {mismatches}")

    status = payload.get("status")
    if status not in {"PASS", "FAIL"}:
        raise ValueError("visual review status must be PASS or FAIL")
    decision = payload.get("decision")
    if not isinstance(decision, str) or not decision:
        raise ValueError("visual review decision must be a non-empty string")
    if status == "FAIL" and decision == "ACCEPT":
        raise ValueError("a failed visual review cannot record decision ACCEPT")
    return status


def main() -> int:
    args = parse_args()
    job_path = repo_path(args.job, label="job")
    request_path = repo_path(args.request, label="request")
    result_path = repo_path(args.result, label="result")
    runtime = (Path(__file__).resolve().parents[1] / ".image2outfit").resolve()
    if result_path != runtime and runtime not in result_path.parents:
        raise ValueError("result must be inside .image2outfit runtime state")

    job = read_object(job_path, "job")
    request = read_object(request_path, "request")
    if job.get("schemaVersion") != 2 or request.get("schemaVersion") != 1:
        raise ValueError("job/request schema version mismatch")
    if job.get("id") != request.get("productId"):
        raise ValueError("job/request product identity mismatch")

    product_id = str(job["id"])
    review_path = repo_path(
        job["garmentPipeline"]["visualReviewPath"], label="visual review"
    )
    if not review_path.is_file():
        raise FileNotFoundError(
            "direct visual review is not recorded yet; inspect current render artifacts "
            f"and add {review_path.relative_to(Path(__file__).resolve().parents[1])}"
        )
    review = read_object(review_path, "visual review")
    review_status = validate_review(
        review,
        product_id=product_id,
        revision=str(request.get("revisionId", "")),
    )

    views = [
        repo_path(value, label="preview") for value in job["previewPaths"].values()
    ]
    poses = [
        repo_path(value, label="pose") for value in job.get("posePaths", {}).values()
    ]
    emit(
        result_path,
        stage="visual-review",
        product_id=product_id,
        paths=[review_path, *views, *poses],
        extra={
            "reviewMethod": "direct-image-inspection",
            "reviewStatus": review_status,
            "reviewDecision": review["decision"],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
