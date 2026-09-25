from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from image2outfit import dbt_evidence


class DbtEvidenceTests(unittest.TestCase):
    def test_extracts_only_from_canonical_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            product_id = "test-garment"
            config = root / "config" / "products" / product_id
            manifest_dir = root / "Assets" / "GenWorks" / product_id
            config.mkdir(parents=True)
            manifest_dir.mkdir(parents=True)

            job = {
                "id": product_id,
                "productName": "Test Garment",
                "productManifestPath": (
                    f"Assets/GenWorks/{product_id}/ProductManifest.json"
                ),
            }
            construction = {"schemaVersion": 1, "productId": product_id}
            manifest = {
                "schemaVersion": 1,
                "productId": product_id,
                "status": "WORKING",
                "generatedAt": "2026-09-26T00:00:00Z",
                "completionGates": {"blender": "PASS"},
                "technicalGates": {"unityImport": "UNVERIFIED"},
            }
            (config / "job.json").write_text(json.dumps(job), encoding="utf-8")
            (config / "construction.json").write_text(
                json.dumps(construction), encoding="utf-8"
            )
            (manifest_dir / "ProductManifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )

            output = root / ".image2outfit" / "dbt" / "sources"
            report = dbt_evidence.extract(root, output)

            self.assertEqual(report["productCount"], 1)
            self.assertEqual(report["runCount"], 1)
            self.assertEqual(report["gateCount"], 2)

            products = [
                json.loads(line)
                for line in (output / "products.jsonl").read_text().splitlines()
            ]
            self.assertEqual(products[0]["product_id"], product_id)
            self.assertTrue(products[0]["construction_exists"])
            self.assertTrue(products[0]["manifest_exists"])

            runs = [
                json.loads(line)
                for line in (output / "runs.jsonl").read_text().splitlines()
            ]
            self.assertTrue(runs[0]["run_id"].startswith(product_id + ":"))

    def test_missing_canonical_files_remain_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            product_id = "incomplete-garment"
            config = root / "config" / "products" / product_id
            config.mkdir(parents=True)
            job = {
                "id": product_id,
                "productManifestPath": (
                    f"Assets/GenWorks/{product_id}/ProductManifest.json"
                ),
            }
            (config / "job.json").write_text(json.dumps(job), encoding="utf-8")

            output = root / ".image2outfit" / "dbt" / "sources"
            dbt_evidence.extract(root, output)
            row = json.loads((output / "products.jsonl").read_text().splitlines()[0])

            self.assertFalse(row["construction_exists"])
            self.assertFalse(row["manifest_exists"])
            self.assertIsNone(row["product_status"])


if __name__ == "__main__":
    unittest.main()
