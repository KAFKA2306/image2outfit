from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WorkspaceGateOrderTest(unittest.TestCase):
    def test_workspace_snapshot_wraps_generation(self) -> None:
        source = (ROOT / "tools/candidate_orchestrator.py").read_text(
            encoding="utf-8"
        )
        begin = source.index("workspace_tx.begin")
        build = source.index("legacy.run_candidate")
        rollback = source.index("workspace_tx.rollback")
        self.assertLess(begin, build)
        self.assertLess(build, rollback)


if __name__ == "__main__":
    unittest.main()
