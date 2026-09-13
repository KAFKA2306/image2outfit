from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.pipeline import (
    PIPELINE_STAGES,
    new_pipeline_state,
    resume_pipeline_state,
    run_langchain,
    run_langgraph,
    run_pipeline,
    validate_pipeline_state,
)
from image2outfit.tooling import ToolDescriptor, ToolRegistry


class StopAfterCheckpoint(RuntimeError):
    pass


def registry_for(called: list[str], fail_at: str = "") -> ToolRegistry:
    registry = ToolRegistry()
    for stage in PIPELINE_STAGES:

        def handler(state, stage_name=stage.value):
            called.append(stage_name)
            if stage_name == fail_at:
                raise RuntimeError("controlled stage failure")
            return {"mode": "planned", "stage": stage_name}

        registry.register(
            stage,
            handler,
            ToolDescriptor(stage.value, stage.value, f"{stage.value}.json"),
        )
    return registry


def engine_runners():
    runners = [("deterministic", run_pipeline)]
    if importlib.util.find_spec("langchain_core") is not None:
        runners.append(("langchain", run_langchain))
    if importlib.util.find_spec("langgraph") is not None:
        runners.append(("langgraph", run_langgraph))
    return runners


def state_for():
    return new_pipeline_state(
        product_id="checkpoint-parity",
        target_avatar="SiroinoSotai_PC",
        source_reference="private-reference://sha256/checkpoint-parity",
        run_id="checkpoint-parity-run",
    )


def semantic_checkpoint(state):
    return {
        "run_id": state["run_id"],
        "product_id": state["product_id"],
        "completed_stages": list(state["completed_stages"]),
        "status": state["status"],
        "current_stage": state["current_stage"],
        "outputs": copy.deepcopy(state["outputs"]),
        "stage_records": [
            {
                "stage": record["stage"],
                "status": record["status"],
                "outcomeMode": record["outcomeMode"],
            }
            for record in state["stage_records"]
        ],
    }


class PipelineCheckpointEngineTests(unittest.TestCase):
    def test_stop_after_checkpoint_and_resume_starts_at_next_stage(self) -> None:
        stop_index = 2
        for engine, runner in engine_runners():
            with self.subTest(engine=engine):
                first_calls: list[str] = []
                saved = []

                def checkpoint(state):
                    validate_pipeline_state(state)
                    saved.append(copy.deepcopy(state))
                    if len(state["completed_stages"]) == stop_index + 1:
                        raise StopAfterCheckpoint("controlled interruption")

                with self.assertRaises(StopAfterCheckpoint):
                    runner(
                        state_for(),
                        registry_for(first_calls),
                        checkpoint=checkpoint,
                    )

                interrupted = saved[-1]
                self.assertEqual(
                    interrupted["completed_stages"],
                    [stage.value for stage in PIPELINE_STAGES[: stop_index + 1]],
                )
                self.assertEqual(
                    first_calls,
                    [stage.value for stage in PIPELINE_STAGES[: stop_index + 1]],
                )
                validate_pipeline_state(interrupted)

                resumed = resume_pipeline_state(
                    interrupted,
                    run_id=f"{engine}-resumed",
                )
                resumed_calls: list[str] = []
                result = runner(resumed, registry_for(resumed_calls))
                self.assertEqual(
                    resumed_calls[0], PIPELINE_STAGES[stop_index + 1].value
                )
                self.assertNotIn(PIPELINE_STAGES[0].value, resumed_calls)
                self.assertEqual(result["status"], "PLANNED")
                validate_pipeline_state(result)

    def test_failed_stage_is_checkpointed_with_canonical_failed_shape(self) -> None:
        failing = PIPELINE_STAGES[3]
        snapshots = {}
        for engine, runner in engine_runners():
            with self.subTest(engine=engine):
                called: list[str] = []
                saved = []

                def checkpoint(state):
                    validate_pipeline_state(state)
                    saved.append(copy.deepcopy(state))

                result = runner(
                    state_for(),
                    registry_for(called, fail_at=failing.value),
                    checkpoint=checkpoint,
                )
                failed = saved[-1]
                self.assertEqual(result["status"], "FAILED")
                self.assertEqual(failed["status"], "FAILED")
                self.assertEqual(failed["current_stage"], failing.value)
                self.assertEqual(
                    failed["completed_stages"],
                    [stage.value for stage in PIPELINE_STAGES[:3]],
                )
                self.assertEqual(failed["outputs"][failing.value]["mode"], "failed")
                self.assertEqual(failed["stage_records"][-1]["status"], "FAILED")
                self.assertEqual(called[-1], failing.value)
                validate_pipeline_state(failed)
                snapshots[engine] = semantic_checkpoint(failed)

        baseline = snapshots["deterministic"]
        for engine, snapshot in snapshots.items():
            with self.subTest(equivalence=engine):
                self.assertEqual(snapshot, baseline)

    def test_checkpoint_write_failure_is_fail_visible_and_stops_later_stages(self) -> None:
        for engine, runner in engine_runners():
            with self.subTest(engine=engine):
                called: list[str] = []

                def broken_writer(state):
                    validate_pipeline_state(state)
                    raise OSError("checkpoint storage unavailable")

                with self.assertRaisesRegex(OSError, "checkpoint storage unavailable"):
                    runner(
                        state_for(),
                        registry_for(called),
                        checkpoint=broken_writer,
                    )
                self.assertEqual(called, [PIPELINE_STAGES[0].value])

    def test_successful_checkpoint_semantics_are_equivalent(self) -> None:
        snapshots = {}
        for engine, runner in engine_runners():
            called: list[str] = []
            saved = []

            def checkpoint(state):
                validate_pipeline_state(state)
                saved.append(semantic_checkpoint(state))

            result = runner(
                state_for(),
                registry_for(called),
                checkpoint=checkpoint,
            )
            self.assertEqual(result["status"], "PLANNED")
            self.assertEqual(len(saved), len(PIPELINE_STAGES))
            snapshots[engine] = saved

        baseline = snapshots["deterministic"]
        for engine, snapshot in snapshots.items():
            with self.subTest(engine=engine):
                self.assertEqual(snapshot, baseline)


if __name__ == "__main__":
    unittest.main()
