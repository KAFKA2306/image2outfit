from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.pipeline import (
    PIPELINE_STAGES,
    PIPELINE_TRANSITIONS,
    ExecutionMode,
    new_pipeline_state,
    run_pipeline,
)
from image2outfit.tooling import ToolDescriptor, ToolRegistry


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
                    seen.append(stage_name)
                    or {"mode": "planned", "stage": stage_name}
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
