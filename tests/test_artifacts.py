from __future__ import annotations

import hashlib
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.artifact_bridge import artifact_ref_from_stage_result
from image2outfit.artifact_dag import (
    ArtifactKind,
    ArtifactRef,
    GarmentSectionName,
    PipelineArtifactDAG,
)
from image2outfit.pipeline import PipelineStage
from tools.delete_previous_artifacts import is_previous

HASH_A = "a" * 64
HASH_B = "b" * 64
WHOLE_TREE = re.compile(
    r"^\s*\$\{\{\s*env\.(?:PRODUCT_ROOT|REPORT_DIR|PRODUCT_RUNTIME|"
    r"PRODUCT_AUDIT|CANDIDATE_DIR|RELEASE_DIR)\s*\}\}\s*$",
    re.MULTILINE,
)


def upload_blocks(text: str) -> list[str]:
    return re.findall(
        r"uses:\s*actions/upload-artifact@[^\n]+(?P<body>.*?)(?=\n\s*-\s+(?:name:|uses:|run:)|\Z)",
        text,
        flags=re.DOTALL,
    )


def manages_latest_artifact(text: str) -> bool:
    return (
        "tools/delete_previous_artifacts.py" in text
        or "github.rest.actions.deleteArtifact" in text
    )


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


class ArtifactStoragePolicyTests(unittest.TestCase):
    def test_latest_only_artifact_workflows_keep_minimal_output(self) -> None:
        checked = 0
        for workflow in sorted(WORKFLOWS.glob("*.y*ml")):
            text = workflow.read_text(encoding="utf-8")
            blocks = upload_blocks(text)
            if not blocks or not manages_latest_artifact(text):
                continue
            checked += len(blocks)
            self.assertIn("actions: write", text, workflow)
            for block in blocks:
                self.assertRegex(block, r"retention-days:\s*1(?:\s|$)", workflow)
                self.assertIn("overwrite: true", block, workflow)
                self.assertNotRegex(
                    block,
                    r"name:[^\n]*(?:github\.run_id|github\.run_number|github\.run_attempt)",
                    workflow,
                )
                self.assertIsNone(WHOLE_TREE.search(block), workflow)
                self.assertNotIn(".png", block.lower(), workflow)
                self.assertNotIn(".blend1", block.lower(), workflow)
                self.assertNotIn(".blend2", block.lower(), workflow)
        self.assertGreater(checked, 0)


class ArtifactReplacementTests(unittest.TestCase):
    def test_current_name_matches(self) -> None:
        self.assertTrue(
            is_previous("image2outfit-hosted-demo", "image2outfit-hosted-demo")
        )

    def test_legacy_run_suffix_matches(self) -> None:
        self.assertTrue(
            is_previous(
                "image2outfit-hosted-demo-31778430459",
                "image2outfit-hosted-demo",
            )
        )

    def test_other_logical_output_does_not_match(self) -> None:
        self.assertFalse(
            is_previous(
                "image2outfit-hosted-other-31778430459",
                "image2outfit-hosted-demo",
            )
        )

    def test_non_run_suffix_does_not_match(self) -> None:
        self.assertFalse(
            is_previous(
                "image2outfit-hosted-demo-preview",
                "image2outfit-hosted-demo",
            )
        )
