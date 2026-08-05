from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.audit import validate_stage_records
from image2outfit.pipeline import (
    PIPELINE_STAGES,
    ExecutionMode,
    new_pipeline_state,
    resume_pipeline_state,
    run_pipeline,
    validate_pipeline_state,
)
from image2outfit.tooling import ToolDescriptor, ToolRegistry


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
            canonical_stages=[stage.value for stage in PIPELINE_STAGES],
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


if __name__ == "__main__":
    unittest.main()
