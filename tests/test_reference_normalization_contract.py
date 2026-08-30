from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from image2outfit.execution import StageResultRequirement, validate_stage_result


class ReferenceNormalizationContractTests(unittest.TestCase):
    def requirement(self) -> StageResultRequirement:
        profile = json.loads(
            (ROOT / "config/pipeline-profiles/garment-reconstruction-v1.json").read_text(
                encoding="utf-8"
            )
        )
        stage = next(
            item for item in profile["stages"] if item["stage"] == "normalize-view"
        )
        return StageResultRequirement(
            minimum_evidence_count=stage["minimumEvidenceCount"],
            required_fields=stage["requiredResultFields"],
        )

    def base_result(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "stage": "normalize-view",
            "productId": "garment",
            "status": "PASS",
            "evidence": [{"path": "normalized.png", "sha256": "a" * 64}],
        }

    def test_synthetic_style_result_without_source_verification_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "sourceBytesVerified"):
            validate_stage_result(
                self.base_result(),
                expected_stage="normalize-view",
                expected_product_id="garment",
                requirement=self.requirement(),
            )

    def test_verified_private_source_result_satisfies_contract(self) -> None:
        payload = self.base_result()
        payload.update(
            {
                "sourceBytesVerified": True,
                "normalizationMethod": "crop-from-private-source",
            }
        )
        validated = validate_stage_result(
            payload,
            expected_stage="normalize-view",
            expected_product_id="garment",
            requirement=self.requirement(),
        )
        self.assertTrue(validated["sourceBytesVerified"])


if __name__ == "__main__":
    unittest.main()
