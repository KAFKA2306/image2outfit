from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import candidate_manifest  # noqa: E402


class ShapeKeyCandidateGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.artifact = self.root / ".image2outfit/products/test/reports"
        self.artifact.mkdir(parents=True)
        self.job = {
            "id": "test",
            "artifactDir": ".image2outfit/products/test/reports",
        }
        self.root_patch = patch.object(candidate_manifest, "ROOT", self.root)
        self.root_patch.start()

    def tearDown(self) -> None:
        self.root_patch.stop()
        self.temporary.cleanup()

    def write_report(self, value: dict[str, object]) -> None:
        (self.artifact / candidate_manifest.SHAPE_KEY_REPORT).write_text(
            json.dumps(value) + "\n",
            encoding="utf-8",
        )

    def write_construction(self, applicability: str) -> None:
        path = self.root / "config/products/test/construction.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "productId": "test",
                    "profile": "fitted",
                    "shapeKeyPostprocess": {
                        "provider": "maxwilso-smooth-shape-keys",
                        "applicability": applicability,
                        "reason": "test",
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def test_missing_report_blocks(self) -> None:
        result = candidate_manifest._shape_key_gate(self.job)
        self.assertFalse(result["passed"])
        self.assertIn("missing", result["error"])

    def test_blocked_report_blocks(self) -> None:
        self.write_report(
            {
                "provider": "maxwilso-smooth-shape-keys",
                "status": "BLOCKED",
                "passed": False,
                "errors": ["operator unavailable"],
            }
        )
        result = candidate_manifest._shape_key_gate(self.job)
        self.assertFalse(result["passed"])
        self.assertEqual("BLOCKED", result["status"])

    def test_not_applicable_report_passes_when_not_required(self) -> None:
        self.write_report(
            {
                "provider": "maxwilso-smooth-shape-keys",
                "status": "NOT_APPLICABLE",
                "passed": True,
                "errors": [],
                "metrics": {"targetCount": 0},
            }
        )
        result = candidate_manifest._shape_key_gate(self.job)
        self.assertTrue(result["passed"])
        self.assertEqual("NOT_APPLICABLE", result["status"])

    def test_not_applicable_report_blocks_when_required(self) -> None:
        self.write_construction("REQUIRED")
        self.write_report(
            {
                "provider": "maxwilso-smooth-shape-keys",
                "status": "NOT_APPLICABLE",
                "passed": True,
                "errors": [],
                "metrics": {"targetCount": 0},
            }
        )
        result = candidate_manifest._shape_key_gate(self.job)
        self.assertFalse(result["passed"])
        self.assertIn("required Shape Keys", result["error"])

    def test_unexpected_provider_blocks(self) -> None:
        self.write_report(
            {
                "provider": "unknown-addon",
                "status": "APPLIED",
                "passed": True,
                "errors": [],
            }
        )
        result = candidate_manifest._shape_key_gate(self.job)
        self.assertFalse(result["passed"])
        self.assertIn("provider", result["error"])


if __name__ == "__main__":
    unittest.main()
