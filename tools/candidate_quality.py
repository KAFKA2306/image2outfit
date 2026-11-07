#!/usr/bin/env python3
"""Pure quality-decision helpers for auditable garment pipeline stages."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from quality_schema import load_schema, path_label, violations

QUALITY_PASS = "PASS"
QUALITY_REJECT = "REJECT"
QUALITY_PENDING = "PENDING"
VALID_QUALITY_DECISIONS = frozenset({QUALITY_PASS, QUALITY_REJECT, QUALITY_PENDING})


def _require_valid(schema_name: str, instance: Any, label: str) -> None:
    """Raise ValueError at the first violation of a contracts/quality schema."""
    errors = violations(load_schema(schema_name), instance)
    if errors:
        first = errors[0]
        where = path_label(*first.absolute_path) or "$"
        raise ValueError(f"{label} contract violation at {where}: {first.message}")


def _validate_quality_decision(value: str, label: str) -> None:
    if value not in VALID_QUALITY_DECISIONS:
        raise ValueError(f"{label} has unknown quality decision: {value!r}")


def geometry_quality(report: Mapping[str, Any]) -> dict[str, Any]:
    """Return a quality decision without conflating rejection with execution failure."""
    _require_valid("geometry-report.schema.v1.json", report, "geometry report")
    metrics = report["metrics"]

    gate = report.get("geometryGate")
    failed_checks: list[str] = []
    if isinstance(gate, Mapping):
        checks = gate.get("checks")
        if isinstance(checks, Mapping):
            failed_checks.extend(
                str(name) for name, passed in checks.items() if passed is not True
            )

    fallback_checks = {
        "buildReportPassed": report.get("passed") is True,
        "unweightedVertices==0": metrics.get("unweightedVertices") == 0,
        "degenerateTriangles==0": metrics.get("degenerateTriangles") == 0,
    }
    failed_checks.extend(name for name, passed in fallback_checks.items() if not passed)
    failed_checks = sorted(set(failed_checks))
    passed = not failed_checks
    return {
        "decision": QUALITY_PASS if passed else QUALITY_REJECT,
        "passed": passed,
        "failedChecks": failed_checks,
        "metrics": dict(metrics),
    }


def validate_visual_review(
    review: Mapping[str, Any],
    *,
    product_id: str,
    revision_id: str,
) -> dict[str, Any]:
    """Validate a direct-image review and normalize PASS/REJECT semantics."""
    _require_valid("visual-review.schema.v1.json", review, "visual review")

    mismatches = {
        key: {"found": review.get(key), "expected": expected}
        for key, expected in {
            "productId": product_id,
            "reviewedRevision": revision_id,
        }.items()
        if review.get(key) != expected
    }
    if mismatches:
        raise ValueError(f"visual review contract mismatch: {mismatches}")

    status = review["status"]
    expected_decision = QUALITY_PASS if status == "PASS" else QUALITY_REJECT
    return {
        "decision": expected_decision,
        "status": str(status),
        "inspectedImages": dict(review["inspectedImages"]),
        "findings": list(review.get("findings", [])),
    }


def verify_inspected_images(
    inspected_images: Mapping[str, str],
    current_images: Mapping[str, str],
) -> None:
    """Reject stale reviews when the inspected image set or any digest changed."""
    expected_paths = set(current_images)
    inspected_paths = set(inspected_images)
    if inspected_paths != expected_paths:
        missing = sorted(expected_paths - inspected_paths)
        extra = sorted(inspected_paths - expected_paths)
        raise ValueError(
            f"visual review image set mismatch: missing={missing}, extra={extra}"
        )
    mismatches = {
        path: {"reviewed": inspected_images[path], "current": digest}
        for path, digest in current_images.items()
        if inspected_images[path] != digest
    }
    if mismatches:
        raise ValueError(f"visual review image hash mismatch: {mismatches}")


def candidate_status(
    gates: Mapping[str, bool],
    *,
    geometry_decision: str,
    visual_decision: str,
) -> str:
    """Resolve COMPLETE, REJECTED, or WORKING without hiding quality failures."""
    _validate_quality_decision(geometry_decision, "geometry_decision")
    _validate_quality_decision(visual_decision, "visual_decision")
    if all(gates.values()):
        return "COMPLETE"
    if QUALITY_REJECT in {geometry_decision, visual_decision}:
        return "REJECTED"
    return "WORKING"
