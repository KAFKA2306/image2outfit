#!/usr/bin/env python3
"""Validate that repository merge and product release are separate gates."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "pr-merge-policy.json"
WORKFLOWS = ROOT / ".github" / "workflows"
LEGACY_POLICY_WORKFLOW = WORKFLOWS / "policy-tests.yml"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain a JSON object")
    return value


def _workflow_path(spec: dict[str, Any], key: str) -> Path:
    value = spec.get(key)
    if not isinstance(value, str) or not value or Path(value).name != value:
        raise ValueError(f"workflow {key} must be a file name")
    return WORKFLOWS / value


def _trigger_has_path_filter(workflow: str, trigger: str = "pull_request") -> bool:
    """Inspect one top-level GitHub Actions trigger block for path filters."""
    lines = workflow.splitlines()
    try:
        on_index = lines.index("on:")
    except ValueError:
        return False

    trigger_index: int | None = None
    for index in range(on_index + 1, len(lines)):
        raw = lines[index]
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent == 0:
            break
        if indent == 2 and stripped == f"{trigger}:":
            trigger_index = index
            break
    if trigger_index is None:
        return False

    for raw in lines[trigger_index + 1 :]:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent <= 2:
            break
        if stripped.startswith(("paths:", "paths-ignore:")):
            return True
    return False


def validate() -> dict[str, Any]:
    policy = _read_json(POLICY)
    merge_gate = (
        policy.get("mergeGate") if isinstance(policy.get("mergeGate"), dict) else {}
    )
    release_gate = (
        policy.get("productReleaseGate")
        if isinstance(policy.get("productReleaseGate"), dict)
        else {}
    )
    merge_workflow_path = _workflow_path(merge_gate, "workflowFile")
    release_workflow_path = _workflow_path(release_gate, "workflowFile")
    merge_workflow = merge_workflow_path.read_text(encoding="utf-8")
    release_workflow = release_workflow_path.read_text(encoding="utf-8")

    errors: list[str] = []
    if policy.get("schemaVersion") != 1:
        errors.append("pr-merge-policy schemaVersion must be 1")

    allowed_states = set(policy.get("allowedTrackedProductStatesAtMerge", []))
    if not {"WORKING", "REJECTED"}.issubset(allowed_states):
        errors.append("merge policy must allow WORKING and REJECTED product states")

    merge_name = merge_gate.get("workflowName")
    if not isinstance(merge_name, str) or not merge_name:
        errors.append("mergeGate.workflowName is required")
    elif f"name: {merge_name}" not in merge_workflow:
        errors.append("merge workflow name does not match merge policy")

    if "pull_request:" not in merge_workflow:
        errors.append("merge workflow must run on pull_request")
    if _trigger_has_path_filter(merge_workflow):
        errors.append("merge workflow must run for every PR")
    if "Resolve changed Python files" not in merge_workflow:
        errors.append("merge workflow must resolve changed Python files")
    if "Ruff format changed Python" not in merge_workflow:
        errors.append("merge workflow must format-check changed Python only")

    validator = release_gate.get("validatorCommand")
    forbidden_merge_tokens = (
        "manage.py release",
        "production_gate.py --mode release",
        "customer_quality.py",
        release_workflow_path.name,
    )
    for token in forbidden_merge_tokens:
        if token in merge_workflow:
            errors.append(f"merge workflow invokes release path: {token}")

    if "workflow_dispatch:" not in release_workflow:
        errors.append("release workflow must be manual")
    if "pull_request:" in release_workflow or "\n  push:" in release_workflow:
        errors.append("release workflow must not run on PR or push")
    if not isinstance(validator, str) or not validator:
        errors.append("productReleaseGate.validatorCommand is required")
    elif validator not in release_workflow:
        errors.append("release workflow must invoke configured validator")

    if LEGACY_POLICY_WORKFLOW.exists():
        errors.append("legacy policy-tests.yml must be removed")

    return {
        "schemaVersion": 1,
        "mergeEligible": not errors,
        "productReleaseEvaluated": False,
        "errors": errors,
    }


def main() -> int:
    try:
        result = validate()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"PR merge gate: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["mergeEligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
