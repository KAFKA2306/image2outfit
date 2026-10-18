from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.pipeline import ExecutionMode, PipelineStage
from image2outfit.runtime_artifacts import attach_runtime_artifact_ref
from image2outfit.tooling import ToolDescriptor, ToolRegistry


class RuntimeArtifactBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = ROOT / ".image2outfit" / "runtime-artifact-binding-test.json"
        self.runtime.parent.mkdir(parents=True, exist_ok=True)
        self.runtime.write_text('{"fixture":1}\n', encoding="utf-8")

    def tearDown(self) -> None:
        self.runtime.unlink(missing_ok=True)

    def _state(self) -> dict:
        return {
            "schema_version": 1,
            "run_id": "run-a",
            "parent_run_id": "",
            "product_id": "garment-a",
            "target_avatar": "avatar-a",
            "source_reference": "reference-a",
            "source_fingerprint": "canonical-fixture",
            "profile_id": "profile-a",
            "revision_id": "revision-a",
            "execution_mode": ExecutionMode.EXECUTE.value,
            "completed_stages": [],
            "outputs": {},
        }

    def _descriptor(self, stage: PipelineStage) -> ToolDescriptor:
        return ToolDescriptor(
            tool_name=f"fixture-{stage.value}",
            purpose="runtime artifact contract fixture",
            output_contract=f"pipeline-output/{stage.value}.json",
        )

    def _executed(self, stage: PipelineStage) -> dict:
        path = self.runtime.relative_to(ROOT).as_posix()
        digest = hashlib.sha256(self.runtime.read_bytes()).hexdigest()
        return {
            "mode": "executed",
            "result": {
                "schemaVersion": 1,
                "stage": stage.value,
                "productId": "garment-a",
                "status": "PASS",
                "evidence": [{"path": path, "sha256": digest}],
            },
        }

    def test_missing_producer_ref_prevents_consumer_handler_start(self) -> None:
        registry = ToolRegistry()
        called = False

        def consumer(_state):
            nonlocal called
            called = True
            return self._executed(PipelineStage.NORMALIZE_VIEW)

        registry.register(
            PipelineStage.NORMALIZE_VIEW,
            consumer,
            self._descriptor(PipelineStage.NORMALIZE_VIEW),
        )
        with self.assertRaisesRegex(ValueError, "missing inputs"):
            registry.invoke(PipelineStage.NORMALIZE_VIEW, self._state())
        self.assertFalse(called)

    def test_tampered_producer_bytes_prevent_consumer_handler_start(self) -> None:
        producer_registry = ToolRegistry()
        producer_registry.register(
            PipelineStage.INGEST_REFERENCE,
            lambda _state: self._executed(PipelineStage.INGEST_REFERENCE),
            self._descriptor(PipelineStage.INGEST_REFERENCE),
        )
        state = self._state()
        produced = producer_registry.invoke(PipelineStage.INGEST_REFERENCE, state)
        self.assertEqual("reference-set", produced["artifactRef"]["kind"])
        state["completed_stages"] = [PipelineStage.INGEST_REFERENCE.value]
        state["outputs"] = {PipelineStage.INGEST_REFERENCE.value: produced}

        self.runtime.write_text('{"fixture":2}\n', encoding="utf-8")
        consumer_registry = ToolRegistry()
        called = False

        def consumer(_state):
            nonlocal called
            called = True
            return self._executed(PipelineStage.NORMALIZE_VIEW)

        consumer_registry.register(
            PipelineStage.NORMALIZE_VIEW,
            consumer,
            self._descriptor(PipelineStage.NORMALIZE_VIEW),
        )
        with self.assertRaisesRegex(ValueError, "artifact hash mismatch"):
            consumer_registry.invoke(PipelineStage.NORMALIZE_VIEW, state)
        self.assertFalse(called)

    def _completed(self, state: dict, stage: PipelineStage) -> dict:
        """Produce a stage output through the canonical attach boundary."""
        output = attach_runtime_artifact_ref(stage, state, self._executed(stage))
        state["completed_stages"] = [*state["completed_stages"], stage.value]
        state["outputs"] = {**state["outputs"], stage.value: output}
        return output

    def _consumer_registry(self, stage: PipelineStage) -> tuple[ToolRegistry, list]:
        registry = ToolRegistry()
        calls: list = []

        def consumer(_state):
            calls.append(stage)
            return self._executed(stage)

        registry.register(stage, consumer, self._descriptor(stage))
        return registry, calls

    def test_stale_ref_from_another_run_is_rejected_before_consumer(self) -> None:
        state = self._state()
        self._completed(state, PipelineStage.INGEST_REFERENCE)
        other_run = {**state, "run_id": "run-b"}
        registry, calls = self._consumer_registry(PipelineStage.NORMALIZE_VIEW)
        with self.assertRaisesRegex(ValueError, "candidate_id mismatch"):
            registry.invoke(PipelineStage.NORMALIZE_VIEW, other_run)
        self.assertEqual([], calls)

    def test_chained_resume_reuses_lineage_artifacts_with_verified_hashes(self) -> None:
        state = self._state()
        self._completed(state, PipelineStage.INGEST_REFERENCE)
        first_resume = {
            **state,
            "run_id": "run-b",
            "parent_run_id": "run-a",
            "resume_count": 1,
            "resume_history": [{"resume": 1, "parent_run_id": "run-a"}],
        }
        registry, calls = self._consumer_registry(PipelineStage.NORMALIZE_VIEW)
        registry.invoke(PipelineStage.NORMALIZE_VIEW, first_resume)
        second_resume = {
            **first_resume,
            "run_id": "run-c",
            "parent_run_id": "run-b",
            "resume_count": 2,
            "resume_history": [
                {"resume": 1, "parent_run_id": "run-a"},
                {"resume": 2, "parent_run_id": "run-b"},
            ],
        }
        registry.invoke(PipelineStage.NORMALIZE_VIEW, second_resume)
        self.assertEqual(
            [PipelineStage.NORMALIZE_VIEW, PipelineStage.NORMALIZE_VIEW], calls
        )

    def test_stale_ref_from_another_avatar_is_rejected_before_consumer(self) -> None:
        state = self._state()
        self._completed(state, PipelineStage.INGEST_REFERENCE)
        other_avatar = {**state, "target_avatar": "avatar-b"}
        registry, calls = self._consumer_registry(PipelineStage.NORMALIZE_VIEW)
        with self.assertRaisesRegex(ValueError, "avatar_sha256 mismatch"):
            registry.invoke(PipelineStage.NORMALIZE_VIEW, other_avatar)
        self.assertEqual([], calls)

    def test_wrong_product_ref_is_rejected_before_consumer(self) -> None:
        state = self._state()
        self._completed(state, PipelineStage.INGEST_REFERENCE)
        other_product = {**state, "product_id": "garment-b"}
        registry, calls = self._consumer_registry(PipelineStage.NORMALIZE_VIEW)
        with self.assertRaisesRegex(ValueError, "garment_id mismatch"):
            registry.invoke(PipelineStage.NORMALIZE_VIEW, other_product)
        self.assertEqual([], calls)

    def test_forged_producer_stage_is_rejected_before_consumer(self) -> None:
        state = self._state()
        self._completed(state, PipelineStage.INGEST_REFERENCE)
        ref = state["outputs"][PipelineStage.INGEST_REFERENCE.value]["artifactRef"]
        ref["producer_stage"] = PipelineStage.NORMALIZE_VIEW.value
        registry, calls = self._consumer_registry(PipelineStage.NORMALIZE_VIEW)
        with self.assertRaisesRegex(ValueError, "wrong producer"):
            registry.invoke(PipelineStage.NORMALIZE_VIEW, state)
        self.assertEqual([], calls)

    def test_multi_input_stage_requires_every_consumed_artifact(self) -> None:
        state = self._state()
        self._completed(state, PipelineStage.SKIN_AND_EXPORT)
        registry, calls = self._consumer_registry(PipelineStage.AUDIT_GEOMETRY)
        with self.assertRaisesRegex(ValueError, "missing inputs"):
            registry.invoke(PipelineStage.AUDIT_GEOMETRY, state)
        self.assertEqual([], calls)


if __name__ == "__main__":
    unittest.main()
