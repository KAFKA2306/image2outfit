"""Deterministic stage pipeline with an optional LangGraph execution adapter."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, TypedDict

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


PIPELINE_STAGES = tuple(PipelineStage)
PIPELINE_TRANSITIONS = tuple(
    zip(PIPELINE_STAGES[:-1], PIPELINE_STAGES[1:], strict=True)
)


class PipelineState(TypedDict, total=False):
    schema_version: int
    product_id: str
    target_avatar: str
    source_reference: str
    profile_id: str
    status: str
    current_stage: str
    completed_stages: list[str]
    events: list[dict[str, Any]]
    errors: list[str]
    outputs: dict[str, Any]


def new_pipeline_state(
    *,
    product_id: str,
    target_avatar: str,
    source_reference: str,
    profile_id: str = "garment-reconstruction-v1",
) -> PipelineState:
    if not product_id or not target_avatar or not source_reference:
        raise ValueError("product_id, target_avatar, and source_reference are required")
    return {
        "schema_version": 1,
        "product_id": product_id,
        "target_avatar": target_avatar,
        "source_reference": source_reference,
        "profile_id": profile_id,
        "status": "READY",
        "current_stage": "",
        "completed_stages": [],
        "events": [],
        "errors": [],
        "outputs": {},
    }


def _execute_stage(
    state: PipelineState,
    stage: PipelineStage,
    registry: ToolRegistry,
) -> PipelineState:
    if state.get("status") == "FAILED":
        return state
    try:
        update = registry.invoke(stage, state)
    except Exception as exc:  # noqa: BLE001 - stage boundary records exact failure
        error = f"{stage.value}: {type(exc).__name__}: {exc}"
        errors = [*state.get("errors", []), error]
        events = [
            *state.get("events", []),
            {"stage": stage.value, "status": "FAILED", "error": str(exc)},
        ]
        return {
            **state,
            "status": "FAILED",
            "current_stage": stage.value,
            "errors": errors,
            "events": events,
        }

    outputs = {**state.get("outputs", {}), stage.value: update}
    completed = [*state.get("completed_stages", []), stage.value]
    events = [
        *state.get("events", []),
        {
            "stage": stage.value,
            "status": "PASS",
            "tool": registry.descriptor(stage).tool_name,
        },
    ]
    status = "COMPLETE" if stage is PIPELINE_STAGES[-1] else "RUNNING"
    return {
        **state,
        "status": status,
        "current_stage": stage.value,
        "completed_stages": completed,
        "events": events,
        "outputs": outputs,
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
