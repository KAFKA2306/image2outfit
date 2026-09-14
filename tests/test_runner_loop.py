from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.runner_audit import Decision, StopReason
from image2outfit.runner_loop import (
    finalize_ledger,
    new_ledger,
    record_attempt,
    resolve_stop,
    validate_ledger,
)


class RunnerLoopTests(unittest.TestCase):
    def test_keep_advances_current_candidate(self) -> None:
        ledger = new_ledger("a" * 64, "b" * 64)
        ledger = record_attempt(
            ledger,
            request_sha256="a" * 64,
            blocker="fit.penetration_ratio",
            before_candidate_sha256="b" * 64,
            after_candidate_sha256="c" * 64,
            before_audit_sha256="d" * 64,
            after_audit_sha256="e" * 64,
            patch_id="patch-1",
            decision=Decision.KEEP,
            elapsed_minutes=3.0,
        )
        self.assertEqual(ledger["currentCandidateSha256"], "c" * 64)
        validate_ledger(ledger, "a" * 64)

    def test_revert_retains_current_candidate(self) -> None:
        ledger = new_ledger("a" * 64, "b" * 64)
        ledger = record_attempt(
            ledger,
            request_sha256="a" * 64,
            blocker="fit.penetration_ratio",
            before_candidate_sha256="b" * 64,
            after_candidate_sha256="c" * 64,
            before_audit_sha256="d" * 64,
            after_audit_sha256="e" * 64,
            patch_id="patch-1",
            decision=Decision.REVERT,
            elapsed_minutes=3.0,
        )
        self.assertEqual(ledger["currentCandidateSha256"], "b" * 64)

    def test_three_consecutive_reverts_flag_early_stop_candidate(self) -> None:
        ledger = new_ledger("a" * 64, "b" * 64)
        for attempt in range(3):
            ledger = record_attempt(
                ledger,
                request_sha256="a" * 64,
                blocker="fit.penetration_ratio",
                before_candidate_sha256="b" * 64,
                after_candidate_sha256=chr(ord("c") + attempt) * 64,
                before_audit_sha256="f" * 64,
                after_audit_sha256=str(attempt + 1) * 64,
                patch_id=f"patch-{attempt + 1}",
                decision=Decision.REVERT,
                elapsed_minutes=3.0 + attempt,
            )
        self.assertTrue(ledger["earlyStopCandidate"])
        self.assertIsNone(ledger["stopReason"])

    def test_same_blocker_stalls_only_after_attempt_budget(self) -> None:
        ledger = new_ledger("a" * 64, "b" * 64)
        for attempt in range(2):
            ledger = record_attempt(
                ledger,
                request_sha256="a" * 64,
                blocker="fit.penetration_ratio",
                before_candidate_sha256="b" * 64,
                after_candidate_sha256=chr(ord("c") + attempt) * 64,
                before_audit_sha256="f" * 64,
                after_audit_sha256=str(attempt + 1) * 64,
                patch_id=f"patch-{attempt + 1}",
                decision=Decision.REVERT,
                elapsed_minutes=3.0 + attempt,
            )
        request = {
            "maxAttemptsPerBlocker": 2,
            "maxTotalAttempts": 24,
            "maxRunnerMinutes": 120,
        }
        stop = resolve_stop(
            ledger,
            request=request,
            request_sha256="a" * 64,
            blocker="fit.penetration_ratio",
            complete=False,
            failed_hard=False,
            elapsed_minutes=10,
        )
        self.assertEqual(stop, StopReason.STALLED)

    def test_terminal_ledger_rejects_more_attempts(self) -> None:
        ledger = finalize_ledger(
            new_ledger("a" * 64, "b" * 64), StopReason.FAILED_HARD
        )
        with self.assertRaises(ValueError):
            record_attempt(
                ledger,
                request_sha256="a" * 64,
                blocker="geometry.nonfinite_values",
                before_candidate_sha256="b" * 64,
                after_candidate_sha256="c" * 64,
                before_audit_sha256="d" * 64,
                after_audit_sha256="e" * 64,
                patch_id="patch-after-stop",
                decision=Decision.REVERT,
                elapsed_minutes=1.0,
            )


if __name__ == "__main__":
    unittest.main()
