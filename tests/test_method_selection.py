from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import method_selection  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class MethodSelectionTest(unittest.TestCase):
    def test_all_products_have_one_valid_profile(self) -> None:
        report = method_selection.audit_all(ROOT)
        self.assertTrue(report["passed"], report["errors"])
        product_jobs = list((ROOT / "config" / "products").glob("*/job.json"))
        self.assertEqual(report["productCount"], len(product_jobs))

    def test_loose_layered_requires_runtime_and_motion_evidence(self) -> None:
        job = method_selection.read_json(
            ROOT / "config" / "products" / "siroino-wide-cargo" / "job.json"
        )
        report = method_selection.select(job, ROOT)
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["constructionProfile"], "loose-layered")
        for value in (
            "penetration-report",
            "deformation-benchmark",
            "runtime-performance",
            "motion-review",
        ):
            self.assertIn(value, report["requiredCommercialEvidence"])

    def test_versioned_build_entrypoint_is_rejected(self) -> None:
        job = method_selection.read_json(
            ROOT / "config" / "products" / "siroino-wide-cargo" / "job.json"
        )
        job["buildScript"] = "tools/siroino_wide_cargo_release_refit_v23.py"
        report = method_selection.select(job, ROOT)
        self.assertFalse(report["passed"])
        self.assertTrue(
            any("stable product entrypoint" in value for value in report["errors"])
        )

    def test_missing_commercial_evidence_blocks_release(self) -> None:
        job = method_selection.read_json(
            ROOT / "config" / "products" / "siroino-wide-cargo" / "job.json"
        )
        with tempfile.TemporaryDirectory() as temporary:
            candidate = Path(temporary) / "candidate-manifest.json"
            candidate.write_text(
                json.dumps({"schemaVersion": 2, "jobId": job["id"]}) + "\n",
                encoding="utf-8",
            )
            report = method_selection.validate_commercial_evidence(job, candidate, ROOT)
        self.assertFalse(report["passed"])
        self.assertIn("runtime-performance", report["evidence"])
        self.assertIn("motion-review", report["evidence"])


if __name__ == "__main__":
    unittest.main()
