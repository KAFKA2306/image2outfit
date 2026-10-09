"""Stable batch-manifest and aggregation logic for product execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_ALLOWED_STATES = {"SUCCEEDED", "REVIEW_REQUIRED", "FAILED", "BLOCKED", "NO_STATE"}


@dataclass(frozen=True, slots=True)
class BatchManifest:
    batch_id: str
    requests: tuple[str, ...]
    max_concurrency: int
    continue_on_error: bool

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "BatchManifest":
        if value.get("schemaVersion") != 1:
            raise ValueError("batch manifest schemaVersion must be 1")

        batch_id = value.get("batchId")
        if not isinstance(batch_id, str) or not batch_id:
            raise ValueError("batchId is required")

        raw_requests = value.get("requests")
        if not isinstance(raw_requests, list) or not raw_requests:
            raise ValueError("requests must be a non-empty list")

        requests: list[str] = []
        for index, item in enumerate(raw_requests):
            if not isinstance(item, str) or not item:
                raise ValueError(f"requests[{index}] must be a non-empty string")
            path = Path(item)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"requests[{index}] must stay repository-relative")
            if path.parent.as_posix() != "config/pipeline/requests":
                raise ValueError(
                    f"requests[{index}] must live under config/pipeline/requests"
                )
            if path.suffix != ".json":
                raise ValueError(f"requests[{index}] must be a JSON request")
            requests.append(path.as_posix())

        if len(set(requests)) != len(requests):
            raise ValueError("batch requests must be unique")

        max_concurrency = value.get("maxConcurrency", 1)
        if max_concurrency != 1:
            raise ValueError(
                "maxConcurrency must be 1 because product execution is serialized"
            )

        continue_on_error = value.get("continueOnError", True)
        if continue_on_error is not True:
            raise ValueError(
                "continueOnError must be true so one failed product cannot hide later states"
            )

        if value.get("resumePolicy") != "canonical-checkpoint":
            raise ValueError("resumePolicy must be canonical-checkpoint")
        if value.get("terminalCachePolicy") != "reuse-executed":
            raise ValueError("terminalCachePolicy must be reuse-executed")

        return cls(
            batch_id=batch_id,
            requests=tuple(requests),
            max_concurrency=1,
            continue_on_error=True,
        )


def batch_status(items: Sequence[Mapping[str, Any]]) -> str:
    states = {str(item.get("schedulerState", "NO_STATE")) for item in items}
    unknown = states - _ALLOWED_STATES
    if unknown:
        raise ValueError("unknown scheduler states: " + ", ".join(sorted(unknown)))
    if states & {"FAILED", "BLOCKED", "NO_STATE"}:
        return "FAILED"
    if "REVIEW_REQUIRED" in states:
        return "REVIEW_REQUIRED"
    return "SUCCEEDED"


def summarize(
    manifest: BatchManifest,
    items: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    counts = {state: 0 for state in sorted(_ALLOWED_STATES)}
    normalized: list[dict[str, Any]] = []

    for item in items:
        state = str(item.get("schedulerState", "NO_STATE"))
        if state not in _ALLOWED_STATES:
            raise ValueError(f"unknown scheduler state: {state}")
        counts[state] += 1
        normalized.append(
            {
                "request": str(item["request"]),
                "productId": str(item.get("productId", "")),
                "schedulerState": state,
                "currentStage": str(item.get("currentStage", "")),
                "cachedTerminal": bool(item.get("cachedTerminal", False)),
                "returnCode": int(item.get("returnCode", 0)),
            }
        )

    return {
        "schemaVersion": 1,
        "batchId": manifest.batch_id,
        "status": batch_status(normalized),
        "requestCount": len(manifest.requests),
        "counts": counts,
        "items": normalized,
        "schedulerOwnsCompletion": False,
        "productCompletionClaimed": False,
        "releaseEligibilityEvaluated": False,
    }
