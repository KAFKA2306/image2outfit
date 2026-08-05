"""Compatibility bridge from the existing stage-result v1 contract."""

from __future__ import annotations

from typing import Any, Mapping

from .artifact_dag import ArtifactKind, ArtifactRef
from .pipeline import PipelineStage


def artifact_ref_from_stage_result(
    result: Mapping[str, Any],
    *,
    kind: ArtifactKind | str,
    hypothesis_id: str,
    candidate_id: str,
    avatar_sha256: str,
    evidence_index: int = 0,
) -> ArtifactRef:
    """Convert a validated stage-result v1 payload to a typed artifact ref."""
    required = {"schemaVersion", "stage", "productId", "status", "evidence"}
    missing = sorted(required.difference(result))
    if missing:
        raise ValueError(f"stage result is missing required fields: {missing}")
    if result["schemaVersion"] != 1:
        raise ValueError("only stage-result schemaVersion 1 is supported")
    if result["status"] != "PASS":
        raise ValueError("only PASS stage results can produce artifact refs")
    evidence = result["evidence"]
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("stage result evidence must be a non-empty list")
    try:
        selected = evidence[evidence_index]
    except IndexError as exc:
        raise ValueError("evidence_index is outside the stage result evidence") from exc
    if not isinstance(selected, Mapping):
        raise ValueError("selected stage result evidence must be an object")
    if set(selected) != {"path", "sha256"}:
        raise ValueError("stage result evidence must contain only path and sha256")
    return ArtifactRef(
        kind=ArtifactKind(kind),
        producer_stage=PipelineStage(str(result["stage"])),
        garment_id=str(result["productId"]),
        hypothesis_id=hypothesis_id,
        candidate_id=candidate_id,
        avatar_sha256=avatar_sha256,
        content_sha256=str(selected["sha256"]),
        artifact_path=str(selected["path"]),
        schema_version=int(result["schemaVersion"]),
    )
