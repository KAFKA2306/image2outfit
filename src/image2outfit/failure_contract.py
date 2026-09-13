"""Stable machine-readable failure descriptors for pipeline callers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

ERROR_CODES = (
    "INVALID_PIPELINE_INPUT",
    "PIPELINE_CONFIGURATION_INVALID",
    "PIPELINE_EXECUTION_FAILED",
    "INVALID_RESUME_STATE",
    "PIPELINE_ENGINE_UNAVAILABLE",
    "AUDIT_PUBLICATION_FAILED",
    "INTERNAL_PIPELINE_ERROR",
)
PHASES = ("request", "contract", "profile", "resume", "registry", "pipeline", "audit")
_CAUSE_CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def stable_cause_code(exc: BaseException) -> str | None:
    """Return an explicit domain code without using the Python exception class name."""
    for attribute in ("cause_code", "error_code", "code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, str) and _CAUSE_CODE.fullmatch(value):
            return value
    return None


def failure_descriptor(
    error_code: str,
    phase: str,
    message: str,
    *,
    stage: str | None = None,
    cause_code: str | None = None,
) -> dict[str, str]:
    if error_code not in ERROR_CODES:
        raise ValueError(f"unsupported pipeline failure errorCode: {error_code}")
    if phase not in PHASES:
        raise ValueError(f"unsupported pipeline failure phase: {phase}")
    if not isinstance(message, str) or not message:
        raise ValueError("pipeline failure message must be a non-empty string")
    failure = {"errorCode": error_code, "phase": phase, "message": message}
    if stage:
        failure["stage"] = stage
    if cause_code:
        if not _CAUSE_CODE.fullmatch(cause_code):
            raise ValueError(f"invalid pipeline failure causeCode: {cause_code}")
        failure["causeCode"] = cause_code
    return failure


def failed_state_descriptor(state: Mapping[str, Any]) -> dict[str, str]:
    """Project a FAILED pipeline state onto the canonical failure contract."""
    if state.get("status") != "FAILED":
        raise ValueError("pipeline state is not FAILED")
    stage = str(state.get("current_stage", "")) or None
    output: Mapping[str, Any] = {}
    outputs = state.get("outputs")
    if stage and isinstance(outputs, Mapping):
        candidate = outputs.get(stage)
        if isinstance(candidate, Mapping):
            output = candidate
    message = str(output.get("error") or "pipeline stage execution failed")
    cause = output.get("causeCode")
    return failure_descriptor(
        "PIPELINE_EXECUTION_FAILED",
        "pipeline",
        message,
        stage=stage,
        cause_code=cause if isinstance(cause, str) else None,
    )
