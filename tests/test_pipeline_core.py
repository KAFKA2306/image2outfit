from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.pipeline import PIPELINE_STAGES, new_pipeline_state, run_pipeline
from image2outfit.tooling import ToolDescriptor, ToolRegistry


class PipelineCoreTests(unittest.TestCase):
    def test_pipeline_runs_in_canonical_order(self) -> None:
        registry = ToolRegistry()
        seen: list[str] = []
        for stage in PIPELINE_STAGES:
            registry.register(
                stage,
                lambda state, stage_name=stage.value: seen.append(stage_name)
                or {"stage": stage_name},
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
        self.assertEqual(seen, [stage.value for stage in PIPELINE_STAGES])
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(result["completed_stages"], seen)

    def test_pipeline_stops_after_a_failed_stage(self) -> None:
        registry = ToolRegistry()
        called: list[str] = []
        failing = PIPELINE_STAGES[3]
        for stage in PIPELINE_STAGES:
            def handler(state, stage_name=stage.value):
                called.append(stage_name)
                if stage_name == failing.value:
                    raise RuntimeError("expected failure")
                return {"stage": stage_name}

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
