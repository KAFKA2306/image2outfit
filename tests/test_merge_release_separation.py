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
    def test_merge_policy_allows_non_release_product_states(self) -> None:
        policy = json.loads(
            (ROOT / "config" / "pr-merge-policy.json").read_text(encoding="utf-8")
        )
        rules = policy["rules"]
        self.assertFalse(rules["productCompletionRequiredForMerge"])
        self.assertFalse(rules["productReleaseEligibilityRequiredForMerge"])
        self.assertFalse(rules["productVisualPassRequiredForMerge"])
        self.assertFalse(rules["productRuntimePassRequiredForMerge"])
        self.assertTrue(rules["mergeDoesNotReleaseProduct"])
        self.assertTrue(rules["affectedProductExecutionMustReachValidBoundary"])
        self.assertIn("WORKING", policy["allowedTrackedProductStatesAtMerge"])
        self.assertIn("REJECTED", policy["allowedTrackedProductStatesAtMerge"])

    def test_release_workflow_is_manual_and_not_a_merge_gate(self) -> None:
        release = (ROOT / ".github" / "workflows" / "release-self-hosted.yml").read_text(
            encoding="utf-8"
        )
        merge = (ROOT / ".github" / "workflows" / "pr-merge-gate.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("workflow_dispatch:", release)
        self.assertNotIn("pull_request:", release)
        self.assertNotIn("\n  push:", release)
        self.assertIn("production_gate.py --mode release", release)
        self.assertNotIn("production_gate.py --mode release", merge)
        self.assertNotIn("customer_quality.py", merge)

    def test_static_merge_gate_contract_passes(self) -> None:
        result = pr_merge_gate.validate()
        self.assertTrue(result["mergeEligible"], result["errors"])
        self.assertFalse(result["productReleaseEvaluated"])


if __name__ == "__main__":
    unittest.main()
