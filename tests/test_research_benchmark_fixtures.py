from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.research_benchmark import (
    CANONICAL_RESEARCH_FIXTURES,
    DIRECT_METRIC_IDS,
)


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
