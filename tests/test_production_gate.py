from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

from production_gate_core import DirectoryTransaction  # noqa: E402


class DirectoryTransactionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.target = self.root / "Candidates" / "test-product"
        self.target.mkdir(parents=True)
        (self.target / "marker.txt").write_text("last-good", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_failed_iteration_restores_last_good_directory(self) -> None:
        transaction = DirectoryTransaction(self.target)
        had_original = transaction.begin()
        self.target.mkdir(parents=True)
        (self.target / "marker.txt").write_text("failed-new", encoding="utf-8")
        transaction.rollback(had_original)
        self.assertEqual(
            "last-good", (self.target / "marker.txt").read_text(encoding="utf-8")
        )
        self.assertFalse(transaction.backup.exists())
        self.assertFalse(transaction.journal.exists())

    def test_successful_iteration_commits_new_directory(self) -> None:
        transaction = DirectoryTransaction(self.target)
        had_original = transaction.begin()
        self.target.mkdir(parents=True)
        (self.target / "marker.txt").write_text("new-good", encoding="utf-8")
        transaction.commit(had_original)
        self.assertEqual(
            "new-good", (self.target / "marker.txt").read_text(encoding="utf-8")
        )
        self.assertFalse(transaction.backup.exists())
        self.assertFalse(transaction.journal.exists())

    def test_next_run_recovers_interrupted_protected_state(self) -> None:
        transaction = DirectoryTransaction(self.target)
        transaction.begin()
        recovered = DirectoryTransaction(self.target)
        recovered.recover()
        self.assertEqual(
            "last-good", (self.target / "marker.txt").read_text(encoding="utf-8")
        )
        self.assertFalse(recovered.backup.exists())
        self.assertFalse(recovered.journal.exists())

    def test_next_run_recovers_interrupted_prepared_state(self) -> None:
        transaction = DirectoryTransaction(self.target)
        transaction._write_journal("PREPARED", True)
        recovered = DirectoryTransaction(self.target)
        recovered.recover()
        self.assertEqual(
            "last-good", (self.target / "marker.txt").read_text(encoding="utf-8")
        )
        self.assertFalse(recovered.journal.exists())

    def test_rollback_removes_new_directory_when_no_previous_state_exists(self) -> None:
        empty_target = self.root / "Release" / "new-product"
        transaction = DirectoryTransaction(empty_target)
        had_original = transaction.begin()
        empty_target.mkdir(parents=True)
        (empty_target / "package.zip").write_text("invalid", encoding="utf-8")
        transaction.rollback(had_original)
        self.assertFalse(empty_target.exists())
        self.assertFalse(transaction.backup.exists())
        self.assertFalse(transaction.journal.exists())


if __name__ == "__main__":
    unittest.main()
