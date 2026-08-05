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
from image2outfit.pipeline import PIPELINE_STAGES, new_pipeline_state, run_pipeline
from pipeline_stage_adapters import build_registry, load_profile


class ExecutionBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = load_profile(
            ROOT / "config/pipeline-profiles/garment-reconstruction-v1.json"
        )
        self.state = new_pipeline_state(
            product_id="test-garment",
            target_avatar="SiroinoSotai_PC",
            source_reference="private-reference://sha256/test",
        )

    def test_execute_rejects_missing_required_binding(self) -> None:
        result = run_pipeline(
            self.state,
            build_registry(self.profile, execute=True),
        )
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["current_stage"], PIPELINE_STAGES[0].value)
        self.assertIn("required execution binding is missing", result["errors"][0])

    def test_command_templates_expand_without_a_shell(self) -> None:
        binding = StageExecutionBinding(
            ("python", "tools/run_blender_stage.py", "--job", "{jobPath}")
        )
        self.assertEqual(
            binding.expand({"jobPath": "jobs/example/job.json"}),
            (
                "python",
                "tools/run_blender_stage.py",
                "--job",
                "jobs/example/job.json",
            ),
        )

    def test_command_templates_reject_missing_variables(self) -> None:
        binding = StageExecutionBinding(("python", "{missing}"))
        with self.assertRaises(MissingTemplateVariableError):
            binding.expand({})

    def test_plan_mode_reports_unbound_required_stages(self) -> None:
        result = run_pipeline(self.state, build_registry(self.profile))
        self.assertEqual(result["status"], "COMPLETE")
        for stage in PIPELINE_STAGES:
            output = result["outputs"][stage.value]
            self.assertEqual(output["mode"], "planned")
            self.assertFalse(output["bound"])
            self.assertTrue(output["requiredInExecute"])
