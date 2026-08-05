from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.artifact_bridge import artifact_ref_from_stage_result
from image2outfit.artifact_dag import ArtifactKind
from image2outfit.pipeline import PipelineStage

HASH_A = "a" * 64
HASH_B = "b" * 64


class StageResultCompatibilityTests(unittest.TestCase):
    def test_stage_result_v1_converts_without_schema_migration(self) -> None:
        ref = artifact_ref_from_stage_result(
            {
                "schemaVersion": 1,
                "stage": "ingest-reference",
                "productId": "garment-a",
                "status": "PASS",
                "evidence": [
                    {
                        "path": "artifacts/reference-set.json",
                        "sha256": HASH_B,
                    }
                ],
            },
            kind=ArtifactKind.REFERENCE_SET,
            hypothesis_id="hypothesis-a",
            candidate_id="candidate-a",
            avatar_sha256=HASH_A,
        )
        self.assertEqual(ref.producer_stage, PipelineStage.INGEST_REFERENCE)
        self.assertEqual(ref.content_sha256, HASH_B)


if __name__ == "__main__":
    unittest.main()
