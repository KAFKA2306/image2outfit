#!/usr/bin/env python3
"""Pure quality-decision helpers for auditable garment pipeline stages."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

QUALITY_PASS = "PASS"
QUALITY_REJECT = "REJECT"
QUALITY_PENDING = "PENDING"
VALID_QUALITY_DECISIONS = frozenset(
    {QUALITY_PASS, QUALITY_REJECT, QUALITY_PENDING}
)


def _validate_quality_decision(value: str, label: str) -> None:
    if value not in VALID_QUALITY_DECISIONS:
        raise ValueError(f"{label} has unknown quality decision: {value!r}")


def geometry_quality(report: Mapping[str, Any]) -> dict[str, Any]:
    """Return a quality decision without conflating rejection with execution failure."""
    metrics = report.get("metrics")
    if not isinstance(metrics, Mapping):
        raise ValueError("geometry report metrics are missing")

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
    failed_checks.extend(
        name for name, passed in fallback_checks.items() if not passed
    )
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
    required = {
        "schemaVersion": 1,
        "productId": product_id,
        "reviewMethod": "direct-image-inspection",
        "reviewedRevision": revision_id,
    }
    mismatches = {
        key: {"found": review.get(key), "expected": expected}
        for key, expected in required.items()
        if review.get(key) != expected
    }
    if mismatches:
        raise ValueError(f"visual review contract mismatch: {mismatches}")

    status = review.get("status")
    decision = review.get("decision")
    expected_decision = {
        "PASS": QUALITY_PASS,
        "REJECTED": QUALITY_REJECT,
    }.get(status)
    if expected_decision is None:
        raise ValueError("visual review status must be PASS or REJECTED")
    if decision != expected_decision:
        raise ValueError(
            "visual review decision is inconsistent with status: "
            f"{decision!r} != {expected_decision!r}"
        )

    inspected = review.get("inspectedImages")
    if not isinstance(inspected, Mapping) or not inspected:
        raise ValueError("visual review inspectedImages must be a non-empty object")
    if not all(isinstance(path, str) and path for path in inspected):
        raise ValueError("visual review inspectedImages paths must be non-empty strings")
    if not all(
        isinstance(digest, str) and len(digest) == 64
        for digest in inspected.values()
    ):
        raise ValueError("visual review inspectedImages values must be SHA-256 digests")

    findings = review.get("findings", [])
    if not isinstance(findings, list):
        raise ValueError("visual review findings must be a list")
    if expected_decision == QUALITY_REJECT and not findings:
        raise ValueError("a rejected visual review must record at least one finding")

    return {
        "decision": expected_decision,
        "status": str(status),
        "inspectedImages": dict(inspected),
        "findings": list(findings),
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
