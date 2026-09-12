"""Machine-observable A/B/C evaluation for blueprint-guided hypothesis experiments."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

ROUTES = ("A", "B", "C")
SEMANTIC_MASK_ROLES = frozenset(
    {"shadow", "wrinkle", "seam", "material_region", "decoration"}
)


def _sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def _nonnegative_number(value: object, *, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{label} must be a finite non-negative number")
    return float(value)


def _nonnegative_int(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def validate_experiment_record(
    payload: Mapping[str, Any],
    *,
    expected_product_id: str | None = None,
) -> dict[str, Any]:
    if payload.get("schemaVersion") != 1:
        raise ValueError("experiment record schemaVersion must be 1")
    route = payload.get("route")
    if route not in ROUTES:
        raise ValueError("experiment route must be A, B, or C")
    product_id = payload.get("productId")
    if not isinstance(product_id, str) or not product_id:
        raise ValueError("experiment productId is required")
    if expected_product_id is not None and product_id != expected_product_id:
        raise ValueError("experiment product identity mismatch")

    identity = {
        "referenceSha256": _sha256(
            payload.get("referenceSha256"), label="referenceSha256"
        ),
        "initialBlueprintSha256": _sha256(
            payload.get("initialBlueprintSha256"), label="initialBlueprintSha256"
        ),
        "targetAvatarAuthoritySha256": _sha256(
            payload.get("targetAvatarAuthoritySha256"),
            label="targetAvatarAuthoritySha256",
        ),
        "qualitySpecSha256": _sha256(
            payload.get("qualitySpecSha256"), label="qualitySpecSha256"
        ),
    }

    status = payload.get("status")
    if status not in {"PASS", "FAILED", "REJECTED"}:
        raise ValueError("experiment status is invalid")

    metrics = payload.get("metrics")
    if not isinstance(metrics, Mapping):
        raise ValueError("experiment metrics must be an object")
    normalized_metrics = {
        "elapsedSeconds": _nonnegative_number(
            metrics.get("elapsedSeconds"), label="metrics.elapsedSeconds"
        ),
        "artifactBytes": _nonnegative_int(
            metrics.get("artifactBytes"), label="metrics.artifactBytes"
        ),
    }
    for key in (
        "invalidTopologyFindingCount",
        "uvFindingCount",
        "normalFindingCount",
        "materialRegionFindingCount",
        "silhouetteFindingCount",
        "skinningFindingCount",
        "collisionFindingCount",
        "canonicalQualityFindingCount",
    ):
        normalized_metrics[key] = _nonnegative_int(
            metrics.get(key), label=f"metrics.{key}"
        )
    machine_cost = metrics.get("machineCost")
    normalized_metrics["machineCost"] = (
        None
        if machine_cost is None
        else _nonnegative_number(machine_cost, label="metrics.machineCost")
    )

    gate_passed = payload.get("canonicalQualityGatePassed")
    if not isinstance(gate_passed, bool):
        raise ValueError("canonicalQualityGatePassed must be boolean")

    masks = payload.get("semanticMasks", [])
    if not isinstance(masks, list):
        raise ValueError("semanticMasks must be a list")
    normalized_masks: list[dict[str, str]] = []
    for index, raw in enumerate(masks):
        if not isinstance(raw, Mapping):
            raise ValueError(f"semanticMasks[{index}] must be an object")
        role = raw.get("role")
        if role not in SEMANTIC_MASK_ROLES:
            raise ValueError(f"semanticMasks[{index}].role is invalid")
        normalized_masks.append(
            {
                "role": str(role),
                "artifactSha256": _sha256(
                    raw.get("artifactSha256"),
                    label=f"semanticMasks[{index}].artifactSha256",
                ),
            }
        )
    if route == "C" and status == "PASS" and not normalized_masks:
        raise ValueError("a passing C route must record at least one semantic mask")

    return {
        "schemaVersion": 1,
        "route": route,
        "productId": product_id,
        **identity,
        "status": status,
        "metrics": normalized_metrics,
        "canonicalQualityGatePassed": gate_passed,
        "semanticMasks": normalized_masks,
    }


def compare_experiment_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if len(records) != 3:
        raise ValueError("formal A/B/C comparison requires exactly three records")
    validated = [validate_experiment_record(record) for record in records]
    by_route = {record["route"]: record for record in validated}
    if set(by_route) != set(ROUTES):
        raise ValueError("formal comparison requires one record for each A/B/C route")

    baseline = by_route["A"]
    identity_keys = (
        "productId",
        "referenceSha256",
        "initialBlueprintSha256",
        "targetAvatarAuthoritySha256",
        "qualitySpecSha256",
    )
    for route in ("B", "C"):
        candidate = by_route[route]
        mismatch = [key for key in identity_keys if candidate[key] != baseline[key]]
        if mismatch:
            raise ValueError(f"route {route} identity mismatch: {mismatch}")

    def assess(candidate: Mapping[str, Any]) -> dict[str, Any]:
        base_metrics = baseline["metrics"]
        metrics = candidate["metrics"]
        quality_nonregression = candidate["canonicalQualityGatePassed"] and (
            not baseline["canonicalQualityGatePassed"]
            or metrics["canonicalQualityFindingCount"]
            <= base_metrics["canonicalQualityFindingCount"]
        )
        elapsed_improved = metrics["elapsedSeconds"] < base_metrics["elapsedSeconds"]
        base_cost = base_metrics["machineCost"]
        candidate_cost = metrics["machineCost"]
        comparable_cost = base_cost is not None and candidate_cost is not None
        cost_nonregression = comparable_cost and candidate_cost <= base_cost
        quality_improved = (
            candidate["canonicalQualityGatePassed"]
            and metrics["canonicalQualityFindingCount"]
            < base_metrics["canonicalQualityFindingCount"]
        )
        qualifies = (
            candidate["status"] == "PASS"
            and quality_nonregression
            and (elapsed_improved or (cost_nonregression and quality_improved))
        )
        return {
            "route": candidate["route"],
            "qualityNonRegression": quality_nonregression,
            "elapsedImproved": elapsed_improved,
            "costComparable": comparable_cost,
            "costNonRegression": cost_nonregression,
            "qualityImproved": quality_improved,
            "qualifiesForAdoption": qualifies,
        }

    b = assess(by_route["B"])
    c = assess(by_route["C"])
    if c["qualifiesForAdoption"]:
        decision = "CONTINUE"
        selected_route = "C"
    elif b["qualifiesForAdoption"]:
        decision = "LIMITED_ADOPTION"
        selected_route = "B"
    else:
        decision = "REJECT"
        selected_route = "A"

    return {
        "schemaVersion": 1,
        "productId": baseline["productId"],
        "decision": decision,
        "selectedRoute": selected_route,
        "baselineRoute": "A",
        "assessments": {"B": b, "C": c},
    }
