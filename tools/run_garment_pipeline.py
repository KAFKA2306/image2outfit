#!/usr/bin/env python3
"""Run, checkpoint, or resume the canonical garment reconstruction pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from image2outfit.audit import write_audit_bundle
from image2outfit.pipeline import (
    PIPELINE_STAGES,
    ExecutionMode,
    new_pipeline_state,
    resume_pipeline_state,
    run_langchain,
    run_langgraph,
    run_pipeline,
    validate_pipeline_state,
)
from pipeline_source_fingerprint import pipeline_source_fingerprint
from pipeline_stage_adapters import build_registry, load_profile

IDENTITY_FIELDS = {
    "product_id": "productId",
    "target_avatar": "targetAvatar",
    "source_reference": "sourceReference",
    "profile_id": "profileId",
    "revision_id": "revisionId",
    "source_fingerprint": "sourceFingerprint",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument(
        "--profile",
        type=Path,
        default=ROOT / "config/pipeline-profiles/garment-reconstruction-v1.json",
    )
    parser.add_argument(
        "--engine",
        choices=("deterministic", "langchain", "langgraph"),
        default="deterministic",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resume-state", type=Path)
    parser.add_argument("--checkpoint-output", type=Path)
    parser.add_argument(
        "--audit-root",
        type=Path,
        default=Path(".image2outfit/audit"),
        help="Repository-relative root for immutable per-run audit bundles.",
    )
    return parser.parse_args()


def _mapping(value: object, label: str) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"request.{label} must be an object")
    return value


def _repo_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _identity_mismatches(state: dict[str, Any], expected: dict[str, str]) -> list[str]:
    return [
        request_name
        for state_name, request_name in IDENTITY_FIELDS.items()
        if str(state.get(state_name, "")) != expected[request_name]
    ]


def _assert_identity(state: dict[str, Any], expected: dict[str, str]) -> None:
    mismatches = _identity_mismatches(state, expected)
    if mismatches:
        raise ValueError(
            "resume checkpoint identity does not match request: "
            + ", ".join(mismatches)
        )


def _new_state(
    request: dict[str, Any], expected: dict[str, str], mode: ExecutionMode
) -> dict[str, Any]:
    run_id = request.get("runId")
    if run_id is not None and (not isinstance(run_id, str) or not run_id):
        raise ValueError("request.runId must be a non-empty string when provided")
    state = new_pipeline_state(
        product_id=expected["productId"],
        target_avatar=expected["targetAvatar"],
        source_reference=expected["sourceReference"],
        profile_id=expected["profileId"],
        revision_id=expected["revisionId"],
        execution_mode=mode,
        run_id=run_id,
    )
    state["source_fingerprint"] = expected["sourceFingerprint"]
    return state


def main() -> int:
    args = parse_args()
    request_path = _repo_path(args.request)
    profile_path = _repo_path(args.profile)
    request = _read_object(request_path, label="request")
    if request.get("schemaVersion") != 1:
        raise ValueError("request.schemaVersion must be 1")
    profile = load_profile(profile_path)
    product_id = str(request["productId"])
    expected = {
        "productId": product_id,
        "targetAvatar": str(request["targetAvatar"]),
        "sourceReference": str(request["sourceReference"]),
        "profileId": str(profile["profileId"]),
        "revisionId": str(request.get("revisionId", "")),
        "sourceFingerprint": pipeline_source_fingerprint(
            ROOT,
            product_id=product_id,
            request_path=request_path,
            profile_path=profile_path,
        ),
    }
    variables = {
        **expected,
        **{
            str(key): str(value)
            for key, value in _mapping(request.get("variables"), "variables").items()
        },
    }
    mode = ExecutionMode.EXECUTE if args.execute else ExecutionMode.PLAN
    if args.resume_state:
        previous = _read_object(_repo_path(args.resume_state), label="resume state")
        validate_pipeline_state(previous)
        mismatches = _identity_mismatches(previous, expected)
        non_source_mismatches = [
            value for value in mismatches if value != "sourceFingerprint"
        ]
        if non_source_mismatches:
            _assert_identity(previous, expected)
        if "sourceFingerprint" in mismatches:
            state = _new_state(request, expected, mode)
            state["checkpoint_reset"] = {
                "reason": "source-fingerprint-changed",
                "previousRunId": str(previous.get("run_id", "")),
                "previousSourceFingerprint": str(
                    previous.get("source_fingerprint", "")
                ),
                "sourceFingerprint": expected["sourceFingerprint"],
            }
            print(
                "Ignoring stale resume checkpoint because pipeline sources changed.",
                file=sys.stderr,
            )
        else:
            state = resume_pipeline_state(previous, execution_mode=mode)
    else:
        state = _new_state(request, expected, mode)

    registry = build_registry(
        profile,
        execute=args.execute,
        bindings=_mapping(request.get("stageBindings"), "stageBindings"),
        variables=variables,
    )
    checkpoint = (
        (lambda current: _write_json_atomic(args.checkpoint_output, current))
        if args.checkpoint_output
        else None
    )
    if args.engine == "langgraph":
        result = run_langgraph(state, registry)
    elif args.engine == "langchain":
        result = run_langchain(state, registry)
    else:
        result = run_pipeline(state, registry, checkpoint=checkpoint)

    audit_root = (
        args.audit_root if args.audit_root.is_absolute() else ROOT / args.audit_root
    )
    result["audit"] = write_audit_bundle(
        result,
        audit_root=audit_root,
        canonical_stages=[stage.value for stage in PIPELINE_STAGES],
    )
    if args.checkpoint_output:
        _write_json_atomic(args.checkpoint_output, result)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        _write_json_atomic(args.output, result)
    print(payload)
    expected_status = "EXECUTED" if args.execute else "PLANNED"
    return 0 if result.get("status") == expected_status else 1


if __name__ == "__main__":
    raise SystemExit(main())
