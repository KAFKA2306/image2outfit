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


class JobSchemaClosureTest(unittest.TestCase):
    def test_every_tracked_job_uses_only_declared_fields(self) -> None:
        schema = json.loads(
            (ROOT / "config/job.schema.v2.json").read_text(encoding="utf-8")
        )
        self.assertIs(schema["additionalProperties"], False)
        allowed = set(schema["properties"])
        violations = {}
        for path in (ROOT / "config/products").glob("*/job.json"):
            job = json.loads(path.read_text(encoding="utf-8-sig"))
            unknown = sorted(set(job) - allowed)
            if unknown:
                violations[path.parent.name] = unknown
        self.assertEqual({}, violations)


class MethodSelectionTest(unittest.TestCase):
    def test_all_products_have_one_valid_declared_contract(self) -> None:
        report = method_selection.audit_all(ROOT)
        self.assertTrue(report["passed"], report["errors"])
        configured_jobs = list((ROOT / "config" / "products").glob("*/job.json"))
        self.assertEqual(report["productCount"], len(configured_jobs))
        self.assertGreater(report["productCount"], 0)
        self.assertTrue(
            all(
                product.get("selectionMode") == "DECLARED_CONSTRUCTION_CONTRACT"
                for product in report["products"]
            )
        )

    def test_panel_sewn_requires_pattern_and_motion_evidence(self) -> None:
        job = method_selection.read_json(
            ROOT / "config" / "products" / "siroino-wide-cargo" / "job.json"
        )
        report = method_selection.select(job, ROOT)
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["constructionProfile"], "panel-sewn")
        for value in (
            "panel-graph",
            "seam-graph",
            "connectivity-audit",
            "topology-audit",
            "pbr-audit",
            "motion-review",
        ):
            self.assertIn(value, report["requiredCommercialEvidence"])

    def test_wide_cargo_pattern_seams_reference_declared_boundaries(self) -> None:
        path = (
            ROOT
            / "Assets"
            / "GenWorks"
            / "siroino-wide-cargo"
            / "Source"
            / "Patterns"
            / "pattern-spec.json"
        )
        pattern = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(pattern["productId"], "siroino-wide-cargo")
        self.assertEqual(pattern["status"], "WORKING")
        self.assertEqual(pattern["units"], "m")
        self.assertEqual(len(pattern["panels"]), pattern["acceptance"]["panelCount"])
        self.assertEqual(
            len(pattern["seamPairs"]), pattern["acceptance"]["seamPairCount"]
        )

        declared = {
            f"{panel['id']}:{boundary}"
            for panel in pattern["panels"]
            for boundary in panel["boundaries"]
        }
        referenced = {boundary for pair in pattern["seamPairs"] for boundary in pair}
        self.assertTrue(referenced <= declared)
        self.assertTrue(set(pattern["openBoundaries"]) <= declared)
        self.assertTrue(referenced.isdisjoint(pattern["openBoundaries"]))

        baseline = pattern["baselineGeometry"]
        self.assertGreaterEqual(len(baseline["frontDepthProfile"]), 2)
        self.assertGreaterEqual(len(baseline["rearDepthProfile"]), 2)
        self.assertGreaterEqual(len(baseline["legRows"]), 2)
        self.assertGreaterEqual(len(baseline["upperRows"]), 2)
        self.assertNotIn("crotchRise", baseline)

        back_rise = baseline["backRise"]
        front_rise = baseline["frontRise"]
        self.assertGreaterEqual(len(back_rise), 2)
        self.assertEqual(len(front_rise), len(back_rise))
        self.assertEqual(back_rise[-1], front_rise[0])
        self.assertEqual(back_rise[-1][0], 0.0)
        self.assertEqual(len(back_rise) + len(front_rise) - 1, 17)
        self.assertTrue(all(point[0] >= 0.0 for point in back_rise))
        self.assertTrue(all(point[0] <= 0.0 for point in front_rise))
        self.assertTrue(
            all(
                back_rise[index][1] >= back_rise[index + 1][1]
                for index in range(len(back_rise) - 1)
            )
        )
        self.assertTrue(
            all(
                front_rise[index][1] <= front_rise[index + 1][1]
                for index in range(len(front_rise) - 1)
            )
        )

        self.assertIs(
            pattern["acceptance"]["productionGeometryConsumerRequiredBeforeRelease"],
            True,
        )

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
        for value in (
            "panel-graph",
            "seam-graph",
            "connectivity-audit",
            "motion-review",
        ):
            self.assertIn(value, report["evidence"])

    def test_construction_contract_must_bind_its_product(self) -> None:
        job = method_selection.read_json(
            ROOT / "config" / "products" / "siroino-wide-cargo" / "job.json"
        )
        construction_path = (
            ROOT / "config" / "products" / "siroino-wide-cargo" / "construction.json"
        )
        original = construction_path.read_text(encoding="utf-8")
        try:
            construction = json.loads(original)
            construction["productId"] = "other-product"
            construction_path.write_text(
                json.dumps(construction) + "\n", encoding="utf-8"
            )
            report = method_selection.select(job, ROOT)
        finally:
            construction_path.write_text(original, encoding="utf-8")
        self.assertFalse(report["passed"])
        self.assertIn("construction.productId must match job.id", report["errors"])
