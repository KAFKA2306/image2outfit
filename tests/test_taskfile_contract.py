from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TaskfileContractTest(unittest.TestCase):
    def test_new_production_modules_are_checked_and_formatted(self) -> None:
        taskfile = (ROOT / "Taskfile.yml").read_text(encoding="utf-8")
        for path in (
            "tools/contract_io.py",
            "tools/workspace_transaction.py",
            "tools/runtime_transaction.py",
            "tools/production_contract.py",
            "tools/candidate_manifest.py",
            "tools/technical_candidate.py",
            "tools/candidate_orchestrator.py",
            "tools/release_orchestrator.py",
            "tools/release_packager.py",
        ):
            self.assertGreaterEqual(taskfile.count(path), 3, path)


if __name__ == "__main__":
    unittest.main()
