from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "siroino-tuxedo-halter-dress-large"
CONFIG = ROOT / "config" / "products" / PRODUCT_ID


def read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(path)
    return payload


class TuxedoStandardFlowProofTests(unittest.TestCase):
    def test_variant_contract_separates_color_and_size_invalidation(self) -> None:
        variants = read_json(CONFIG / "variants.json")
        self.assertEqual(variants["productId"], PRODUCT_ID)
        self.assertEqual(variants["baseVariant"], "wine-red-black")
        by_kind = {item["kind"]: item for item in variants["variants"]}
        color = by_kind["color"]
        size = by_kind["size"]
        self.assertTrue(color["geometryReuseRequired"])
        self.assertFalse(size["geometryReuseRequired"])
        self.assertEqual(size["geometryVariables"]["bibWidthScale"], 1.1)
        self.assertNotIn("simulate-cloth", color["expectedInvalidation"])
        self.assertIn("simulate-cloth", size["expectedInvalidation"])
        self.assertIn("render-evidence", size["expectedInvalidation"])

    def test_job_uses_existing_build_stage_for_variant_proof(self) -> None:
        job = read_json(CONFIG / "job.json")
        pipeline = job["garmentPipeline"]
        self.assertEqual(
            pipeline["variantSpecPath"],
            f"config/products/{PRODUCT_ID}/variants.json",
        )
        self.assertEqual(
            pipeline["variantProofScript"],
            "tools/run_tuxedo_variant_proof.py",
        )
        self.assertEqual(pipeline["stageContractVersion"], 2)

    def test_material_and_cloth_controls_are_explicit(self) -> None:
        recipe = read_json(CONFIG / "material-recipe.json")
        control = recipe["controlExperiment"]
        self.assertEqual(control["parameter"], "wine.roughnessScale")
        self.assertEqual(control["baseValue"], 1.0)
        self.assertEqual(control["controlValue"], 1.18)
        self.assertEqual(
            control["expectedInvariant"],
            "garment geometry SHA-256",
        )
        construction = read_json(CONFIG / "construction.json")
        cloth = construction["clothSimulation"]
        self.assertEqual(cloth["applicability"], "REQUIRED")
        self.assertIn("start/middle/end", cloth["evidence"])
        self.assertIn("reopen", cloth["evidence"])


if __name__ == "__main__":
    unittest.main()
