"""Deterministic stage pipeline with LangChain and LangGraph adapters."""

from __future__ import annotations

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
    product_id: str
    target_avatar: str
    source_reference: str
    profile_id: str
    execution_mode: str
    status: str
    current_stage: str
    completed_stages: list[str]
    events: list[dict[str, Any]]
    errors: list[str]
    outputs: dict[str, Any]
    stage_records: list[dict[str, Any]]


def new_pipeline_state(
    *,
    product_id: str,
    target_avatar: str,
    source_reference: str,
    profile_id: str = "garment-reconstruction-v1",
    execution_mode: ExecutionMode | str = ExecutionMode.PLAN,
    run_id: str | None = None,
) -> PipelineState:
    if not product_id or not target_avatar or not source_reference:
        raise ValueError("product_id, target_avatar, and source_reference are required")
    mode = ExecutionMode(execution_mode)
    return {
        "schema_version": 1,
        "run_id": run_id or uuid4().hex,
        "product_id": product_id,
        "target_avatar": target_avatar,
        "source_reference": source_reference,
        "profile_id": profile_id,
        "execution_mode": mode.value,
        "status": "READY",
        "current_stage": "",
        "completed_stages": [],
        "events": [],
        "errors": [],
        "outputs": {},
        "stage_records": [],
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
        "productId": state.get("product_id"),
        "targetAvatar": state.get("target_avatar"),
        "sourceReference": state.get("source_reference"),
        "profileId": state.get("profile_id"),
        "executionMode": state.get("execution_mode"),
        "stage": stage.value,
        "completedStages": list(state.get("completed_stages", [])),
        "previousRecordDigest": previous_digest,
    }


def _execute_stage(
    state: PipelineState,
    stage: PipelineStage,
    registry: ToolRegistry,
) -> PipelineState:
    if state.get("status") == "FAILED":
        return state
    descriptor = registry.descriptor(stage)
    mode = ExecutionMode(state.get("execution_mode", ExecutionMode.PLAN.value))
    records = list(state.get("stage_records", []))
    previous_digest = records[-1]["recordDigest"] if records else "0" * 64
    input_snapshot = _stage_input_snapshot(state, stage)
    started_at = utc_now()
    try:
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
    completed = [*state.get("completed_stages", []), stage.value]
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


def run_pipeline(state: PipelineState, registry: ToolRegistry) -> PipelineState:
    missing = registry.missing(PIPELINE_STAGES)
    if missing:
        raise ValueError(f"pipeline registry is incomplete: {missing}")
    current = dict(state)
    for stage in PIPELINE_STAGES:
        current = _execute_stage(current, stage, registry)
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

    chain = RunnableLambda(lambda state: state)
    for stage in PIPELINE_STAGES:
        chain = chain | RunnableLambda(
            lambda state, current_stage=stage: _execute_stage(
                state, current_stage, registry
            )
        )
    return chain


def run_langchain(state: PipelineState, registry: ToolRegistry) -> PipelineState:
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
    for stage in PIPELINE_STAGES:
        builder.add_node(
            stage.value,
            lambda state, current_stage=stage: _execute_stage(
                state, current_stage, registry
            ),
        )
    builder.add_edge(START, PIPELINE_STAGES[0].value)
    for current, following in PIPELINE_TRANSITIONS:
        builder.add_edge(current.value, following.value)
    builder.add_edge(PIPELINE_STAGES[-1].value, END)
    return builder.compile()


def run_langgraph(state: PipelineState, registry: ToolRegistry) -> PipelineState:
    return build_langgraph(registry).invoke(state)
