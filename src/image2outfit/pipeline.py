"""Deterministic, checkpointable stage pipeline with auditable adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Any, TypedDict
from uuid import uuid4

from .audit import make_stage_record, utc_now
from .tooling import ToolRegistry


class PipelineStage(StrEnum):
    INGEST_REFERENCE = "ingest-reference"
    NORMALIZE_VIEW = "normalize-view"
    DECOMPOSE_GARMENT = "decompose-garment"
    DRAFT_PATTERNS = "draft-patterns"
    INFER_STITCHES = "infer-stitches"
    INITIALIZE_3D = "initialize-3d"
    BUILD_BLENDER = "build-blender"
    SIMULATE_CLOTH = "simulate-cloth"
    SKIN_AND_EXPORT = "skin-and-export"
    RENDER_EVIDENCE = "render-evidence"
    AUDIT_GEOMETRY = "audit-geometry"
    VISUAL_REVIEW = "visual-review"
    FINALIZE_CANDIDATE = "finalize-candidate"


class ExecutionMode(StrEnum):
    PLAN = "plan"
    EXECUTE = "execute"


PIPELINE_STAGES = tuple(PipelineStage)
PIPELINE_TRANSITIONS = tuple(
    zip(PIPELINE_STAGES[:-1], PIPELINE_STAGES[1:], strict=True)
)


class PipelineState(TypedDict, total=False):
    schema_version: int
    run_id: str
    parent_run_id: str
    product_id: str
    target_avatar: str
    source_reference: str
    profile_id: str
    revision_id: str
    execution_mode: str
    status: str
    current_stage: str
    completed_stages: list[str]
    events: list[dict[str, Any]]
    errors: list[str]
    outputs: dict[str, Any]
    stage_records: list[dict[str, Any]]
    resume_count: int
    resume_history: list[dict[str, Any]]


CheckpointCallback = Callable[[PipelineState], None]


def new_pipeline_state(
    *,
    product_id: str,
    target_avatar: str,
    source_reference: str,
    profile_id: str = "garment-reconstruction-v1",
    revision_id: str = "",
    execution_mode: ExecutionMode | str = ExecutionMode.PLAN,
    run_id: str | None = None,
) -> PipelineState:
    if not product_id or not target_avatar or not source_reference:
        raise ValueError("product_id, target_avatar, and source_reference are required")
    mode = ExecutionMode(execution_mode)
    return {
        "schema_version": 1,
        "run_id": run_id or uuid4().hex,
        "parent_run_id": "",
        "product_id": product_id,
        "target_avatar": target_avatar,
        "source_reference": source_reference,
        "profile_id": profile_id,
        "revision_id": revision_id,
        "execution_mode": mode.value,
        "status": "READY",
        "current_stage": "",
        "completed_stages": [],
        "events": [],
        "errors": [],
        "outputs": {},
        "stage_records": [],
        "resume_count": 0,
        "resume_history": [],
    }


def _string_list(value: object, *, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"pipeline state {label} must be a string list")
    return list(value)


def validate_pipeline_state(state: Mapping[str, Any]) -> tuple[PipelineStage, ...]:
    """Validate identity and prove completed stages form one canonical prefix."""
    if state.get("schema_version") != 1:
        raise ValueError("pipeline state schema_version must be 1")
    for field in (
        "run_id",
        "product_id",
        "target_avatar",
        "source_reference",
        "profile_id",
    ):
        if not isinstance(state.get(field), str) or not state[field]:
            raise ValueError(f"pipeline state {field} is required")
    if not isinstance(state.get("revision_id", ""), str):
        raise ValueError("pipeline state revision_id must be a string")
    ExecutionMode(state.get("execution_mode", ExecutionMode.PLAN.value))

    completed_names = _string_list(
        state.get("completed_stages", []), label="completed_stages"
    )
    canonical_names = [stage.value for stage in PIPELINE_STAGES]
    if completed_names != canonical_names[: len(completed_names)]:
        raise ValueError("completed_stages must be a canonical pipeline prefix")

    outputs = state.get("outputs", {})
    if not isinstance(outputs, Mapping):
        raise ValueError("pipeline state outputs must be an object")
    missing_outputs = [name for name in completed_names if name not in outputs]
    if missing_outputs:
        raise ValueError(
            "completed stages are missing auditable outputs: "
            + ", ".join(missing_outputs)
        )

    records = state.get("stage_records", [])
    if not isinstance(records, list):
        raise ValueError("pipeline state stage_records must be a list")
    if records:
        record_stages = [record.get("stage") for record in records]
        allowed = completed_names
        if state.get("status") == "FAILED" and len(records) == len(completed_names) + 1:
            allowed = [*completed_names, canonical_names[len(completed_names)]]
        if record_stages != allowed:
            raise ValueError(
                "stage_records do not match the completed canonical prefix"
            )
    return tuple(PipelineStage(name) for name in completed_names)


def next_pipeline_stage(state: Mapping[str, Any]) -> PipelineStage | None:
    completed = validate_pipeline_state(state)
    return (
        PIPELINE_STAGES[len(completed)]
        if len(completed) < len(PIPELINE_STAGES)
        else None
    )


def resume_pipeline_state(
    state: PipelineState,
    *,
    execution_mode: ExecutionMode | str | None = None,
    run_id: str | None = None,
) -> PipelineState:
    """Start a new immutable audit run at the first unfinished stage."""
    current = dict(state)
    completed = validate_pipeline_state(current)
    previous_mode = ExecutionMode(
        current.get("execution_mode", ExecutionMode.PLAN.value)
    )
    requested_mode = (
        previous_mode if execution_mode is None else ExecutionMode(execution_mode)
    )
    if completed and requested_mode is not previous_mode:
        raise ValueError("execution_mode cannot change after a stage has completed")

    following = (
        PIPELINE_STAGES[len(completed)]
        if len(completed) < len(PIPELINE_STAGES)
        else None
    )
    if following is None:
        return current

    previous_run = str(current["run_id"])
    new_run = run_id or uuid4().hex
    if new_run == previous_run:
        raise ValueError("a resumed run must use a new run_id")
    count = int(current.get("resume_count", 0)) + 1
    history = list(current.get("resume_history", []))
    history.append(
        {
            "resume": count,
            "parent_run_id": previous_run,
            "previous_status": str(current.get("status", "")),
            "next_stage": following.value,
            "completed_stage_count": len(completed),
            "preserved_error_count": len(current.get("errors", [])),
        }
    )
    current.pop("audit", None)
    return {
        **current,
        "run_id": new_run,
        "parent_run_id": previous_run,
        "execution_mode": requested_mode.value,
        "status": "READY",
        "current_stage": following.value,
        "stage_records": [],
        "resume_count": count,
        "resume_history": history,
    }


def _stage_input_snapshot(
    state: PipelineState,
    stage: PipelineStage,
) -> dict[str, Any]:
    records = state.get("stage_records", [])
    previous_digest = records[-1]["recordDigest"] if records else "0" * 64
    return {
        "schemaVersion": state.get("schema_version"),
        "runId": state.get("run_id"),
        "parentRunId": state.get("parent_run_id", ""),
        "productId": state.get("product_id"),
        "targetAvatar": state.get("target_avatar"),
        "sourceReference": state.get("source_reference"),
        "profileId": state.get("profile_id"),
        "revisionId": state.get("revision_id", ""),
        "executionMode": state.get("execution_mode"),
        "stage": stage.value,
        "completedStages": list(state.get("completed_stages", [])),
        "previousRecordDigest": previous_digest,
    }


def _rebuild_reused_prefix(
    state: PipelineState,
    registry: ToolRegistry,
) -> PipelineState:
    """Re-record reused outputs under the resumed run's immutable hash chain."""
    if state.get("stage_records"):
        return state
    completed = list(state.get("completed_stages", []))
    if not completed:
        return state
    current = dict(state)
    current["completed_stages"] = []
    records: list[dict[str, Any]] = []
    for stage_name in completed:
        stage = PipelineStage(stage_name)
        descriptor = registry.descriptor(stage)
        output = dict(state["outputs"][stage_name])
        started = utc_now()
        previous = records[-1]["recordDigest"] if records else "0" * 64
        snapshot = _stage_input_snapshot({**current, "stage_records": records}, stage)
        record = make_stage_record(
            run_id=str(state["run_id"]),
            product_id=str(state["product_id"]),
            sequence=len(records) + 1,
            stage=stage.value,
            requested_mode=str(state["execution_mode"]),
            outcome_mode=str(output.get("mode", "reused")),
            status="REUSED",
            tool_name=descriptor.tool_name,
            purpose=descriptor.purpose,
            output_contract=descriptor.output_contract,
            input_snapshot=snapshot,
            output=output,
            previous_record_digest=previous,
            started_at=started,
            finished_at=utc_now(),
        )
        records.append(record)
        current["completed_stages"] = [
            *current.get("completed_stages", []),
            stage_name,
        ]
    return {**state, "stage_records": records}


def _execute_stage(
    state: PipelineState,
    stage: PipelineStage,
    registry: ToolRegistry,
) -> PipelineState:
    if state.get("status") == "FAILED":
        return state
    completed_names = list(state.get("completed_stages", []))
    if stage.value in completed_names:
        return state

    expected_index = len(completed_names)
    descriptor = registry.descriptor(stage)
    mode = ExecutionMode(state.get("execution_mode", ExecutionMode.PLAN.value))
    records = list(state.get("stage_records", []))
    previous_digest = records[-1]["recordDigest"] if records else "0" * 64
    input_snapshot = _stage_input_snapshot(state, stage)
    started_at = utc_now()
    try:
        if (
            expected_index >= len(PIPELINE_STAGES)
            or PIPELINE_STAGES[expected_index] is not stage
        ):
            expected = (
                PIPELINE_STAGES[expected_index].value
                if expected_index < len(PIPELINE_STAGES)
                else "<end>"
            )
            raise ValueError(
                f"stage {stage.value!r} is out of order; expected {expected!r}"
            )
        update = registry.invoke(stage, state)
        actual_mode = update.get("mode")
        expected_mode = "planned" if mode is ExecutionMode.PLAN else "executed"
        if actual_mode != expected_mode:
            raise ValueError(
                f"stage {stage.value!r} returned mode {actual_mode!r}; "
                f"expected {expected_mode!r}"
            )
    except Exception as exc:  # noqa: BLE001 - stage boundary records exact failure
        error = f"{stage.value}: {type(exc).__name__}: {exc}"
        failed_output = {
            "mode": "failed",
            "requestedMode": mode.value,
            "stage": stage.value,
            "errorType": type(exc).__name__,
            "error": str(exc),
        }
        record = make_stage_record(
            run_id=str(state["run_id"]),
            product_id=str(state["product_id"]),
            sequence=len(records) + 1,
            stage=stage.value,
            requested_mode=mode.value,
            outcome_mode="failed",
            status="FAILED",
            tool_name=descriptor.tool_name,
            purpose=descriptor.purpose,
            output_contract=descriptor.output_contract,
            input_snapshot=input_snapshot,
            output=failed_output,
            previous_record_digest=previous_digest,
            started_at=started_at,
            finished_at=utc_now(),
        )
        errors = [*state.get("errors", []), error]
        events = [
            *state.get("events", []),
            {
                "stage": stage.value,
                "status": "FAILED",
                "error": str(exc),
                "auditRecordDigest": record["recordDigest"],
            },
        ]
        return {
            **state,
            "status": "FAILED",
            "current_stage": stage.value,
            "errors": errors,
            "events": events,
            "outputs": {**state.get("outputs", {}), stage.value: failed_output},
            "stage_records": [*records, record],
        }

    event_status = "PLANNED" if actual_mode == "planned" else "PASS"
    record = make_stage_record(
        run_id=str(state["run_id"]),
        product_id=str(state["product_id"]),
        sequence=len(records) + 1,
        stage=stage.value,
        requested_mode=mode.value,
        outcome_mode=str(actual_mode),
        status=event_status,
        tool_name=descriptor.tool_name,
        purpose=descriptor.purpose,
        output_contract=descriptor.output_contract,
        input_snapshot=input_snapshot,
        output=update,
        previous_record_digest=previous_digest,
        started_at=started_at,
        finished_at=utc_now(),
    )
    outputs = {**state.get("outputs", {}), stage.value: update}
    completed = [*completed_names, stage.value]
    events = [
        *state.get("events", []),
        {
            "stage": stage.value,
            "status": event_status,
            "tool": descriptor.tool_name,
            "auditRecordDigest": record["recordDigest"],
        },
    ]
    if stage is PIPELINE_STAGES[-1]:
        status = "PLANNED" if actual_mode == "planned" else "EXECUTED"
    else:
        status = "PLANNING" if actual_mode == "planned" else "RUNNING"
    return {
        **state,
        "status": status,
        "current_stage": stage.value,
        "completed_stages": completed,
        "events": events,
        "outputs": outputs,
        "stage_records": [*records, record],
    }


def run_pipeline(
    state: PipelineState,
    registry: ToolRegistry,
    *,
    checkpoint: CheckpointCallback | None = None,
) -> PipelineState:
    missing = registry.missing(PIPELINE_STAGES)
    if missing:
        raise ValueError(f"pipeline registry is incomplete: {missing}")
    current = dict(state)
    completed = validate_pipeline_state(current)
    current = _rebuild_reused_prefix(current, registry)
    for stage in PIPELINE_STAGES[len(completed) :]:
        current = _execute_stage(current, stage, registry)
        if checkpoint is not None:
            checkpoint(current)
        if current.get("status") == "FAILED":
            break
    return current


def build_langchain(registry: ToolRegistry):
    """Build the same canonical stage sequence as a LangChain runnable."""
    missing = registry.missing(PIPELINE_STAGES)
    if missing:
        raise ValueError(f"pipeline registry is incomplete: {missing}")
    try:
        from langchain_core.runnables import RunnableLambda
    except ImportError as exc:
        raise RuntimeError(
            "LangChain Core is not installed. Run with langchain-core==1.5.0 or "
            "use the deterministic engine."
        ) from exc

    chain = RunnableLambda(lambda state: _rebuild_reused_prefix(state, registry))
    for stage in PIPELINE_STAGES:
        chain = chain | RunnableLambda(
            lambda state, current_stage=stage: _execute_stage(
                state, current_stage, registry
            )
        )
    return chain


def run_langchain(state: PipelineState, registry: ToolRegistry) -> PipelineState:
    validate_pipeline_state(state)
    return build_langchain(registry).invoke(state)


def build_langgraph(registry: ToolRegistry):
    """Compile the same stage contract with LangGraph when it is available."""
    missing = registry.missing(PIPELINE_STAGES)
    if missing:
        raise ValueError(f"pipeline registry is incomplete: {missing}")
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError(
            "LangGraph is not installed. Run with langgraph==1.2.9 or use the "
            "deterministic engine."
        ) from exc

    builder = StateGraph(PipelineState)
    builder.add_node(
        "resume-prefix",
        lambda state: _rebuild_reused_prefix(state, registry),
    )
    for stage in PIPELINE_STAGES:
        builder.add_node(
            stage.value,
            lambda state, current_stage=stage: _execute_stage(
                state, current_stage, registry
            ),
        )
    builder.add_edge(START, "resume-prefix")
    builder.add_edge("resume-prefix", PIPELINE_STAGES[0].value)
    for current, following in PIPELINE_TRANSITIONS:
        builder.add_edge(current.value, following.value)
    builder.add_edge(PIPELINE_STAGES[-1].value, END)
    return builder.compile()


def run_langgraph(state: PipelineState, registry: ToolRegistry) -> PipelineState:
    validate_pipeline_state(state)
    return build_langgraph(registry).invoke(state)
