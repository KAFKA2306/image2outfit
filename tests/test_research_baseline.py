from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import audit_research_baseline  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT
    / "Assets"
    / "GenWorks"
    / "Shared"
    / "Research"
    / "2026-garment-methods.json"
)


class ResearchBaselineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.path = (
            self.root
            / "Assets"
            / "GenWorks"
            / "Shared"
            / "Research"
            / "2026-garment-methods.json"
        )
        self.path.parent.mkdir(parents=True)
        shutil.copy2(SOURCE, self.path)
        self.now = datetime(2026, 8, 2, 8, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def read(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def write(self, value: dict) -> None:
        self.path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def test_current_primary_source_baseline_passes(self) -> None:
        result = audit_research_baseline.audit(self.root, now=self.now)
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["methodCount"], 9)
        self.assertEqual(
            set(result["requiredCapabilities"]),
            set(result["productionCoverage"]),
        )

    def test_stale_survey_blocks_production(self) -> None:
        baseline = self.read()
        baseline["reviewedAt"] = "2025-01-01T00:00:00Z"
        self.write(baseline)
        result = audit_research_baseline.audit(self.root, now=self.now)
        self.assertFalse(result["passed"])
        self.assertTrue(any("stale" in error for error in result["errors"]))

    def test_non_primary_source_is_rejected(self) -> None:
        baseline = self.read()
        baseline["methods"][0]["officialUrl"] = "https://example.com/paper"
        self.write(baseline)
        result = audit_research_baseline.audit(self.root, now=self.now)
        self.assertFalse(result["passed"])
        self.assertTrue(
            any("primary-source host" in error for error in result["errors"])
        )

    def test_unlicensed_code_reuse_is_rejected(self) -> None:
        baseline = self.read()
        baseline["methods"][0]["codeReuseAllowed"] = True
        self.write(baseline)
        result = audit_research_baseline.audit(self.root, now=self.now)
        self.assertFalse(result["passed"])
        self.assertTrue(any("codeLicense" in error for error in result["errors"]))

    def test_missing_method_coverage_is_rejected(self) -> None:
        baseline = self.read()
        for method in baseline["methods"]:
            if "dynamic-evaluation" in method["capabilities"]:
                method["implementationTrack"] = "WATCH"
        self.write(baseline)
        result = audit_research_baseline.audit(self.root, now=self.now)
        self.assertFalse(result["passed"])
        self.assertTrue(
            any("dynamic-evaluation" in error for error in result["errors"])
        )


if __name__ == "__main__":
    unittest.main()
