from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CandidateStateGateTest(unittest.TestCase):
    def test_candidate_orchestrator_checks_manifest_before_commit(self) -> None:
        source = (ROOT / "tools/candidate_orchestrator.py").read_text(
            encoding="utf-8"
        )
        state_check = source.index("contract.product_state_errors")
        candidate_commit = source.index("candidate_tx.commit")
        workspace_commit = source.index("workspace_tx.commit")
        self.assertLess(state_check, candidate_commit)
        self.assertLess(state_check, workspace_commit)


if __name__ == "__main__":
    unittest.main()
