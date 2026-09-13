from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.pipeline import ExecutionMode, PipelineStage
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


if __name__ == "__main__":
    unittest.main()
