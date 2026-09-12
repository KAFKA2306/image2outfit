"""Runtime enforcement for typed producer/consumer artifact handoff."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from .artifact_bridge import artifact_ref_from_stage_result
from .artifact_dag import ArtifactKind, ArtifactRef, PipelineArtifactDAG
from .pipeline import ExecutionMode, PipelineStage

_DAG = PipelineArtifactDAG()


def _ref_from_dict(raw: Mapping[str, Any]) -> ArtifactRef:
    return ArtifactRef(
        kind=ArtifactKind(str(raw["kind"])),
        producer_stage=PipelineStage(str(raw["producer_stage"])),
        garment_id=str(raw["garment_id"]),
        hypothesis_id=str(raw["hypothesis_id"]),
        candidate_id=str(raw["candidate_id"]),
        avatar_sha256=str(raw["avatar_sha256"]),
        content_sha256=str(raw["content_sha256"]),
        artifact_path=str(raw["artifact_path"]),
        schema_version=int(raw.get("schema_version", 1)),
    )


def _ref_dict(ref: ArtifactRef) -> dict[str, Any]:
    return {
        "kind": ref.kind.value,
        "producer_stage": ref.producer_stage.value,
        "garment_id": ref.garment_id,
        "hypothesis_id": ref.hypothesis_id,
        "candidate_id": ref.candidate_id,
        "avatar_sha256": ref.avatar_sha256,
        "content_sha256": ref.content_sha256,
        "artifact_path": ref.artifact_path,
        "schema_version": ref.schema_version,
    }


def _completed_refs(state: Mapping[str, Any]) -> list[ArtifactRef]:
    refs: list[ArtifactRef] = []
    outputs = state.get("outputs", {})
    if not isinstance(outputs, Mapping):
        return refs
    for stage_name in state.get("completed_stages", []):
        output = outputs.get(stage_name)
        if not isinstance(output, Mapping):
            continue
        raw = output.get("artifactRef")
        if isinstance(raw, Mapping):
            refs.append(_ref_from_dict(raw))
    return refs


def _identity(
    state: Mapping[str, Any], refs: list[ArtifactRef]
) -> tuple[str, str, str, str]:
    if refs:
        anchor = refs[0]
        return (
            str(state["product_id"]),
            anchor.hypothesis_id,
            anchor.candidate_id,
            anchor.avatar_sha256,
        )
    hypothesis_id = str(
        state.get("revision_id")
        or state.get("source_fingerprint")
        or state.get("profile_id")
        or "default-hypothesis"
    )
    candidate_id = str(
        state.get("parent_run_id") or state.get("run_id") or "default-candidate"
    )
    avatar_sha256 = hashlib.sha256(
        str(state["target_avatar"]).encode("utf-8")
    ).hexdigest()
    return str(state["product_id"]), hypothesis_id, candidate_id, avatar_sha256


def _enforced(state: Mapping[str, Any]) -> bool:
    return (
        state.get("execution_mode") == ExecutionMode.EXECUTE.value
        and isinstance(state.get("source_fingerprint"), str)
        and bool(state["source_fingerprint"])
    )


def validate_runtime_artifact_inputs(
    stage: PipelineStage | str,
    state: Mapping[str, Any],
    *,
    repository_root: str,
) -> None:
    """Fail closed before a canonical execute-mode consumer starts."""
    if not _enforced(state):
        return
    resolved = PipelineStage(stage)
    refs = _completed_refs(state)
    garment_id, hypothesis_id, candidate_id, avatar_sha256 = _identity(state, refs)
    _DAG.validate_inputs(
        resolved,
        refs,
        garment_id=garment_id,
        hypothesis_id=hypothesis_id,
        candidate_id=candidate_id,
        avatar_sha256=avatar_sha256,
    )
    required = set(_DAG.contract(resolved).consumes)
    for ref in refs:
        if ref.kind in required:
            ref.verify_content(repository_root)


def attach_runtime_artifact_ref(
    stage: PipelineStage | str,
    state: Mapping[str, Any],
    output: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach the canonical produced ArtifactRef to an executed stage output."""
    result = dict(output)
    if not _enforced(state) or result.get("mode") != "executed":
        return result
    payload = result.get("result")
    if not isinstance(payload, Mapping):
        raise ValueError("executed stage output is missing validated result payload")
    resolved = PipelineStage(stage)
    refs = _completed_refs(state)
    _, hypothesis_id, candidate_id, avatar_sha256 = _identity(state, refs)
    ref = artifact_ref_from_stage_result(
        payload,
        kind=_DAG.contract(resolved).produces,
        hypothesis_id=hypothesis_id,
        candidate_id=candidate_id,
        avatar_sha256=avatar_sha256,
    )
    result["artifactRef"] = _ref_dict(ref)
    return result
