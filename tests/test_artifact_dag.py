from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.artifact_dag import (
    ArtifactKind,
    ArtifactRef,
    GarmentSectionName,
    PipelineArtifactDAG,
)
from image2outfit.pipeline import PipelineStage

HASH_A = "a" * 64
HASH_B = "b" * 64


class ArtifactDAGTests(unittest.TestCase):
    def test_contract_has_exact_canonical_stage_order(self) -> None:
        dag = PipelineArtifactDAG()
        self.assertEqual(
            [contract.stage for contract in dag.contracts], list(PipelineStage)
        )

    def test_material_change_restarts_at_build_blender(self) -> None:
        dag = PipelineArtifactDAG()
        stages = dag.dirty_stages([GarmentSectionName.MATERIALS])
        self.assertEqual(stages[0], PipelineStage.BUILD_BLENDER)
        self.assertEqual(stages[-1], PipelineStage.FINALIZE_CANDIDATE)

    def test_provenance_change_invalidates_entire_pipeline(self) -> None:
        dag = PipelineArtifactDAG()
        stages = dag.dirty_stages([GarmentSectionName.PROVENANCE])
        self.assertEqual(stages, tuple(PipelineStage))

    def test_input_identity_mismatch_is_rejected(self) -> None:
        dag = PipelineArtifactDAG()
        artifact = ArtifactRef(
            kind=ArtifactKind.REFERENCE_SET,
            producer_stage=PipelineStage.INGEST_REFERENCE,
            garment_id="garment-a",
            hypothesis_id="hypothesis-a",
            candidate_id="candidate-a",
            avatar_sha256=HASH_A,
            content_sha256=HASH_B,
            artifact_path="artifacts/reference-set.json",
        )
        with self.assertRaisesRegex(ValueError, "garment_id mismatch"):
            dag.validate_inputs(
                PipelineStage.NORMALIZE_VIEW,
                [artifact],
                garment_id="garment-b",
                hypothesis_id="hypothesis-a",
                candidate_id="candidate-a",
                avatar_sha256=HASH_A,
            )

    def test_execution_plan_is_machine_readable(self) -> None:
        plan = PipelineArtifactDAG().execution_plan(["quality"])
        self.assertEqual(plan["schemaVersion"], 1)
        self.assertEqual(plan["changedSections"], ["quality"])
        self.assertIn("visual-review", plan["stages"])
        self.assertEqual(plan["stages"][-1], "finalize-candidate")

    def test_artifact_file_hash_is_recomputed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact_path = root / "artifacts/reference-set.json"
            artifact_path.parent.mkdir(parents=True)
            artifact_path.write_text("{}\n", encoding="utf-8")
            digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
            artifact = ArtifactRef(
                kind=ArtifactKind.REFERENCE_SET,
                producer_stage=PipelineStage.INGEST_REFERENCE,
                garment_id="garment-a",
                hypothesis_id="hypothesis-a",
                candidate_id="candidate-a",
                avatar_sha256=HASH_A,
                content_sha256=digest,
                artifact_path="artifacts/reference-set.json",
            )
            artifact.verify_content(root)
            artifact_path.write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                artifact.verify_content(root)


if __name__ == "__main__":
    unittest.main()
