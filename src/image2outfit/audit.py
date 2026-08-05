"""Tamper-evident audit records for canonical garment pipeline runs."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_HASH = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_ZERO_HASH = "0" * 64


def utc_now() -> str:
    return (
        datetime.now(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def canonical_json_bytes(value: Any) -> bytes:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("audit payload must be finite JSON data") from exc
    return payload.encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalized_evidence(output: Mapping[str, Any]) -> list[dict[str, str]]:
    result = output.get("result")
    if not isinstance(result, Mapping):
        return []
    evidence = result.get("evidence")
    if not isinstance(evidence, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in evidence:
        if not isinstance(item, Mapping):
            continue
        path = item.get("path")
        digest = item.get("sha256")
        if isinstance(path, str) and isinstance(digest, str):
            normalized.append({"path": path, "sha256": digest})
    return normalized


def make_stage_record(
    *,
    run_id: str,
    product_id: str,
    sequence: int,
    stage: str,
    requested_mode: str,
    outcome_mode: str,
    status: str,
    tool_name: str,
    purpose: str,
    output_contract: str,
    input_snapshot: Mapping[str, Any],
    output: Mapping[str, Any],
    previous_record_digest: str = _ZERO_HASH,
    started_at: str,
    finished_at: str,
) -> dict[str, Any]:
    if sequence < 1:
        raise ValueError("stage audit sequence must be positive")
    if not _HASH.fullmatch(previous_record_digest):
        raise ValueError("previous_record_digest must be a SHA-256 digest")
    record: dict[str, Any] = {
        "schemaVersion": 1,
        "runId": run_id,
        "productId": product_id,
        "sequence": sequence,
        "stage": stage,
        "requestedMode": requested_mode,
        "outcomeMode": outcome_mode,
        "status": status,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "tool": {
            "name": tool_name,
            "purpose": purpose,
            "outputContract": output_contract,
        },
        "inputDigest": sha256_json(input_snapshot),
        "outputDigest": sha256_json(output),
        "previousRecordDigest": previous_record_digest,
        "resultPath": output.get("resultPath", ""),
        "evidence": _normalized_evidence(output),
        "output": dict(output),
    }
    record["recordDigest"] = sha256_json(record)
    return record


def validate_stage_records(
    records: Sequence[Mapping[str, Any]],
    *,
    expected_run_id: str | None = None,
    expected_product_id: str | None = None,
    canonical_stages: Sequence[str] | None = None,
) -> None:
    previous = _ZERO_HASH
    for index, raw in enumerate(records, start=1):
        record = dict(raw)
        if record.get("schemaVersion") != 1:
            raise ValueError(f"stage audit record {index} schemaVersion must be 1")
        if record.get("sequence") != index:
            raise ValueError(f"stage audit record {index} sequence is invalid")
        if expected_run_id is not None and record.get("runId") != expected_run_id:
            raise ValueError(f"stage audit record {index} runId mismatch")
        if (
            expected_product_id is not None
            and record.get("productId") != expected_product_id
        ):
            raise ValueError(f"stage audit record {index} productId mismatch")
        if canonical_stages is not None:
            if index > len(canonical_stages):
                raise ValueError("stage audit records exceed the canonical stage count")
            if record.get("stage") != canonical_stages[index - 1]:
                raise ValueError(f"stage audit record {index} is out of canonical order")
        if record.get("previousRecordDigest") != previous:
            raise ValueError(f"stage audit record {index} chain is broken")
        claimed = record.pop("recordDigest", None)
        if not isinstance(claimed, str) or not _HASH.fullmatch(claimed):
            raise ValueError(f"stage audit record {index} digest is invalid")
        actual = sha256_json(record)
        if actual != claimed:
            raise ValueError(f"stage audit record {index} digest mismatch")
        previous = claimed


def _safe_identifier(value: str, *, label: str) -> str:
    if not value or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} contains unsafe path characters")
    return value


def _resolve_inside(root: Path, value: str, *, label: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        raise ValueError(f"{label} must be relative")
    resolved_root = root.resolve()
    resolved = (resolved_root / path).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"{label} escapes the audit bundle")
    return resolved


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_audit_bundle(
    state: Mapping[str, Any],
    *,
    audit_root: Path,
    canonical_stages: Sequence[str],
) -> dict[str, Any]:
    run_id = _safe_identifier(str(state["run_id"]), label="run_id")
    product_id = _safe_identifier(str(state["product_id"]), label="product_id")
    raw_records = state.get("stage_records", [])
    if not isinstance(raw_records, list):
        raise ValueError("pipeline stage_records must be a list")
    records = [dict(record) for record in raw_records]
    validate_stage_records(
        records,
        expected_run_id=run_id,
        expected_product_id=product_id,
        canonical_stages=canonical_stages,
    )
    final_status = state.get("status")
    if final_status in {"PLANNED", "EXECUTED"} and len(records) != len(
        canonical_stages
    ):
        raise ValueError("successful pipeline audit must contain all canonical stages")

    resolved_audit_root = audit_root.resolve()
    run_root = resolved_audit_root / product_id / run_id
    if run_root.exists():
        raise FileExistsError(f"audit run already exists and is immutable: {run_root}")
    stages_root = run_root / "stages"
    stage_entries: list[dict[str, Any]] = []
    for record in records:
        sequence = int(record["sequence"])
        stage = str(record["stage"])
        path = stages_root / f"{sequence:02d}-{stage}.json"
        _write_json_atomic(path, record)
        stage_entries.append(
            {
                "sequence": sequence,
                "stage": stage,
                "status": record["status"],
                "path": path.relative_to(run_root).as_posix(),
                "sha256": sha256_file(path),
                "recordDigest": record["recordDigest"],
            }
        )

    state_path = run_root / "pipeline-state.json"
    _write_json_atomic(state_path, state)
    manifest = {
        "schemaVersion": 1,
        "runId": run_id,
        "productId": product_id,
        "profileId": state.get("profile_id", ""),
        "executionMode": state.get("execution_mode", ""),
        "finalStatus": final_status,
        "createdAt": utc_now(),
        "canonicalStages": list(canonical_stages),
        "recordedStageCount": len(stage_entries),
        "chainHeadDigest": records[-1]["recordDigest"] if records else _ZERO_HASH,
        "pipelineState": {
            "path": state_path.relative_to(run_root).as_posix(),
            "sha256": sha256_file(state_path),
        },
        "stages": stage_entries,
    }
    manifest_path = run_root / "manifest.json"
    _write_json_atomic(manifest_path, manifest)
    manifest_sha256 = sha256_file(manifest_path)
    latest_path = resolved_audit_root / product_id / "latest.json"
    _write_json_atomic(
        latest_path,
        {
            "schemaVersion": 1,
            "productId": product_id,
            "runId": run_id,
            "finalStatus": final_status,
            "manifestPath": manifest_path.relative_to(resolved_audit_root).as_posix(),
            "manifestSha256": manifest_sha256,
            "updatedAt": utc_now(),
        },
    )
    verify_audit_bundle(run_root)
    return {
        "root": run_root.as_posix(),
        "manifestPath": manifest_path.as_posix(),
        "manifestSha256": manifest_sha256,
        "latestPath": latest_path.as_posix(),
        "chainHeadDigest": manifest["chainHeadDigest"],
    }


def verify_audit_bundle(run_root: Path) -> dict[str, Any]:
    manifest_path = run_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != 1:
        raise ValueError("audit manifest schemaVersion must be 1")
    canonical_stages = manifest.get("canonicalStages")
    if not isinstance(canonical_stages, list) or not all(
        isinstance(stage, str) and stage for stage in canonical_stages
    ):
        raise ValueError("audit manifest canonicalStages must be a string list")
    stage_entries = manifest.get("stages")
    if not isinstance(stage_entries, list):
        raise ValueError("audit manifest stages must be a list")
    if manifest.get("recordedStageCount") != len(stage_entries):
        raise ValueError("audit manifest recordedStageCount mismatch")

    records: list[dict[str, Any]] = []
    for index, entry in enumerate(stage_entries, start=1):
        if not isinstance(entry, Mapping):
            raise ValueError(f"audit manifest stage {index} must be an object")
        value = entry.get("path")
        if not isinstance(value, str) or not value:
            raise ValueError(f"audit manifest stage {index} path is required")
        path = _resolve_inside(run_root, value, label=f"stage {index} path")
        if not path.is_file() or sha256_file(path) != entry.get("sha256"):
            raise ValueError(f"audit stage file hash mismatch: {value}")
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("recordDigest") != entry.get("recordDigest"):
            raise ValueError(f"audit stage record digest mismatch: {value}")
        records.append(record)
    validate_stage_records(
        records,
        expected_run_id=manifest.get("runId"),
        expected_product_id=manifest.get("productId"),
        canonical_stages=canonical_stages,
    )
    final_status = manifest.get("finalStatus")
    if final_status in {"PLANNED", "EXECUTED"} and len(records) != len(
        canonical_stages
    ):
        raise ValueError("successful audit manifest must contain every canonical stage")

    state_entry = manifest.get("pipelineState")
    if not isinstance(state_entry, Mapping):
        raise ValueError("audit manifest pipelineState must be an object")
    state_value = state_entry.get("path")
    if not isinstance(state_value, str) or not state_value:
        raise ValueError("audit manifest pipelineState path is required")
    state_path = _resolve_inside(run_root, state_value, label="pipelineState path")
    if not state_path.is_file() or sha256_file(state_path) != state_entry.get("sha256"):
        raise ValueError("audit pipeline-state file hash mismatch")
    expected_head = records[-1]["recordDigest"] if records else _ZERO_HASH
    if manifest.get("chainHeadDigest") != expected_head:
        raise ValueError("audit manifest chain head mismatch")
    return manifest
