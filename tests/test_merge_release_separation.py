from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import pr_merge_gate  # noqa: E402


class MergeReleaseSeparationTests(unittest.TestCase):
    def policy(self) -> dict:
        return json.loads(
            (ROOT / "config" / "pr-merge-policy.json").read_text(encoding="utf-8")
        )

    def test_merge_policy_allows_non_release_product_states(self) -> None:
        policy = self.policy()
        rules = policy["rules"]
        self.assertFalse(rules["productCompletionRequiredForMerge"])
        self.assertFalse(rules["productReleaseEligibilityRequiredForMerge"])
        self.assertFalse(rules["productVisualPassRequiredForMerge"])
        self.assertFalse(rules["productRuntimePassRequiredForMerge"])
        self.assertFalse(rules["unrelatedExistingProductFailuresBlockMerge"])
        self.assertFalse(rules["unrelatedExistingLintDebtBlocksMerge"])
        self.assertTrue(rules["mergeDoesNotReleaseProduct"])
        self.assertTrue(rules["affectedProductExecutionMustReachValidBoundary"])
        self.assertIn("WORKING", policy["allowedTrackedProductStatesAtMerge"])
        self.assertIn("REJECTED", policy["allowedTrackedProductStatesAtMerge"])

    def test_policy_names_one_merge_gate_and_one_manual_release_gate(self) -> None:
        policy = self.policy()
        self.assertEqual(policy["mergeGate"]["workflowFile"], "pr-merge-gate.yml")
        self.assertEqual(policy["mergeGate"]["workflowName"], "PR merge gate")
        self.assertTrue(policy["productReleaseGate"]["manualDispatchRequired"])
        self.assertEqual(
            policy["productReleaseGate"]["validatorCommand"],
            "tools/production_gate.py --mode release",
        )
        self.assertNotIn("branchLifecycle", policy)

    def test_release_workflow_is_manual_and_not_a_merge_gate(self) -> None:
        policy = self.policy()
        workflows = ROOT / ".github" / "workflows"
        release = (workflows / policy["productReleaseGate"]["workflowFile"]).read_text(
            encoding="utf-8"
        )
        merge = (workflows / policy["mergeGate"]["workflowFile"]).read_text(
            encoding="utf-8"
        )
        self.assertIn("workflow_dispatch:", release)
        self.assertNotIn("pull_request:", release)
        self.assertNotIn("\n  push:", release)
        self.assertIn(policy["productReleaseGate"]["validatorCommand"], release)
        self.assertNotIn("production_gate.py --mode release", merge)
        self.assertNotIn("customer_quality.py", merge)

    def test_merge_workflow_has_no_pr_path_filter(self) -> None:
        policy = self.policy()
        merge = (
            ROOT / ".github" / "workflows" / policy["mergeGate"]["workflowFile"]
        ).read_text(encoding="utf-8")
        self.assertFalse(pr_merge_gate._trigger_has_path_filter(merge))

    def test_merge_lint_and_format_are_change_scoped(self) -> None:
        policy = self.policy()
        merge = (
            ROOT / ".github" / "workflows" / policy["mergeGate"]["workflowFile"]
        ).read_text(encoding="utf-8")
        self.assertIn("Resolve changed Python files", merge)
        self.assertIn("/tmp/changed-python.txt", merge)
        self.assertIn("Ruff lint changed Python", merge)
        self.assertIn("Ruff format changed Python", merge)
        self.assertNotIn("ruff check --ignore S102 src tools tests", merge)
        self.assertIn(
            "changed-python-ruff-lint-pass",
            policy["requiredRepositoryEvidence"],
        )
        self.assertIn(
            "changed-python-ruff-format-pass",
            policy["requiredRepositoryEvidence"],
        )

    def test_path_text_outside_pr_trigger_does_not_count_as_filter(self) -> None:
        workflow = """name: example
on:
  pull_request:
    branches: [main]
jobs:
  test:
    steps:
      - run: echo 'paths: is documentation text'
"""
        self.assertFalse(pr_merge_gate._trigger_has_path_filter(workflow))

    def test_actual_pr_path_filter_is_rejected(self) -> None:
        workflow = """name: example
on:
  pull_request:
    branches: [main]
    paths:
      - src/**
"""
        self.assertTrue(pr_merge_gate._trigger_has_path_filter(workflow))

    def test_legacy_release_named_merge_workflow_is_absent(self) -> None:
        self.assertFalse((ROOT / ".github" / "workflows" / "policy-tests.yml").exists())

    def test_static_merge_gate_contract_passes(self) -> None:
        result = pr_merge_gate.validate()
        self.assertTrue(result["mergeEligible"], result["errors"])
        self.assertFalse(result["productReleaseEvaluated"])


if __name__ == "__main__":
    unittest.main()
