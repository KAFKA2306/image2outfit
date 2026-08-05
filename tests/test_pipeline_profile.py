from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from image2outfit.pipeline import PIPELINE_STAGES
from pipeline_stage_adapters import build_registry, load_profile


class PipelineProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = load_profile(
            ROOT / "config/pipeline-profiles/garment-reconstruction-v1.json"
        )

    def test_default_profile_matches_canonical_pipeline(self) -> None:
        registry = build_registry(self.profile)
        self.assertEqual(registry.missing(PIPELINE_STAGES), ())

    def test_every_stage_declares_unique_managed_outputs(self) -> None:
        self.assertEqual(len(self.profile["stages"]), len(PIPELINE_STAGES))
        for item in self.profile["stages"]:
            with self.subTest(stage=item["stage"]):
                outputs = item.get("managedOutputs")
                self.assertIsInstance(outputs, list)
                self.assertTrue(outputs)
                self.assertTrue(
                    all(isinstance(output, str) and output for output in outputs)
                )
                self.assertEqual(len(outputs), len(set(outputs)))

    def test_audit_contract_references_tracked_schemas(self) -> None:
        contract = self.profile.get("auditContract")
        self.assertIsInstance(contract, dict)
        self.assertEqual(contract["hashAlgorithm"], "SHA-256")
        self.assertEqual(contract["chain"], "previousRecordDigest")
        self.assertIn("{productId}", contract["storageRoot"])
        self.assertIn("{runId}", contract["storageRoot"])
        for key in ("recordSchema", "manifestSchema"):
            with self.subTest(key=key):
                path = ROOT / contract[key]
                self.assertTrue(path.is_file(), f"Missing audit schema: {path}")


if __name__ == "__main__":
    unittest.main()
