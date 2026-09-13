"""Deterministic attempt ledger for the Runner-only garment loop."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .runner_audit import Decision, StopReason, stop_reason

_HASH = re.compile(r"^[0-9a-f]{64}$")


def new_ledger(request_sha256: str, initial_candidate_sha256: str) -> dict[str, Any]:
    _require_hash("requestSha256", request_sha256)
    _require_hash("initialCandidateSha256", initial_candidate_sha256)
    return {
        "schemaVersion": 1,
        "requestSha256": request_sha256,
        "initialCandidateSha256": initial_candidate_sha256,
        "currentCandidateSha256": initial_candidate_sha256,
        "attempts": [],
        "stopReason": None,
        "earlyStopCandidate": False,
    }


def _require_hash(name: str, value: Any) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256")
    return value


def validate_ledger(ledger: Mapping[str, Any], request_sha256: str) -> None:
    _require_hash("requestSha256", request_sha256)
    if ledger.get("requestSha256") != request_sha256:
        raise ValueError("attempt ledger request hash mismatch")
    _require_hash("initialCandidateSha256", ledger.get("initialCandidateSha256"))
    _require_hash("currentCandidateSha256", ledger.get("currentCandidateSha256"))
    attempts = ledger.get("attempts")
    if not isinstance(attempts, list):
        raise ValueError("attempt ledger attempts must be a list")
    expected = 1
    current = ledger["initialCandidateSha256"]
    for attempt in attempts:
        if not isinstance(attempt, Mapping):
            raise ValueError("attempt ledger entry must be an object")
        if attempt.get("attempt") != expected:
            raise ValueError("attempt numbers must be contiguous and one-based")
        if attempt.get("requestSha256") != request_sha256:
            raise ValueError("attempt request hash mismatch")
        if attempt.get("beforeCandidateSha256") != current:
            raise ValueError("attempt before-candidate does not match ledger state")
        after = _require_hash("afterCandidateSha256", attempt.get("afterCandidateSha256"))
        decision = Decision(str(attempt.get("decision")))
        current = after if decision is Decision.KEEP else current
        expected += 1
    if current != ledger["currentCandidateSha256"]:
        raise ValueError("ledger current candidate does not match attempt history")


def blocker_stats(ledger: Mapping[str, Any], blocker: str) -> tuple[int, int]:
    attempts = ledger.get("attempts", [])
    relevant = [item for item in attempts if item.get("blocker") == blocker]
    accepted = sum(item.get("decision") == Decision.KEEP.value for item in relevant)
    return len(relevant), accepted


def consecutive_reverts(ledger: Mapping[str, Any]) -> int:
    count = 0
    for item in reversed(ledger.get("attempts", [])):
        if item.get("decision") != Decision.REVERT.value:
            break
        count += 1
    return count


def record_attempt(
    ledger: Mapping[str, Any],
    *,
    request_sha256: str,
    blocker: str,
    before_candidate_sha256: str,
    after_candidate_sha256: str,
    before_audit_sha256: str,
    after_audit_sha256: str,
    patch_id: str,
    decision: Decision,
    elapsed_minutes: float,
) -> dict[str, Any]:
    validate_ledger(ledger, request_sha256)
    if ledger.get("stopReason") is not None:
        raise ValueError("cannot append attempt after terminal stopReason")
    if not isinstance(blocker, str) or not blocker:
        raise ValueError("blocker is required")
    if not isinstance(patch_id, str) or not patch_id:
        raise ValueError("patchId is required")
    _require_hash("beforeCandidateSha256", before_candidate_sha256)
    _require_hash("afterCandidateSha256", after_candidate_sha256)
    _require_hash("beforeAuditSha256", before_audit_sha256)
    _require_hash("afterAuditSha256", after_audit_sha256)
    if before_candidate_sha256 != ledger["currentCandidateSha256"]:
        raise ValueError("attempt before-candidate must equal ledger current candidate")
    if elapsed_minutes < 0:
        raise ValueError("elapsedMinutes must be non-negative")

    attempts = [dict(item) for item in ledger["attempts"]]
    attempts.append({
        "attempt": len(attempts) + 1,
        "requestSha256": request_sha256,
        "blocker": blocker,
        "patchId": patch_id,
        "beforeCandidateSha256": before_candidate_sha256,
        "afterCandidateSha256": after_candidate_sha256,
        "beforeAuditSha256": before_audit_sha256,
        "afterAuditSha256": after_audit_sha256,
        "decision": decision.value,
        "elapsedMinutes": elapsed_minutes,
    })
    result = dict(ledger)
    result["attempts"] = attempts
    if decision is Decision.KEEP:
        result["currentCandidateSha256"] = after_candidate_sha256
    result["earlyStopCandidate"] = consecutive_reverts(result) >= 3
    validate_ledger(result, request_sha256)
    return result


def resolve_stop(
    ledger: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    blocker: str | None,
    complete: bool,
    failed_hard: bool,
    elapsed_minutes: float,
) -> StopReason | None:
    validate_ledger(ledger, str(request["requestSha256"]))
    blocker_attempts = 0
    accepted_for_blocker = 0
    if blocker:
        blocker_attempts, accepted_for_blocker = blocker_stats(ledger, blocker)
    return stop_reason(
        complete=complete,
        failed_hard=failed_hard,
        total_attempts=len(ledger["attempts"]),
        elapsed_minutes=elapsed_minutes,
        max_total_attempts=int(request["maxTotalAttempts"]),
        max_runner_minutes=int(request["maxRunnerMinutes"]),
        blocker_attempts=blocker_attempts,
        max_attempts_per_blocker=int(request["maxAttemptsPerBlocker"]),
        accepted_for_blocker=accepted_for_blocker,
    )


def finalize_ledger(ledger: Mapping[str, Any], stop: StopReason) -> dict[str, Any]:
    result = dict(ledger)
    if result.get("stopReason") is not None:
        raise ValueError("attempt ledger is already terminal")
    result["stopReason"] = stop.value
    return result
