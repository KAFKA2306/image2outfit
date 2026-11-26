#!/usr/bin/env python3
"""Run, checkpoint, or resume the canonical garment reconstruction pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from contract_io import digest, read_json, validate_schema_file
from image2outfit.audit import sha256_json, validate_stage_records, write_audit_bundle
from image2outfit.audit_schema import load_audit_schemas
from image2outfit.artifact_dag import ArtifactKind, ArtifactRef, PipelineArtifactDAG
from image2outfit.failure_contract import (
    failed_state_descriptor,
    failure_descriptor,
    stable_cause_code,
)
from image2outfit.pipeline import (
    PIPELINE_STAGES,
    ExecutionMode,
    new_pipeline_state,
    PipelineStage,
    resume_pipeline_state,
    run_langchain,
    run_langgraph,
    run_pipeline,
    validate_pipeline_state,
)
from pipeline_profile_contract import load_profile
from pipeline_source_fingerprint import pipeline_source_fingerprint
from pipeline_stage_adapters import build_registry

DEFAULT_PROFILE = Path("config/pipeline-profiles/garment-reconstruction-v1.json")
PIPELINE_STATE_SCHEMA = ROOT / "config/pipeline/pipeline-state.schema.v1.json"
REQUEST_SCHEMA = Path("config/pipeline/pipeline-request.schema.v1.json")
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
        help="Override request.profilePath. Otherwise the request or default profile is used.",
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


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _validate_request(request: dict[str, Any]) -> None:
    errors = validate_schema_file(request, ROOT / REQUEST_SCHEMA, "request")
    if errors:
        raise ValueError("invalid pipeline request: " + "; ".join(errors))


def _repo_path(path: Path, *, label: str) -> Path:
    resolved = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise ValueError(f"{label} escapes repository: {path}")
    return resolved


def _profile_path(args: argparse.Namespace, request: dict[str, Any]) -> Path:
    if args.profile is not None:
        return _repo_path(args.profile, label="profile")
    configured = request.get("profilePath")
    if configured is None:
        return _repo_path(DEFAULT_PROFILE, label="default profile")
    if not isinstance(configured, str) or not configured:
        raise ValueError("request.profilePath must be a non-empty string")
    return _repo_path(Path(configured), label="request.profilePath")


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _validate_persisted_pipeline_state(
    state: dict[str, Any], *, label: str = "pipeline state"
) -> None:
    errors = validate_schema_file(state, PIPELINE_STATE_SCHEMA, label)
    if errors:
        raise ValueError(
            "pipeline state schema validation failed: " + "; ".join(errors)
        )
    validate_pipeline_state(state)


def _read_pipeline_state(path: Path, *, label: str) -> dict[str, Any]:
    state = _read_object(path, label=label)
    _validate_persisted_pipeline_state(state, label=label)
    return state


def _write_pipeline_state_atomic(path: Path, state: dict[str, Any]) -> None:
    _validate_persisted_pipeline_state(state)
    _write_json_atomic(path, state)


def _record_product_handoff(result: dict[str, Any], checkpoint_path: Path) -> None:
    product_id = result.get("product_id")
    if not isinstance(product_id, str) or not product_id:
        raise ValueError("executed pipeline result is missing product_id")
    job_path = _repo_path(
        Path("config") / "products" / product_id / "job.json",
        label="product job",
    )
    job = read_json(job_path)
    manifest_rel = job.get("productManifestPath")
    if not isinstance(manifest_rel, str) or not manifest_rel:
        raise ValueError("product job is missing productManifestPath")
    manifest_path = _repo_path(Path(manifest_rel), label="product manifest")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"ProductManifest missing: {manifest_path}")
    import product_manifest_state

    product_manifest_state.record_workflow_attempt(
        manifest_path=manifest_path,
        job=job,
        checkpoint_path=checkpoint_path,
        expected_manifest_sha256=digest(manifest_path),
        root=ROOT,
    )


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


def _validate_resume_integrity(previous: dict[str, Any]) -> None:
    """Validate the successful checkpoint prefix before any reuse is created."""
    completed = list(previous.get("completed_stages", []))
    if not completed:
        return

    raw_records = previous.get("stage_records", [])
    if not isinstance(raw_records, list) or len(raw_records) < len(completed):
        raise ValueError(
            "resume checkpoint is missing audit records for the completed prefix"
        )
    records = raw_records[: len(completed)]
    validate_stage_records(
        records,
        expected_run_id=str(previous["run_id"]),
        expected_product_id=str(previous["product_id"]),
        canonical_stages=[stage.value for stage in PIPELINE_STAGES],
    )

    outputs = previous.get("outputs", {})
    for index, stage in enumerate(completed):
        state_output = outputs[stage]
        record = records[index]
        if record.get("output") != state_output:
            raise ValueError(f"resume checkpoint output mismatch for stage {stage}")
        if record.get("outputDigest") != sha256_json(state_output):
            raise ValueError(
                f"resume checkpoint output digest mismatch for stage {stage}"
            )


def _resume_or_reset(
    previous: dict[str, Any],
    *,
    request: dict[str, Any],
    expected: dict[str, str],
    mode: ExecutionMode,
    allow_verified_prefix_on_source_change: bool = False,
) -> dict[str, Any]:
    _validate_persisted_pipeline_state(previous, label="resume state")
    mismatches = _identity_mismatches(previous, expected)
    allowed_drift = {"sourceFingerprint"}
    if allow_verified_prefix_on_source_change and "sourceFingerprint" in mismatches:
        # A new product revision necessarily has different hypothesis-bound
        # artifact refs. Allow the explicit resume path to verify reusable
        # outputs; the artifact-DAG checks below will reject refs bound to the
        # previous revision and start the new run at its first affected stage.
        allowed_drift.add("revisionId")
    non_source_mismatches = [
        value for value in mismatches if value not in allowed_drift
    ]
    if non_source_mismatches:
        _assert_identity(previous, expected)
    if "sourceFingerprint" not in mismatches:
        _validate_resume_integrity(previous)
        return resume_pipeline_state(previous, execution_mode=mode)

    if allow_verified_prefix_on_source_change:
        _validate_resume_integrity(previous)
        prefix: list[str] = []
        outputs = previous.get("outputs", {})
        records = previous.get("stage_records", [])
        records_by_stage: dict[str, dict[str, Any]] = {}
        for record in records:
            if isinstance(record, dict) and isinstance(record.get("stage"), str):
                records_by_stage[record["stage"]] = record
        origin = str(previous.get("run_id", ""))
        history = previous.get("resume_history", [])
        if history and isinstance(history[0], dict):
            origin = str(history[0].get("parent_run_id") or origin)
        elif previous.get("parent_run_id"):
            origin = str(previous["parent_run_id"])
        avatar_sha256 = hashlib.sha256(
            expected["targetAvatar"].encode("utf-8")
        ).hexdigest()
        artifact_dag = PipelineArtifactDAG()
        for stage in previous.get("completed_stages", []):
            output = outputs.get(stage, {})
            stage_record = records_by_stage.get(stage, {})
            record_output = stage_record.get("output", {})
            raw_ref = output.get("artifactRef") if isinstance(output, dict) else None
            if (
                not isinstance(raw_ref, dict)
                or stage_record.get("status") not in {"PASS", "REUSED"}
                or not isinstance(record_output, dict)
                or record_output.get("mode") != "executed"
                or not isinstance(record_output.get("result"), dict)
                or record_output.get("artifactRef") != raw_ref
            ):
                break
            try:
                result_path = stage_record.get("resultPath")
                if not isinstance(result_path, str) or not result_path:
                    break
                stage_result = _read_object(
                    _repo_path(Path(result_path), label="resumed stage result"),
                    label="resumed stage result",
                )
                if stage_result != record_output["result"]:
                    break
                ref = ArtifactRef(
                    kind=ArtifactKind(str(raw_ref["kind"])),
                    producer_stage=PipelineStage(str(raw_ref["producer_stage"])),
                    garment_id=str(raw_ref["garment_id"]),
                    hypothesis_id=str(raw_ref["hypothesis_id"]),
                    candidate_id=str(raw_ref["candidate_id"]),
                    avatar_sha256=str(raw_ref["avatar_sha256"]),
                    content_sha256=str(raw_ref["content_sha256"]),
                    artifact_path=str(raw_ref["artifact_path"]),
                    schema_version=int(raw_ref.get("schema_version", 1)),
                )
                if (
                    ref.producer_stage.value != stage
                    or ref.kind != artifact_dag.contract(stage).produces
                    or ref.garment_id != expected["productId"]
                    or ref.hypothesis_id != expected["revisionId"]
                    or ref.candidate_id != origin
                    or ref.avatar_sha256 != avatar_sha256
                ):
                    break
                ref.verify_content(str(ROOT))
            except (KeyError, TypeError, ValueError, OSError):
                break
            prefix.append(stage)

        if prefix:
            reused = dict(previous)
            reused["completed_stages"] = prefix
            reused["outputs"] = {stage: outputs[stage] for stage in prefix}
            reused["stage_records"] = [records_by_stage[stage] for stage in prefix]
            reused["events"] = [
                event
                for event in previous.get("events", [])
                if isinstance(event, dict) and event.get("stage") in prefix
            ]
            reused["errors"] = []
            reused.pop("failure", None)
            reused["source_fingerprint"] = expected["sourceFingerprint"]
            resumed = resume_pipeline_state(reused, execution_mode=mode)
            resumed["resume_history"][-1]["source_fingerprint_drift"] = {
                "previous": str(previous.get("source_fingerprint", "")),
                "current": expected["sourceFingerprint"],
                "verifiedPrefix": len(prefix),
                "invalidatedStage": (
                    previous["completed_stages"][len(prefix)]
                    if len(prefix) < len(previous.get("completed_stages", []))
                    else resumed.get("current_stage", "")
                ),
            }
            return resumed

    state = _new_state(request, expected, mode)
    state["checkpoint_reset"] = {
        "reason": "source-or-revision-changed",
        "previousRunId": str(previous.get("run_id", "")),
        "previousRevisionId": str(previous.get("revision_id", "")),
        "revisionId": expected["revisionId"],
        "previousSourceFingerprint": str(previous.get("source_fingerprint", "")),
        "sourceFingerprint": expected["sourceFingerprint"],
    }
    return state


def _emit(args: argparse.Namespace, value: dict[str, Any]) -> int:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = _repo_path(args.output, label="output")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    sys.stdout.write(payload)
    return 1 if value.get("status") == "FAILED" else 0


def _emit_failure(
    args: argparse.Namespace,
    *,
    error_code: str,
    phase: str,
    exc: BaseException,
    stage: str | None = None,
) -> int:
    failure = failure_descriptor(
        error_code,
        phase,
        str(exc) or error_code,
        stage=stage,
        cause_code=stable_cause_code(exc),
    )
    return _emit(args, {"status": "FAILED", "failure": failure})


def main() -> int:
    args = parse_args()
    try:
        request_path = _repo_path(args.request, label="request")
        request = _read_object(request_path, label="request")
        _validate_request(request)
        product_id = str(request["productId"])
        target_avatar = str(request["targetAvatar"])
        source_reference = str(request["sourceReference"])
    except Exception as exc:  # noqa: BLE001 - CLI contract boundary
        return _emit_failure(
            args, error_code="INVALID_PIPELINE_INPUT", phase="request", exc=exc
        )

    try:
        profile_path = _profile_path(args, request)
        profile = load_profile(profile_path)
        _, record_schema, _, manifest_schema = load_audit_schemas(
            ROOT, profile["auditContract"]
        )
    except Exception as exc:  # noqa: BLE001 - CLI contract boundary
        return _emit_failure(
            args, error_code="PIPELINE_CONFIGURATION_INVALID", phase="profile", exc=exc
        )

    try:
        expected = {
            "productId": product_id,
            "targetAvatar": target_avatar,
            "sourceReference": source_reference,
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
                for key, value in _mapping(
                    request.get("variables"), "variables"
                ).items()
            },
        }
        mode = ExecutionMode.EXECUTE if args.execute else ExecutionMode.PLAN
    except Exception as exc:  # noqa: BLE001 - contract boundary
        return _emit_failure(
            args, error_code="PIPELINE_CONFIGURATION_INVALID", phase="contract", exc=exc
        )

    try:
        resume_path = args.resume_state
        if resume_path is None and args.execute and args.checkpoint_output:
            existing_checkpoint = _repo_path(
                args.checkpoint_output, label="checkpoint output"
            )
            if existing_checkpoint.is_file():
                resume_path = existing_checkpoint
        if resume_path:
            previous = _read_pipeline_state(
                _repo_path(resume_path, label="resume state"),
                label="resume state",
            )
            state = _resume_or_reset(
                previous,
                request=request,
                expected=expected,
                mode=mode,
                allow_verified_prefix_on_source_change=args.resume_state is not None,
            )
            if state.get("checkpoint_reset"):
                print(
                    "Ignoring stale resume checkpoint because pipeline sources changed.",
                    file=sys.stderr,
                )
        else:
            state = _new_state(request, expected, mode)
    except Exception as exc:  # noqa: BLE001 - resume boundary
        return _emit_failure(
            args, error_code="INVALID_RESUME_STATE", phase="resume", exc=exc
        )

    try:
        registry = build_registry(
            profile,
            execute=args.execute,
            bindings=_mapping(request.get("stageBindings"), "stageBindings"),
            variables=variables,
            tool_requirements=_mapping(
                request.get("toolRequirements"), "toolRequirements"
            ),
            tool_pins=_mapping(request.get("toolPins"), "toolPins"),
        )
    except Exception as exc:  # noqa: BLE001 - registry boundary
        return _emit_failure(
            args, error_code="PIPELINE_CONFIGURATION_INVALID", phase="registry", exc=exc
        )

    checkpoint: Callable[[dict[str, Any]], None] | None = (
        (lambda current: _write_pipeline_state_atomic(args.checkpoint_output, current))
        if args.checkpoint_output
        else None
    )
    try:
        if args.engine == "langgraph":
            result = run_langgraph(state, registry, checkpoint=checkpoint)
        elif args.engine == "langchain":
            result = run_langchain(state, registry, checkpoint=checkpoint)
        else:
            result = run_pipeline(state, registry, checkpoint=checkpoint)
    except RuntimeError as exc:
        if (
            args.engine in {"langchain", "langgraph"}
            and "not installed" in str(exc).lower()
        ):
            return _emit_failure(
                args,
                error_code="PIPELINE_ENGINE_UNAVAILABLE",
                phase="pipeline",
                exc=exc,
            )
        return _emit_failure(
            args, error_code="INTERNAL_PIPELINE_ERROR", phase="pipeline", exc=exc
        )
    except Exception as exc:  # noqa: BLE001 - pipeline boundary
        return _emit_failure(
            args, error_code="INTERNAL_PIPELINE_ERROR", phase="pipeline", exc=exc
        )

    result["toolPlan"] = registry.selection_plan()
    if result.get("status") == "FAILED":
        result["failure"] = failed_state_descriptor(result)

    try:
        audit_root = (
            args.audit_root if args.audit_root.is_absolute() else ROOT / args.audit_root
        )
        result["audit"] = write_audit_bundle(
            result,
            audit_root=audit_root,
            canonical_stages=[stage.value for stage in PIPELINE_STAGES],
            record_schema=record_schema,
            manifest_schema=manifest_schema,
        )
    except Exception as exc:  # noqa: BLE001 - audit publication boundary
        return _emit_failure(
            args, error_code="AUDIT_PUBLICATION_FAILED", phase="audit", exc=exc
        )

    if args.checkpoint_output:
        _write_pipeline_state_atomic(args.checkpoint_output, result)
    expected_status = "EXECUTED" if args.execute else "PLANNED"
    if result.get("status") != expected_status and result.get("status") != "FAILED":
        result["status"] = "FAILED"
        result["failure"] = failure_descriptor(
            "INTERNAL_PIPELINE_ERROR",
            "pipeline",
            f"pipeline finished with unexpected status: {result.get('status')}",
        )
    if args.execute:
        try:
            checkpoint_path = _repo_path(
                args.checkpoint_output, label="checkpoint output"
            )
            _record_product_handoff(result, checkpoint_path)
        except Exception as exc:  # noqa: BLE001 - product manifest handoff boundary
            return _emit_failure(
                args, error_code="PRODUCT_HANDOFF_FAILED", phase="handoff", exc=exc
            )
    return _emit(args, result)


if __name__ == "__main__":
    raise SystemExit(main())
