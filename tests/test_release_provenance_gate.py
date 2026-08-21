from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from release_provenance_gate import (  # noqa: E402
    evaluate_release_provenance,
    load_merge_gate_contract,
)


class ReleaseProvenanceGateTests(unittest.TestCase):
    SHA = "a" * 40
    HEAD = "b" * 40
    MERGE_GATE_NAME = "PR merge gates"

    def merged_pr(self) -> dict:
        return {
            "number": 42,
            "merged_at": "2026-08-15T00:00:00Z",
            "merge_commit_sha": self.SHA,
            "base": {"ref": "main"},
            "head": {"sha": self.HEAD},
        }

    def successful_merge_gate_run(self) -> dict:
        return {
            "id": 123,
            "name": self.MERGE_GATE_NAME,
            "head_sha": self.HEAD,
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-08-15T00:01:00Z",
            "html_url": "https://github.com/KAFKA2306/image2outfit/actions/runs/123",
        }

    def evaluate(self, *, pulls=None, runs=None, ref="refs/heads/main") -> dict:
        return evaluate_release_provenance(
            release_ref=ref,
            release_sha=self.SHA,
            default_branch="main",
            associated_pulls=pulls if pulls is not None else [self.merged_pr()],
            workflow_runs=(
                runs if runs is not None else [self.successful_merge_gate_run()]
            ),
            merge_gate_name=self.MERGE_GATE_NAME,
        )

    def test_merge_gate_identity_comes_from_merge_policy(self) -> None:
        workflow_file, workflow_name = load_merge_gate_contract()
        self.assertEqual(workflow_file, "policy-tests.yml")
        self.assertEqual(workflow_name, self.MERGE_GATE_NAME)

    def test_verified_requires_merged_pr_and_exact_head_merge_gate_success(self) -> None:
        result = self.evaluate()
        self.assertEqual(result["state"], "VERIFIED")
        self.assertEqual(result["pr_number"], 42)
        self.assertEqual(result["pr_head_sha"], self.HEAD)
        self.assertEqual(result["merge_gate_run_id"], 123)
        self.assertEqual(result["merge_gate_conclusion"], "success")

    def test_direct_push_is_blocked(self) -> None:
        result = self.evaluate(pulls=[])
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["failure_class"], "MERGED_PR_PROVENANCE_MISSING")

    def test_non_default_branch_is_blocked(self) -> None:
        result = self.evaluate(ref="refs/heads/feat/example")
        self.assertEqual(result["failure_class"], "NON_DEFAULT_BRANCH")

    def test_missing_merge_gate_run_is_blocked(self) -> None:
        result = self.evaluate(runs=[])
        self.assertEqual(result["failure_class"], "MERGE_GATE_RUN_MISSING")

    def test_failed_or_pending_merge_gate_run_is_blocked(self) -> None:
        failed = self.successful_merge_gate_run() | {"conclusion": "failure"}
        result = self.evaluate(runs=[failed])
        self.assertEqual(result["failure_class"], "MERGE_GATE_NOT_SUCCESSFUL")

        pending = self.successful_merge_gate_run() | {
            "status": "in_progress",
            "conclusion": None,
        }
        result = self.evaluate(runs=[pending])
        self.assertEqual(result["failure_class"], "MERGE_GATE_NOT_SUCCESSFUL")

    def test_success_for_another_head_does_not_authorize_release(self) -> None:
        other = self.successful_merge_gate_run() | {"head_sha": "c" * 40}
        result = self.evaluate(runs=[other])
        self.assertEqual(result["failure_class"], "MERGE_GATE_RUN_MISSING")

    def test_merge_workflow_does_not_execute_product_release_gate(self) -> None:
        merge_workflow = (ROOT / ".github/workflows/policy-tests.yml").read_text(
            encoding="utf-8"
        )
        release_workflow = (ROOT / ".github/workflows/release-self-hosted.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("name: PR merge gates", merge_workflow)
        self.assertNotIn("production_gate.py --mode release", merge_workflow)
        self.assertIn("production_gate.py --mode release", release_workflow)
        self.assertFalse((ROOT / ".github/workflows/pr-merge-gate.yml").exists())


if __name__ == "__main__":
    unittest.main()
