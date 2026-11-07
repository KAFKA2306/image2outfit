from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from image2outfit.execution import (
    MissingTemplateVariableError,
    StageExecutionBinding,
)
from image2outfit.pipeline import (
    PIPELINE_STAGES,
    ExecutionMode,
    new_pipeline_state,
    run_pipeline,
)
from pipeline_stage_adapters import build_registry, load_profile


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
