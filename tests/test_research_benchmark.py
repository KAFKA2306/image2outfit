from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.research_benchmark import (
    AdoptionStatus,
    BenchmarkMetric,
    BenchmarkRun,
    CANONICAL_RESEARCH_FIXTURES,
    DIRECT_METRIC_IDS,
    compare_benchmark_runs,
)


def run_fixture(
    method_id: str,
    *,
    values: dict[str, float] | None = None,
    reproducible: bool = True,
) -> BenchmarkRun:
    resolved = {metric_id: 1.0 for metric_id in DIRECT_METRIC_IDS}
    if values:
        resolved.update(values)
    return BenchmarkRun(
        fixture_id="loose-pleated-skirt",
        method_id=method_id,
        metrics=tuple(
            BenchmarkMetric(metric_id=metric_id, value=resolved[metric_id])
            for metric_id in DIRECT_METRIC_IDS
        ),
        reproducible=reproducible,
    )


class ResearchBenchmarkTests(unittest.TestCase):
    def test_exactly_three_fixed_fixture_classes_are_canonical(self) -> None:
        self.assertEqual(
            tuple(fixture.fixture_id for fixture in CANONICAL_RESEARCH_FIXTURES),
            (
                "tight-fitted-top",
                "loose-pleated-skirt",
                "layered-outfit-with-trim",
            ),
        )
        self.assertTrue(
            all(
                fixture.required_metric_ids == DIRECT_METRIC_IDS
                for fixture in CANONICAL_RESEARCH_FIXTURES
            )
        )

    def test_accepts_only_non_regressing_reproducible_improvement(self) -> None:
        baseline = run_fixture("internal-pattern-baseline")
        candidate = run_fixture(
            "garmentcode-candidate",
            values={"seam-mismatch-ratio": 0.5},
        )

        decision = compare_benchmark_runs(baseline, candidate)

        self.assertEqual(decision.status, AdoptionStatus.ACCEPTED)
        self.assertEqual(decision.improved_metric_ids, ("seam-mismatch-ratio",))
        self.assertEqual(decision.regressed_metric_ids, ())

    def test_rejects_candidate_when_any_required_metric_regresses(self) -> None:
        baseline = run_fixture("internal-pattern-baseline")
        candidate = run_fixture(
            "garmentcode-candidate",
            values={
                "seam-mismatch-ratio": 0.5,
                "body-penetration-count": 2.0,
            },
        )

        decision = compare_benchmark_runs(baseline, candidate)

        self.assertEqual(decision.status, AdoptionStatus.REJECTED)
        self.assertEqual(decision.regressed_metric_ids, ("body-penetration-count",))

    def test_rejects_non_reproducible_candidate_even_if_metrics_improve(self) -> None:
        decision = compare_benchmark_runs(
            run_fixture("baseline"),
            run_fixture(
                "candidate",
                values={"pattern-geometry-defects": 0.0},
                reproducible=False,
            ),
        )
        self.assertEqual(decision.status, AdoptionStatus.REJECTED)
        self.assertIn("candidate is not reproducible", decision.reasons)

    def test_incomplete_when_required_metric_is_missing(self) -> None:
        baseline = run_fixture("baseline")
        candidate = BenchmarkRun(
            fixture_id="loose-pleated-skirt",
            method_id="candidate",
            metrics=baseline.metrics[:-1],
            reproducible=True,
        )

        decision = compare_benchmark_runs(baseline, candidate)

        self.assertEqual(decision.status, AdoptionStatus.INCOMPLETE)
        self.assertIn("manual-intervention-count", decision.reasons[0])


class ResearchBenchmarkFixtureTests(unittest.TestCase):
    def test_fixture_config_points_to_real_product_jobs(self) -> None:
        config_path = ROOT / "config/pipeline/research-benchmark-fixtures.v1.json"
        payload = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual(payload["issue"], 269)
        self.assertEqual(payload["baselineStatus"], "NOT_MEASURED")
        self.assertEqual(
            tuple(item["fixtureId"] for item in payload["fixtures"]),
            tuple(item.fixture_id for item in CANONICAL_RESEARCH_FIXTURES),
        )
        self.assertEqual(tuple(payload["requiredMetricIds"]), DIRECT_METRIC_IDS)

        for fixture in payload["fixtures"]:
            job_path = ROOT / fixture["jobPath"]
            self.assertTrue(job_path.is_file(), fixture["jobPath"])
            job = json.loads(job_path.read_text(encoding="utf-8"))
            self.assertEqual(job["id"], fixture["productId"])

    def test_fixture_products_are_distinct(self) -> None:
        payload = json.loads(
            (ROOT / "config/pipeline/research-benchmark-fixtures.v1.json").read_text(
                encoding="utf-8"
            )
        )
        product_ids = [item["productId"] for item in payload["fixtures"]]
        self.assertEqual(len(product_ids), len(set(product_ids)))


if __name__ == "__main__":
    unittest.main()
