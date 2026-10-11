from __future__ import annotations

import re
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import known_failures  # noqa: E402

TEST_FILES = sorted((ROOT / "tests").glob("test_*.py"))


class _Probe(unittest.TestCase):
    def runTest(self) -> None:  # pragma: no cover - only used for its name
        pass


def _entry(**overrides: object) -> dict:
    entry: dict = {
        "id": "KF-TEST",
        "test": "_Probe.runTest",
        "subject": "subject-a",
        "match": "needle",
        "reason": "fixture",
        "issue": 1,
        "expires": "2026-12-31",
    }
    entry.update(overrides)
    return entry


class KnownFailureRegistryTests(unittest.TestCase):
    def test_registry_entries_are_complete_and_well_formed(self) -> None:
        entries = known_failures.load_entries()
        self.assertTrue(entries)
        for entry in entries:
            with self.subTest(id=entry.get("id")):
                for field in known_failures.REQUIRED_FIELDS:
                    self.assertIn(field, entry)
                self.assertIsInstance(entry["issue"], int)
                date.fromisoformat(entry["expires"])

    def test_registry_entries_are_not_expired(self) -> None:
        today = date.today()
        expired = [
            entry["id"]
            for entry in known_failures.load_entries()
            if date.fromisoformat(entry["expires"]) < today
        ]
        self.assertEqual(
            [],
            expired,
            "expired known failures block again; fix the artifact or renew the entry",
        )

    def test_registry_entries_name_existing_test_methods(self) -> None:
        classes: dict[str, str] = {}
        for path in TEST_FILES:
            for block in path.read_text(encoding="utf-8").split("\nclass ")[1:]:
                name = re.match(r"\w+", block).group(0)
                classes[name] = block
        for entry in known_failures.load_entries():
            class_name, method_name = entry["test"].split(".", 1)
            with self.subTest(id=entry["id"]):
                self.assertIn(class_name, classes)
                self.assertRegex(
                    classes[class_name],
                    rf"\n    def {re.escape(method_name)}\(",
                )


class KnownFailureMatchingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.probe = _Probe()
        self.today = date(2026, 10, 11)

    def test_matching_active_entry_is_found(self) -> None:
        found = known_failures.find(
            self.probe,
            "subject-a",
            "a needle here",
            today=self.today,
            entries=[_entry()],
        )
        self.assertEqual("KF-TEST", found["id"])

    def test_other_subject_or_message_is_not_matched(self) -> None:
        entries = [_entry()]
        self.assertIsNone(
            known_failures.find(
                self.probe, "subject-b", "a needle", today=self.today, entries=entries
            )
        )
        self.assertIsNone(
            known_failures.find(
                self.probe, "subject-a", "other", today=self.today, entries=entries
            )
        )

    def test_expired_entry_is_not_matched(self) -> None:
        self.assertIsNone(
            known_failures.find(
                self.probe,
                "subject-a",
                "a needle",
                today=date(2027, 1, 1),
                entries=[_entry()],
            )
        )

    def test_tolerated_converts_only_registered_failures_to_skips(self) -> None:
        original = known_failures.load_entries
        known_failures.load_entries = lambda path=None: [_entry(match="needle")]
        try:
            with self.assertRaises(unittest.SkipTest):
                with known_failures.tolerated(self.probe, "subject-a"):
                    raise AssertionError("needle missing")
            with self.assertRaises(AssertionError):
                with known_failures.tolerated(self.probe, "subject-a"):
                    raise AssertionError("unrelated failure")
        finally:
            known_failures.load_entries = original


if __name__ == "__main__":
    unittest.main()
