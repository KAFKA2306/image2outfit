from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit import dbt_evidence  # noqa: E402


class DbtEvidenceTests(unittest.TestCase):
    def _write_policy(self, root: Path) -> None:
        config = root / "config"
        config.mkdir(parents=True, exist_ok=True)
        policy = {
            "canonicalGateStates": [
                "PASS",
                "FAIL",
                "PENDING",
                "UNVERIFIED",
                "OUT_OF_SCOPE",
            ],
            "gateStateNormalization": {
                "PASS": "PASS",
                "FAIL": "FAIL",
                "PENDING": "PENDING",
                "UNVERIFIED": "UNVERIFIED",
                "OUT_OF_SCOPE": "OUT_OF_SCOPE",
                "DRY_RUN_PASS": "UNVERIFIED",
                "NOT_RUN": "UNVERIFIED",
            },
        }
        (config / "genworks-handoff-policy.json").write_text(
            json.dumps(policy), encoding="utf-8"
        )

    def test_extracts_only_from_canonical_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write_policy(root)
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
            self.assertEqual(report["unknownGateStateCount"], 0)

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

            gates = [
                json.loads(line)
                for line in (output / "gates.jsonl").read_text().splitlines()
            ]
            by_name = {row["gate_name"]: row for row in gates}
            self.assertEqual(by_name["blender"]["normalized_gate_state"], "PASS")
            self.assertEqual(
                by_name["unityImport"]["normalized_gate_state"], "UNVERIFIED"
            )
            self.assertTrue(by_name["blender"]["gate_state_known"])

    def test_unknown_gate_state_is_preserved_and_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write_policy(root)
            product_id = "unknown-state-garment"
            config = root / "config" / "products" / product_id
            manifest_dir = root / "Assets" / "GenWorks" / product_id
            config.mkdir(parents=True)
            manifest_dir.mkdir(parents=True)
            (config / "job.json").write_text(
                json.dumps(
                    {
                        "id": product_id,
                        "productManifestPath": (
                            f"Assets/GenWorks/{product_id}/ProductManifest.json"
                        ),
                    }
                ),
                encoding="utf-8",
            )
            (config / "construction.json").write_text(
                json.dumps({"productId": product_id}), encoding="utf-8"
            )
            (manifest_dir / "ProductManifest.json").write_text(
                json.dumps(
                    {
                        "productId": product_id,
                        "status": "WORKING",
                        "technicalGates": {"mesh": "MAGIC_PASS"},
                    }
                ),
                encoding="utf-8",
            )

            output = root / ".image2outfit" / "dbt" / "sources"
            report = dbt_evidence.extract(root, output)
            gate = json.loads((output / "gates.jsonl").read_text().splitlines()[0])

            self.assertEqual(report["unknownGateStateCount"], 1)
            self.assertEqual(gate["gate_state"], "MAGIC_PASS")
            self.assertIsNone(gate["normalized_gate_state"])
            self.assertFalse(gate["gate_state_known"])

    def test_missing_canonical_files_remain_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write_policy(root)
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
