from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from release_provenance_gate import evaluate_release_provenance  # noqa: E402


class ReleaseProvenanceGateTests(unittest.TestCase):
    SHA = "a" * 40
    HEAD = "b" * 40

    def merged_pr(self) -> dict:
        return {
            "number": 42,
            "merged_at": "2026-08-15T00:00:00Z",
            "merge_commit_sha": self.SHA,
            "base": {"ref": "main"},
            "head": {"sha": self.HEAD},
        }

    def successful_run(self) -> dict:
        return {
            "id": 123,
            "name": "Release policy tests",
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
            workflow_runs=runs if runs is not None else [self.successful_run()],
        )

    def test_verified_requires_merged_pr_and_exact_head_policy_success(self) -> None:
        result = self.evaluate()
        self.assertEqual(result["state"], "VERIFIED")
        self.assertEqual(result["pr_number"], 42)
        self.assertEqual(result["pr_head_sha"], self.HEAD)
        self.assertEqual(result["policy_run_id"], 123)

    def test_direct_push_is_blocked(self) -> None:
        result = self.evaluate(pulls=[])
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["failure_class"], "MERGED_PR_PROVENANCE_MISSING")

    def test_non_default_branch_is_blocked(self) -> None:
        result = self.evaluate(ref="refs/heads/feat/example")
        self.assertEqual(result["failure_class"], "NON_DEFAULT_BRANCH")

    def test_missing_policy_run_is_blocked(self) -> None:
        result = self.evaluate(runs=[])
        self.assertEqual(result["failure_class"], "RELEASE_POLICY_RUN_MISSING")

    def test_failed_or_pending_policy_run_is_blocked(self) -> None:
        failed = self.successful_run() | {"conclusion": "failure"}
        result = self.evaluate(runs=[failed])
        self.assertEqual(result["failure_class"], "RELEASE_POLICY_NOT_SUCCESSFUL")

        pending = self.successful_run() | {"status": "in_progress", "conclusion": None}
        result = self.evaluate(runs=[pending])
        self.assertEqual(result["failure_class"], "RELEASE_POLICY_NOT_SUCCESSFUL")

    def test_success_for_another_head_does_not_authorize_release(self) -> None:
        other = self.successful_run() | {"head_sha": "c" * 40}
        result = self.evaluate(runs=[other])
        self.assertEqual(result["failure_class"], "RELEASE_POLICY_RUN_MISSING")


if __name__ == "__main__":
    unittest.main()
