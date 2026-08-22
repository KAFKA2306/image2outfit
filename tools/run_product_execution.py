#!/usr/bin/env python3
"""Execute one tracked product request without making product-state claims.

External schedulers may call this wrapper, but the canonical garment pipeline
continues to own stage execution and audit state. Product completion and release
remain separate authorities.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import runtime_paths  # noqa: E402
from pipeline_source_fingerprint import pipeline_source_fingerprint  # noqa: E402

PIPELINE_RUNNER = TOOLS / "run_garment_pipeline.py"
DEFAULT_PROFILE = Path("config/pipeline-profiles/garment-reconstruction-v1.json")
CHECKPOINT_NAME = "pipeline-state.json"
EXECUTION_STATE_NAME = "product-execution-state.json"
MANUAL_REVIEW_MARKER = "direct visual review is not recorded yet"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    return parser.parse_args()


def _repo_path(path: Path, *, label: str) -> Path:
    resolved = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise ValueError(f"{label} escapes repository: {path}")
    return resolved


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _read_request(path: Path) -> dict[str, Any]:
    value = _read_object(path, label="request")
    if value.get("schemaVersion") != 1:
        raise ValueError("request.schemaVersion must be 1")
    for field in ("productId", "targetAvatar", "sourceReference"):
        if not isinstance(value.get(field), str) or not value[field]:
            raise ValueError(f"request.{field} is required")
    return value


def _profile_path(request: Mapping[str, Any]) -> Path:
    configured = request.get("profilePath")
    if configured is None:
        return _repo_path(DEFAULT_PROFILE, label="default profile")
    if not isinstance(configured, str) or not configured:
        raise ValueError("request.profilePath must be a non-empty string")
    return _repo_path(Path(configured), label="request.profilePath")


def execution_paths(request_path: Path) -> tuple[str, Path, Path, Path]:
    request_path = _repo_path(request_path, label="request")
    request = _read_request(request_path)
    product_id = str(request["productId"])
    runtime = runtime_paths.for_product(ROOT, product_id)
    checkpoint = runtime.reports / CHECKPOINT_NAME
    execution_state = runtime.reports / EXECUTION_STATE_NAME
    return product_id, request_path, checkpoint, execution_state


def current_source_fingerprint(request_path: Path, request: Mapping[str, Any]) -> str:
    return pipeline_source_fingerprint(
        ROOT,
        product_id=str(request["productId"]),
        request_path=request_path,
        profile_path=_profile_path(request),
    )


def checkpoint_matches_request(
    checkpoint: Mapping[str, Any],
    request: Mapping[str, Any],
    source_fingerprint: str,
) -> bool:
    expected = {
        "product_id": str(request["productId"]),
        "target_avatar": str(request["targetAvatar"]),
        "source_reference": str(request["sourceReference"]),
        "revision_id": str(request.get("revisionId", "")),
        "source_fingerprint": source_fingerprint,
        "execution_mode": "execute",
    }
    return checkpoint.get("schema_version") == 1 and all(
        str(checkpoint.get(key, "")) == value for key, value in expected.items()
    )


def classify_checkpoint(checkpoint: Mapping[str, Any]) -> str:
    status = checkpoint.get("status")
    if status == "EXECUTED":
        return "SUCCEEDED"
    errors = checkpoint.get("errors", [])
    if (
        status == "FAILED"
        and checkpoint.get("current_stage") == "visual-review"
        and isinstance(errors, list)
        and any(MANUAL_REVIEW_MARKER in str(error) for error in errors)
    ):
        return "REVIEW_REQUIRED"
    if status == "FAILED":
        return "FAILED"
    return "BLOCKED"


def execution_state_payload(
    *,
    product_id: str,
    request_path: Path,
    checkpoint_path: Path,
    checkpoint: Mapping[str, Any],
    scheduler_state: str,
    cached_terminal: bool,
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "productId": product_id,
        "request": request_path.relative_to(ROOT).as_posix(),
        "checkpoint": checkpoint_path.relative_to(ROOT).as_posix(),
        "schedulerState": scheduler_state,
        "pipelineStatus": checkpoint.get("status"),
        "currentStage": checkpoint.get("current_stage", ""),
        "completedStageCount": len(checkpoint.get("completed_stages", [])),
        "cachedTerminal": cached_terminal,
        "schedulerOwnsCompletion": False,
        "productCompletionClaimed": False,
        "releaseEligibilityEvaluated": False,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_pipeline_command(request_path: Path, checkpoint: Path) -> list[str]:
    command = [
        sys.executable,
        str(PIPELINE_RUNNER),
        "--request",
        str(request_path),
        "--execute",
        "--checkpoint-output",
        str(checkpoint),
    ]
    if checkpoint.is_file():
        command.extend(("--resume-state", str(checkpoint)))
    return command


def _record_state(
    *,
    product_id: str,
    request_path: Path,
    checkpoint_path: Path,
    execution_state_path: Path,
    checkpoint: Mapping[str, Any],
    cached_terminal: bool,
) -> str:
    scheduler_state = classify_checkpoint(checkpoint)
    payload = execution_state_payload(
        product_id=product_id,
        request_path=request_path,
        checkpoint_path=checkpoint_path,
        checkpoint=checkpoint,
        scheduler_state=scheduler_state,
        cached_terminal=cached_terminal,
    )
    _write_json(execution_state_path, payload)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)
    return scheduler_state


def main() -> int:
    args = parse_args()
    product_id, request_path, checkpoint_path, execution_state_path = execution_paths(
        args.request
    )
    request = _read_request(request_path)
    source_fingerprint = current_source_fingerprint(request_path, request)

    if checkpoint_path.is_file():
        checkpoint = _read_object(checkpoint_path, label="pipeline checkpoint")
        if (
            checkpoint.get("completed_stages")
            and checkpoint.get("execution_mode") != "execute"
        ):
            raise ValueError("product execution cannot resume a plan-mode checkpoint")
        if (
            checkpoint.get("status") == "EXECUTED"
            and checkpoint_matches_request(checkpoint, request, source_fingerprint)
        ):
            _record_state(
                product_id=product_id,
                request_path=request_path,
                checkpoint_path=checkpoint_path,
                execution_state_path=execution_state_path,
                checkpoint=checkpoint,
                cached_terminal=True,
            )
            return 0

    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        build_pipeline_command(request_path, checkpoint_path),
        cwd=ROOT,
        check=False,
    )
    if not checkpoint_path.is_file():
        return completed.returncode or 1

    checkpoint = _read_object(checkpoint_path, label="pipeline checkpoint")
    scheduler_state = _record_state(
        product_id=product_id,
        request_path=request_path,
        checkpoint_path=checkpoint_path,
        execution_state_path=execution_state_path,
        checkpoint=checkpoint,
        cached_terminal=False,
    )
    if scheduler_state in {"SUCCEEDED", "REVIEW_REQUIRED"}:
        return 0
    return completed.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
