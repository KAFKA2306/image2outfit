from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from image2outfit.audit import (
    validate_stage_records,
    verify_audit_bundle,
    write_audit_bundle,
)
from image2outfit.execution import (
    MissingTemplateVariableError,
    StageExecutionBinding,
)
from image2outfit.pipeline import (
    PIPELINE_STAGES,
    PIPELINE_TRANSITIONS,
    ExecutionMode,
    new_pipeline_state,
    resume_pipeline_state,
    run_pipeline,
    validate_pipeline_state,
)
from image2outfit.tooling import ToolDescriptor, ToolRegistry
from pipeline_stage_adapters import build_registry, load_profile

CANONICAL_STAGES = [stage.value for stage in PIPELINE_STAGES]


def registry_for(
    mode: str,
    called: list[str] | None = None,
    fail_at: str = "",
) -> ToolRegistry:
    registry = ToolRegistry()
    for stage in PIPELINE_STAGES:

        def handler(state, stage_name=stage.value):
            if called is not None:
                called.append(stage_name)
            if stage_name == fail_at:
                raise RuntimeError("expected failure")
            return {"mode": mode, "stage": stage_name}

        registry.register(
            stage,
            handler,
            ToolDescriptor(stage.value, stage.value, f"{stage.value}.json"),
        )
    return registry


class ExecutionBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = load_profile(
            ROOT / "config/pipeline-profiles/garment-reconstruction-v1.json"
        )
        self.plan_state = new_pipeline_state(
            product_id="test-garment",
            target_avatar="SiroinoSotai_PC",
            source_reference="private-reference://sha256/test",
            execution_mode=ExecutionMode.PLAN,
        )
        self.execute_state = new_pipeline_state(
            product_id="test-garment",
            target_avatar="SiroinoSotai_PC",
            source_reference="private-reference://sha256/test",
            execution_mode=ExecutionMode.EXECUTE,
        )

    def test_execute_rejects_missing_required_binding(self) -> None:
        result = run_pipeline(
            self.execute_state,
            build_registry(self.profile, execute=True),
        )
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["current_stage"], PIPELINE_STAGES[0].value)
        self.assertIn("required execution binding is incomplete", result["errors"][0])

    def test_command_templates_expand_without_a_shell(self) -> None:
        binding = StageExecutionBinding(
            ("python", "tools/run_blender_stage.py", "--job", "{jobPath}"),
            ".image2outfit/products/{productId}/reports/build.json",
        )
        variables = {
            "jobPath": "config/products/example/job.json",
            "productId": "example-garment",
        }
        self.assertEqual(
            binding.expand_command(variables),
            (
                "python",
                "tools/run_blender_stage.py",
                "--job",
                "config/products/example/job.json",
            ),
        )
        self.assertEqual(
            binding.expand_result_path(variables),
            ".image2outfit/products/example-garment/reports/build.json",
        )

    def test_command_templates_reject_missing_variables(self) -> None:
        binding = StageExecutionBinding(("python", "{missing}"))
        with self.assertRaises(MissingTemplateVariableError):
            binding.expand({})

    def test_binding_requires_a_result_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "resultPath"):
            build_registry(
                self.profile,
                execute=True,
                bindings={
                    stage.value: {"command": [sys.executable, "-c", "pass"]}
                    for stage in PIPELINE_STAGES
                },
            )

    def test_plan_mode_reports_unbound_required_stages(self) -> None:
        result = run_pipeline(self.plan_state, build_registry(self.profile))
        self.assertEqual(result["status"], "PLANNED")
        for stage in PIPELINE_STAGES:
            output = result["outputs"][stage.value]
            self.assertEqual(output["mode"], "planned")
            self.assertFalse(output["bound"])
            self.assertTrue(output["requiredInExecute"])


class PipelineCoreTests(unittest.TestCase):
    def test_pipeline_transitions_cover_adjacent_stage_pairs(self) -> None:
        self.assertEqual(len(PIPELINE_TRANSITIONS), len(PIPELINE_STAGES) - 1)
        self.assertEqual(
            PIPELINE_TRANSITIONS,
            tuple(zip(PIPELINE_STAGES[:-1], PIPELINE_STAGES[1:], strict=True)),
        )

    def test_plan_runs_in_canonical_order_without_claiming_completion(self) -> None:
        registry = ToolRegistry()
        seen: list[str] = []
        for stage in PIPELINE_STAGES:
            registry.register(
                stage,
                lambda state, stage_name=stage.value: (
                    seen.append(stage_name) or {"mode": "planned", "stage": stage_name}
                ),
                ToolDescriptor(stage.value, stage.value, f"{stage.value}.json"),
            )
        result = run_pipeline(
            new_pipeline_state(
                product_id="test-garment",
                target_avatar="SiroinoSotai_PC",
                source_reference="private-reference://sha256/test",
                execution_mode=ExecutionMode.PLAN,
            ),
            registry,
        )
        self.assertEqual(seen, [stage.value for stage in PIPELINE_STAGES])
        self.assertEqual(result["status"], "PLANNED")
        self.assertEqual(result["completed_stages"], seen)
        self.assertTrue(all(event["status"] == "PLANNED" for event in result["events"]))

    def test_execute_finishes_as_executed_not_product_complete(self) -> None:
        registry = ToolRegistry()
        for stage in PIPELINE_STAGES:
            registry.register(
                stage,
                lambda state, stage_name=stage.value: {
                    "mode": "executed",
                    "stage": stage_name,
                },
                ToolDescriptor(stage.value, stage.value, f"{stage.value}.json"),
            )
        result = run_pipeline(
            new_pipeline_state(
                product_id="test-garment",
                target_avatar="SiroinoSotai_PC",
                source_reference="private-reference://sha256/test",
                execution_mode=ExecutionMode.EXECUTE,
            ),
            registry,
        )
        self.assertEqual(result["status"], "EXECUTED")

    def test_pipeline_stops_after_a_failed_stage(self) -> None:
        registry = ToolRegistry()
        called: list[str] = []
        failing = PIPELINE_STAGES[3]
        for stage in PIPELINE_STAGES:

            def handler(state, stage_name=stage.value):
                called.append(stage_name)
                if stage_name == failing.value:
                    raise RuntimeError("expected failure")
                return {"mode": "planned", "stage": stage_name}

            registry.register(
                stage,
                handler,
                ToolDescriptor(stage.value, stage.value, f"{stage.value}.json"),
            )
        result = run_pipeline(
            new_pipeline_state(
                product_id="test-garment",
                target_avatar="SiroinoSotai_PC",
                source_reference="private-reference://sha256/test",
            ),
            registry,
        )
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(called[-1], failing.value)
        self.assertEqual(len(called), 4)


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


class PipelineResumeTests(unittest.TestCase):
    def test_failed_checkpoint_resumes_at_first_unfinished_stage(self) -> None:
        first_calls: list[str] = []
        failing = PIPELINE_STAGES[3]
        failed = run_pipeline(
            new_pipeline_state(
                product_id="resume-garment",
                target_avatar="SiroinoSotai_PC",
                source_reference="private-reference://sha256/resume",
                run_id="attempt-one",
            ),
            registry_for("planned", first_calls, failing.value),
        )
        resumed = resume_pipeline_state(failed, run_id="attempt-two")
        second_calls: list[str] = []
        result = run_pipeline(resumed, registry_for("planned", second_calls))
        self.assertEqual(second_calls[0], failing.value)
        self.assertNotIn(PIPELINE_STAGES[0].value, second_calls)
        self.assertEqual(result["status"], "PLANNED")
        self.assertEqual(len(result["completed_stages"]), len(PIPELINE_STAGES))
        self.assertEqual(result["resume_count"], 1)
        self.assertEqual(result["parent_run_id"], "attempt-one")
        self.assertEqual(
            [record["status"] for record in result["stage_records"][:3]],
            ["REUSED", "REUSED", "REUSED"],
        )
        validate_stage_records(
            result["stage_records"],
            expected_run_id="attempt-two",
            canonical_stages=CANONICAL_STAGES,
        )

    def test_resume_rejects_noncanonical_completed_prefix(self) -> None:
        state = new_pipeline_state(
            product_id="bad-resume",
            target_avatar="SiroinoSotai_PC",
            source_reference="private-reference://sha256/bad",
        )
        state["completed_stages"] = [PIPELINE_STAGES[1].value]
        state["outputs"] = {PIPELINE_STAGES[1].value: {"mode": "planned"}}
        with self.assertRaisesRegex(ValueError, "canonical pipeline prefix"):
            validate_pipeline_state(state)

    def test_checkpoint_is_written_after_every_attempt(self) -> None:
        checkpoints: list[str] = []
        failing = PIPELINE_STAGES[2]
        result = run_pipeline(
            new_pipeline_state(
                product_id="checkpoint-garment",
                target_avatar="SiroinoSotai_PC",
                source_reference="private-reference://sha256/checkpoint",
            ),
            registry_for("planned", fail_at=failing.value),
            checkpoint=lambda state: checkpoints.append(state["current_stage"]),
        )
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(checkpoints, [stage.value for stage in PIPELINE_STAGES[:3]])

    def test_execution_mode_cannot_change_after_completed_work(self) -> None:
        failed = run_pipeline(
            new_pipeline_state(
                product_id="mode-lock",
                target_avatar="SiroinoSotai_PC",
                source_reference="private-reference://sha256/mode-lock",
            ),
            registry_for("planned", fail_at=PIPELINE_STAGES[1].value),
        )
        with self.assertRaisesRegex(ValueError, "execution_mode cannot change"):
            resume_pipeline_state(failed, execution_mode=ExecutionMode.EXECUTE)


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
