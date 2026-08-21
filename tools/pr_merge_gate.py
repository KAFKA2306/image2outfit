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


def _workflow_contract(policy: dict[str, Any], key: str) -> tuple[Path, str | None]:
    value = policy.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"merge-policy.{key} must be an object")
    filename = value.get("workflowFile")
    if not isinstance(filename, str) or not filename or Path(filename).name != filename:
        raise ValueError(f"merge-policy.{key}.workflowFile must be a file name")
    name = value.get("workflowName")
    if name is not None and (not isinstance(name, str) or not name):
        raise ValueError(f"merge-policy.{key}.workflowName must be a non-empty string")
    return WORKFLOWS / filename, name


def validate() -> dict[str, Any]:
    merge = _read_json(MERGE_POLICY)
    completion = _read_json(COMPLETION_POLICY)
    release = _read_json(RELEASE_POLICY)
    merge_workflow_path, merge_workflow_name = _workflow_contract(merge, "mergeGate")
    release_workflow_path, _ = _workflow_contract(merge, "productReleaseGate")
    merge_workflow = merge_workflow_path.read_text(encoding="utf-8")
    release_workflow = release_workflow_path.read_text(encoding="utf-8")
    template = PR_TEMPLATE.read_text(encoding="utf-8")

    errors: list[str] = []
    rules = merge.get("rules") if isinstance(merge.get("rules"), dict) else {}

    expected_true = (
        "mergeDoesNotReleaseProduct",
        "affectedProductExecutionMustReachValidBoundary",
        "releaseCommandForbiddenInMergeGate",
        "fullProductTestSuiteForbiddenInMergeGate",
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

    allowed_states = set(merge.get("allowedTrackedProductStatesAtMerge", []))
    tracked_states = set(completion.get("statuses", []))
    if not {"WORKING", "REJECTED"}.issubset(allowed_states):
        errors.append("merge-policy must allow WORKING and REJECTED product state")
    if not allowed_states.issubset(tracked_states):
        errors.append("merge-policy contains unknown product state")

    repository_evidence = set(merge.get("requiredRepositoryEvidence", []))
    required_evidence = {
        "lockfile-valid",
        "python-compiles",
        "repository-hygiene-audit-pass",
        "toolchain-audit-pass",
        "merge-contract-tests-pass",
        "tracked-contracts-parse",
        "changed-python-ruff-lint-pass",
        "changed-python-ruff-format-pass",
    }
    if repository_evidence != required_evidence:
        errors.append("merge-policy requiredRepositoryEvidence")
    if "unit-and-contract-tests-pass" in repository_evidence:
        errors.append("full product unit suite must not be merge evidence")

    if not release.get("requiredHumanEvidenceKinds"):
        errors.append("release policy must retain human evidence requirements")
    if release.get("singleReleaseValidator") != "tools/customer_quality.py":
        errors.append("release policy must retain the dedicated release validator")

    if merge_workflow_name and f"name: {merge_workflow_name}" not in merge_workflow:
        errors.append("PR merge workflow name does not match merge policy")
    if "pull_request:" not in merge_workflow:
        errors.append("PR merge workflow must run on pull_request")
    forbidden_merge_tokens = (
        "manage.py release",
        "production_gate.py --mode release",
        "customer_quality.py",
        "release-self-hosted.yml",
        "unittest discover -s tests",
        "tools/manage.py audit all",
    )
    for token in forbidden_merge_tokens:
        if token in merge_workflow:
            errors.append(f"PR merge workflow contains forbidden merge token: {token}")

    required_merge_tokens = (
        "tools/manage.py audit repository",
        "tools/manage.py audit toolchain",
        "tests/test_merge_release_separation.py",
        "tests/test_release_provenance_gate.py",
        "tests/test_repository_global_config_policy.py",
        "tests/test_repository_policies.py",
        "Parse tracked contracts",
        "tools/pr_merge_gate.py",
    )
    for token in required_merge_tokens:
        if token not in merge_workflow:
            errors.append(f"PR merge workflow missing integration check: {token}")

    if LEGACY_POLICY_WORKFLOW.exists():
        errors.append("legacy policy-tests.yml duplicates the canonical PR merge workflow")

    release_gate = merge.get("productReleaseGate")
    if not isinstance(release_gate, dict):
        errors.append("merge-policy productReleaseGate")
        release_gate = {}
    if release_gate.get("manualDispatchRequired") is not True:
        errors.append("product release gate must require manual dispatch")
    validator_command = release_gate.get("validatorCommand")
    if validator_command != "tools/production_gate.py --mode release":
        errors.append("product release validator command")
    if "workflow_dispatch:" not in release_workflow:
        errors.append("product release workflow must remain manual")
    if "pull_request:" in release_workflow or "\n  push:" in release_workflow:
        errors.append("product release workflow must not run on PR or push")
    if validator_command not in release_workflow:
        errors.append("product release workflow must invoke release mode")

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
        "mergeWorkflow": str(merge_workflow_path.relative_to(ROOT)),
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
