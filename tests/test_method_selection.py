from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import method_selection  # noqa: E402


def job_for_profile(profile: str) -> dict:
    for construction_path in sorted(
        (ROOT / "config" / "products").glob("*/construction.json")
    ):
        construction = method_selection.read_json(construction_path)
        if construction.get("profile") == profile:
            return method_selection.read_json(construction_path.with_name("job.json"))
    raise AssertionError(f"No product declares construction profile: {profile}")


class MethodSelectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.job = job_for_profile("loose-layered")

    def test_loose_layered_requires_runtime_and_motion_evidence(self) -> None:
        report = method_selection.select(self.job, ROOT)
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["constructionProfile"], "loose-layered")
        for value in (
            "penetration-report",
            "deformation-benchmark",
            "runtime-performance",
            "motion-review",
        ):
            with self.subTest(evidence=value):
                self.assertIn(value, report["requiredCommercialEvidence"])

    def test_versioned_build_entrypoint_is_rejected(self) -> None:
        job = dict(self.job)
        job["buildScript"] = "tools/product_release_refit_v23.py"
        report = method_selection.select(job, ROOT)
        self.assertFalse(report["passed"])
        self.assertTrue(
            any("stable product entrypoint" in value for value in report["errors"])
        )

    def test_missing_commercial_evidence_blocks_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = Path(temporary) / "candidate-manifest.json"
            candidate.write_text(
                json.dumps({"schemaVersion": 2, "jobId": self.job["id"]}) + "\n",
                encoding="utf-8",
            )
            report = method_selection.validate_commercial_evidence(
                self.job,
                candidate,
                ROOT,
            )
        self.assertFalse(report["passed"])
        for evidence in ("runtime-performance", "motion-review"):
            with self.subTest(evidence=evidence):
                self.assertIn(evidence, report["evidence"])


if __name__ == "__main__":
    unittest.main()
