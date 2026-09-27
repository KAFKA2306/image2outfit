#!/usr/bin/env python3
"""Policy-derived ProductManifest completion and runtime projection."""

from __future__ import annotations

import re
from typing import Any

KNOWN_GATE_STATUSES = frozenset({"PASS", "FAIL", "PENDING", "NOT_RUN"})


def normalize_gate_name(value: Any) -> str:
    """Normalize spelling without maintaining policy-specific aliases."""
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(value))
    words = re.sub(r"[^A-Za-z0-9]+", " ", words).lower().split()
    return "".join(word for word in words if word != "and")


def _gate_status(value: Any) -> str:
    if value is None:
        return "MISSING"
    status = str(value).strip().upper()
    return status if status in KNOWN_GATE_STATUSES else "INVALID"


def _normalized_gate_map(value: Any) -> tuple[dict[str, tuple[str, Any]], list[str]]:
    if not isinstance(value, dict):
        return {}, []
    result: dict[str, tuple[str, Any]] = {}
    errors: list[str] = []
    for name, status in value.items():
        normalized = normalize_gate_name(name)
        if normalized in result:
            errors.append(f"duplicate normalized gate name: {name}")
            continue
        result[normalized] = (str(name), status)
    return result, errors


def project_product_completion(
    manifest: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    """Project one ProductManifest through the canonical handoff policy."""
    errors: list[str] = []

    configured_states = [
        str(value).strip().upper()
        for value in policy.get("statuses", [])
        if str(value).strip()
    ]
    state_values = [
        str(manifest[key]).strip().upper()
        for key in ("state", "status", "product_state", "release_state")
        if manifest.get(key) not in (None, "")
    ]
    distinct_states = list(dict.fromkeys(state_values))
    if len(distinct_states) > 1:
        errors.append("product lifecycle fields contradict each other")
        state = "INVALID"
    elif distinct_states:
        state = distinct_states[0]
        if configured_states and state not in configured_states:
            errors.append(f"unknown product lifecycle state: {state}")
            state = "INVALID"
    elif configured_states:
        errors.append("product lifecycle state is missing")
        state = "INVALID"
    else:
        state = "WORKING"

    required_names = [str(name) for name in policy.get("requiredCompletionGates", [])]
    completion_values, completion_map_errors = _normalized_gate_map(
        manifest.get("completionGates")
    )
    errors.extend(completion_map_errors)
    completion_gates: list[dict[str, str]] = []
    completion_blockers: list[dict[str, str]] = []
    for required_name in required_names:
        row = completion_values.get(normalize_gate_name(required_name))
        raw_status = row[1] if row else None
        status = _gate_status(raw_status)
        if raw_status is not None and status == "INVALID":
            errors.append(
                f"completion gate has unknown status: {required_name}={raw_status}"
            )
        completion_gates.append({"name": required_name, "status": status})
        if status != "PASS":
            completion_blockers.append(
                {
                    "severity": "COMPLETION",
                    "gate": required_name,
                    "status": status,
                    "message": f"completion gate is not PASS: {required_name} ({status})",
                }
            )

    technical_values, technical_map_errors = _normalized_gate_map(
        manifest.get("technicalGates")
    )
    errors.extend(technical_map_errors)
    for actual_name, raw_status in technical_values.values():
        if _gate_status(raw_status) == "INVALID":
            errors.append(
                f"technical gate has unknown status: {actual_name}={raw_status}"
            )

    runtime_gates: list[dict[str, str]] = []
    for policy_name in policy.get("outOfScopeGates", []):
        row = technical_values.get(normalize_gate_name(policy_name))
        if row is None:
            continue
        actual_name, raw_status = row
        runtime_gates.append(
            {
                "name": actual_name,
                "policyName": str(policy_name),
                "status": _gate_status(raw_status),
            }
        )

    completion_status = str(policy.get("completionStatus", "COMPLETE")).upper()
    if state == completion_status:
        if not isinstance(manifest.get("completionGates"), dict):
            errors.append("complete product requires completionGates")
        for blocker in completion_blockers:
            errors.append(f"complete product gate is not PASS: {blocker['gate']}")

    return {
        "state": state,
        "completionGates": completion_gates,
        "completionBlockers": completion_blockers,
        "runtimeGates": runtime_gates,
        "errors": list(dict.fromkeys(errors)),
    }


__all__ = [
    "KNOWN_GATE_STATUSES",
    "normalize_gate_name",
    "project_product_completion",
]
