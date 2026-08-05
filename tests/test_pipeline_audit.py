from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.audit import (
    validate_stage_records,
    verify_audit_bundle,
    write_audit_bundle,
)
from image2outfit.pipeline import PIPELINE_STAGES, new_pipeline_state, run_pipeline
from image2outfit.tooling import ToolDescriptor, ToolRegistry

CANONICAL_STAGES = [stage.value for stage in PIPELINE_STAGES]


class PipelineAuditTests(unittest.TestCase):
    @staticmethod
    def _registry(*, failing_stage: str | None = None) -> ToolRegistry:
        registry = ToolRegistry()
        for stage in PIPELINE_STAGES:

            def handler(state, stage_name=stage.value):
                if stage_name == failing_stage:
                    raise RuntimeError("intentional audit test failure")
                return {
                    "mode": "planned",
                    "stage": stage_name,
                    "productId": state["product_id"],
                }

            registry.register(
                stage,
                handler,
                ToolDescriptor(
                    tool_name=f"test-{stage.value}",
                    purpose=f"test {stage.value}",
                    output_contract=f"pipeline-output/{stage.value}.json",
                ),
            )
        return registry

    @classmethod
    def _result(cls, *, product_id: str, run_id: str):
        return run_pipeline(
            new_pipeline_state(
                product_id=product_id,
                target_avatar="SiroinoSotai_PC",
                source_reference=f"private-reference://sha256/{product_id}",
                run_id=run_id,
            ),
            cls._registry(),
        )

    def test_every_stage_is_recorded_and_persisted(self) -> None:
        result = self._result(
            product_id="audit-garment",
            run_id="audit-run-001",
        )
        records = result["stage_records"]
        self.assertEqual(len(records), len(PIPELINE_STAGES))
        self.assertTrue(all(record["status"] == "PLANNED" for record in records))
        validate_stage_records(
            records,
            expected_run_id="audit-run-001",
            expected_product_id="audit-garment",
            canonical_stages=CANONICAL_STAGES,
        )
        self.assertEqual(
            [record["stage"] for record in records],
            CANONICAL_STAGES,
        )

        with TemporaryDirectory() as temporary:
            audit_root = Path(temporary) / "audit"
            bundle = write_audit_bundle(
                result,
                audit_root=audit_root,
                canonical_stages=CANONICAL_STAGES,
            )
            run_root = Path(bundle["root"])
            manifest = verify_audit_bundle(run_root)
            self.assertEqual(manifest["recordedStageCount"], len(PIPELINE_STAGES))
            self.assertEqual(manifest["finalStatus"], "PLANNED")
            self.assertTrue((run_root / "pipeline-state.json").is_file())
            self.assertTrue((audit_root / "audit-garment" / "latest.json").is_file())

    def test_failed_stage_has_an_auditable_output(self) -> None:
        failing = PIPELINE_STAGES[3]
        result = run_pipeline(
            new_pipeline_state(
                product_id="audit-failure",
                target_avatar="SiroinoSotai_PC",
                source_reference="private-reference://sha256/failure",
                run_id="audit-run-failure",
            ),
            self._registry(failing_stage=failing.value),
        )
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(len(result["stage_records"]), 4)
        self.assertEqual(result["stage_records"][-1]["stage"], failing.value)
        self.assertEqual(result["stage_records"][-1]["status"], "FAILED")
        self.assertEqual(result["outputs"][failing.value]["mode"], "failed")
        validate_stage_records(
            result["stage_records"],
            canonical_stages=CANONICAL_STAGES,
        )

    def test_modified_stage_file_is_rejected(self) -> None:
        result = self._result(
            product_id="audit-tamper",
            run_id="audit-run-tamper",
        )
        with TemporaryDirectory() as temporary:
            bundle = write_audit_bundle(
                result,
                audit_root=Path(temporary) / "audit",
                canonical_stages=CANONICAL_STAGES,
            )
            run_root = Path(bundle["root"])
            first = run_root / "stages" / "01-ingest-reference.json"
            payload = json.loads(first.read_text(encoding="utf-8"))
            payload["status"] = "PASS"
            first.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify_audit_bundle(run_root)

    def test_existing_run_cannot_be_overwritten(self) -> None:
        result = self._result(
            product_id="audit-immutable",
            run_id="audit-run-immutable",
        )
        with TemporaryDirectory() as temporary:
            audit_root = Path(temporary) / "audit"
            write_audit_bundle(
                result,
                audit_root=audit_root,
                canonical_stages=CANONICAL_STAGES,
            )
            with self.assertRaisesRegex(FileExistsError, "immutable"):
                write_audit_bundle(
                    result,
                    audit_root=audit_root,
                    canonical_stages=CANONICAL_STAGES,
                )

    def test_manifest_path_escape_is_rejected(self) -> None:
        result = self._result(
            product_id="audit-path",
            run_id="audit-run-path",
        )
        with TemporaryDirectory() as temporary:
            bundle = write_audit_bundle(
                result,
                audit_root=Path(temporary) / "audit",
                canonical_stages=CANONICAL_STAGES,
            )
            run_root = Path(bundle["root"])
            manifest_path = run_root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["stages"][0]["path"] = "../../outside.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "escapes"):
                verify_audit_bundle(run_root)


if __name__ == "__main__":
    unittest.main()
