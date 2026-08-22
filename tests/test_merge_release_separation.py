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

    def workflow(self, file_name: str) -> str:
        return (ROOT / ".github" / "workflows" / file_name).read_text(
            encoding="utf-8"
        )

    def test_policy_is_minimal(self) -> None:
        policy = self.policy()
        self.assertEqual(
            set(policy),
            {
                "schemaVersion",
                "mergeGate",
                "productReleaseGate",
                "allowedTrackedProductStatesAtMerge",
            },
        )
        self.assertIn("WORKING", policy["allowedTrackedProductStatesAtMerge"])
        self.assertIn("REJECTED", policy["allowedTrackedProductStatesAtMerge"])

    def test_policy_names_one_merge_gate_and_one_release_gate(self) -> None:
        policy = self.policy()
        self.assertEqual(policy["mergeGate"]["workflowFile"], "pr-merge-gate.yml")
        self.assertEqual(policy["mergeGate"]["workflowName"], "PR merge gate")
        self.assertEqual(
            policy["productReleaseGate"]["workflowFile"],
            "release-self-hosted.yml",
        )
        self.assertEqual(
            policy["productReleaseGate"]["validatorCommand"],
            "tools/production_gate.py --mode release",
        )

    def test_release_workflow_is_manual_and_separate(self) -> None:
        policy = self.policy()
        release = self.workflow(policy["productReleaseGate"]["workflowFile"])
        merge = self.workflow(policy["mergeGate"]["workflowFile"])
        self.assertIn("workflow_dispatch:", release)
        self.assertNotIn("pull_request:", release)
        self.assertNotIn("\n  push:", release)
        self.assertIn(policy["productReleaseGate"]["validatorCommand"], release)
        self.assertNotIn("production_gate.py --mode release", merge)
        self.assertNotIn("customer_quality.py", merge)

    def test_merge_workflow_is_unfiltered_and_change_scoped(self) -> None:
        policy = self.policy()
        merge = self.workflow(policy["mergeGate"]["workflowFile"])
        self.assertFalse(pr_merge_gate._trigger_has_path_filter(merge))
        self.assertIn("Resolve changed Python files", merge)
        self.assertIn("Ruff lint changed Python", merge)
        self.assertIn("Ruff format changed Python", merge)

    def test_path_filter_detection_is_scoped_to_pull_request(self) -> None:
        documentation_only = """name: example
on:
  pull_request:
    branches: [main]
jobs:
  test:
    steps:
      - run: echo 'paths: is documentation text'
"""
        filtered = """name: example
on:
  pull_request:
    branches: [main]
    paths:
      - src/**
"""
        self.assertFalse(pr_merge_gate._trigger_has_path_filter(documentation_only))
        self.assertTrue(pr_merge_gate._trigger_has_path_filter(filtered))

    def test_static_merge_gate_contract_passes(self) -> None:
        self.assertFalse((ROOT / ".github/workflows/policy-tests.yml").exists())
        result = pr_merge_gate.validate()
        self.assertTrue(result["mergeEligible"], result["errors"])
        self.assertFalse(result["productReleaseEvaluated"])


if __name__ == "__main__":
    unittest.main()
