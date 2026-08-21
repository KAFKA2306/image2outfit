#!/usr/bin/env python3
"""Validate that repository merge policy is independent from product release policy."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MERGE_POLICY = ROOT / "config" / "pr-merge-policy.json"
COMPLETION_POLICY = ROOT / "config" / "genworks-handoff-policy.json"
RELEASE_POLICY = ROOT / "config" / "release-policy.json"
WORKFLOWS = ROOT / ".github" / "workflows"
PR_TEMPLATE = ROOT / ".github" / "pull_request_template.md"
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


def validate() -> dict[str, Any]:
    merge = _read_json(MERGE_POLICY)
    completion = _read_json(COMPLETION_POLICY)
    release = _read_json(RELEASE_POLICY)
    merge_gate = merge.get("mergeGate") if isinstance(merge.get("mergeGate"), dict) else {}
    release_gate = (
        merge.get("productReleaseGate")
        if isinstance(merge.get("productReleaseGate"), dict)
        else {}
    )
    merge_workflow_path = _workflow_path(merge_gate, "workflowFile")
    release_workflow_path = _workflow_path(release_gate, "workflowFile")
    merge_workflow = merge_workflow_path.read_text(encoding="utf-8")
    release_workflow = release_workflow_path.read_text(encoding="utf-8")
    template = PR_TEMPLATE.read_text(encoding="utf-8")

    errors: list[str] = []
    rules = merge.get("rules") if isinstance(merge.get("rules"), dict) else {}

    expected_true = (
        "mergeDoesNotReleaseProduct",
        "affectedProductExecutionMustReachValidBoundary",
        "releaseCommandForbiddenInMergeGate",
        "releaseWorkflowMustBeManual",
    )
    expected_false = (
        "productCompletionRequiredForMerge",
        "productReleaseEligibilityRequiredForMerge",
        "productVisualPassRequiredForMerge",
        "productRuntimePassRequiredForMerge",
    )
    for name in expected_true:
        if rules.get(name) is not True:
            errors.append(f"merge-policy.rules.{name}=true")
    for name in expected_false:
        if rules.get(name) is not False:
            errors.append(f"merge-policy.rules.{name}=false")

    if merge.get("schemaVersion") != 1 or merge.get("scope") != "pull-request-merge":
        errors.append("merge-policy identity")
    if merge.get("productCompletionPolicy") != "config/genworks-handoff-policy.json":
        errors.append("merge-policy productCompletionPolicy")
    if merge.get("productReleasePolicy") != "config/release-policy.json":
        errors.append("merge-policy productReleasePolicy")

    merge_name = merge_gate.get("workflowName")
    if not isinstance(merge_name, str) or not merge_name:
        errors.append("merge-policy mergeGate.workflowName")
    elif f"name: {merge_name}" not in merge_workflow:
        errors.append("canonical merge workflow name does not match merge policy")

    if release_gate.get("manualDispatchRequired") is not True:
        errors.append("merge-policy productReleaseGate.manualDispatchRequired=true")
    validator = release_gate.get("validatorCommand")
    if not isinstance(validator, str) or not validator:
        errors.append("merge-policy productReleaseGate.validatorCommand")

    allowed_states = set(merge.get("allowedTrackedProductStatesAtMerge", []))
    tracked_states = set(completion.get("statuses", []))
    if not {"WORKING", "REJECTED"}.issubset(allowed_states):
        errors.append("merge-policy must allow WORKING and REJECTED product state")
    if not allowed_states.issubset(tracked_states):
        errors.append("merge-policy contains unknown product state")

    if not release.get("requiredHumanEvidenceKinds"):
        errors.append("release policy must retain human evidence requirements")
    if release.get("singleReleaseValidator") != "tools/customer_quality.py":
        errors.append("release policy must retain the dedicated release validator")

    forbidden_merge_tokens = (
        "manage.py release",
        "production_gate.py --mode release",
        "customer_quality.py",
        release_workflow_path.name,
    )
    for token in forbidden_merge_tokens:
        if token in merge_workflow:
            errors.append(f"PR merge workflow invokes release path: {token}")

    if "pull_request:" not in merge_workflow:
        errors.append("PR merge workflow must run on pull_request")
    if "paths:" in merge_workflow or "paths-ignore:" in merge_workflow:
        errors.append("canonical PR merge workflow must run for every PR")
    if "workflow_dispatch:" not in release_workflow:
        errors.append("product release workflow must remain manual")
    if "pull_request:" in release_workflow or "\n  push:" in release_workflow:
        errors.append("product release workflow must not run on PR or push")
    if isinstance(validator, str) and validator not in release_workflow:
        errors.append("product release workflow must invoke configured release validator")
    if LEGACY_POLICY_WORKFLOW.exists():
        errors.append("legacy policy-tests.yml must be removed")

    required_template_sections = (
        "## Merge readiness",
        "## Product state / release",
    )
    for section in required_template_sections:
        if section not in template:
            errors.append(f"PR template missing {section}")

    return {
        "schemaVersion": 1,
        "mergePolicy": str(MERGE_POLICY.relative_to(ROOT)),
        "mergeGateWorkflow": str(merge_workflow_path.relative_to(ROOT)),
        "productReleasePolicy": str(RELEASE_POLICY.relative_to(ROOT)),
        "productReleaseWorkflow": str(release_workflow_path.relative_to(ROOT)),
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
