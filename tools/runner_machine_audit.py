#!/usr/bin/env python3
"""Freeze, evaluate, compare, and ledger Runner-only machine audit requests."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.runner_audit import (  # noqa: E402
    Decision,
    MetricResult,
    MetricState,
    audit_result,
    evaluate_metrics,
    freeze_request_manifest,
    frozen_profile,
    pareto_decision,
    request_sha256,
    required_metric_ids,
    runner_complete,
    select_blocker,
    sha256_file,
    stop_reason,
    validate_request_manifest,
    verified_evidence_ratio,
    verify_artifacts,
)
from image2outfit.runner_loop import (  # noqa: E402
    blocker_stats,
    new_ledger,
    record_attempt,
    validate_ledger,
)

DEFAULT_PROFILE = ROOT / "contracts" / "quality" / "runner-only-machine-audit-v1.json"
HASH = re.compile(r"^[0-9a-f]{64}$")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def repo_path(text: str) -> Path:
    path = (ROOT / text).resolve()
    root = ROOT.resolve()
    if path != root and root not in path.parents:
        raise ValueError("path must stay inside repository")
    return path


def freeze_command(args: argparse.Namespace) -> int:
    draft = read_json(repo_path(args.request))
    profile = read_json(repo_path(args.profile))
    frozen = freeze_request_manifest(draft, profile)
    digest = request_sha256(frozen)
    output = repo_path(args.output)
    write_json(output, frozen)
    output.with_suffix(output.suffix + ".sha256").write_text(digest + "\n", encoding="utf-8")
    print(json.dumps({"requestSha256": digest, "output": output.relative_to(ROOT).as_posix()}, indent=2))
    return 0


def validate_command(args: argparse.Namespace) -> int:
    request = read_json(repo_path(args.request))
    validate_request_manifest(request)
    digest = request_sha256(request)
    for item in request["referenceImages"]:
        path = repo_path(str(item["path"]))
        if not path.is_file():
            raise ValueError(f"reference image missing: {item['path']}")
        if sha256_file(path) != item["sha256"]:
            raise ValueError(f"reference image hash mismatch: {item['path']}")
    print(json.dumps({"status": "PASS", "requestSha256": digest}, indent=2))
    return 0


def metric_from_json(metric_id: str, value: dict[str, Any]) -> MetricResult:
    return MetricResult(
        metric_id=metric_id,
        stage=str(value.get("stage") or ""),
        value=value.get("value"),
        threshold=value.get("threshold"),
        state=MetricState(str(value["state"])),
        producer=value.get("producer"),
        evidence_sha256=value.get("evidenceSha256"),
        cause=value.get("cause"),
        producer_version=value.get("producerVersion"),
    )


def candidate_identity(index: dict[str, Any]) -> tuple[str, str | None]:
    declared = index.get("candidateSha256")
    path_value = index.get("candidatePath")
    if not isinstance(declared, str) or not HASH.fullmatch(declared):
        return "", "CANDIDATE_HASH_MISSING"
    if not isinstance(path_value, str) or not path_value:
        return "", "CANDIDATE_PATH_MISSING"
    path = repo_path(path_value)
    if not path.is_file():
        return "", "CANDIDATE_MISSING"
    actual = sha256_file(path)
    if actual != declared:
        return "", "CANDIDATE_HASH_MISMATCH"
    return actual, None


def evaluate_command(args: argparse.Namespace) -> int:
    request = read_json(repo_path(args.request))
    validate_request_manifest(request)
    digest = request_sha256(request)
    profile = frozen_profile(request)
    ledger = read_json(repo_path(args.attempt_ledger))
    validate_ledger(ledger, digest)
    observations_payload = read_json(repo_path(args.observations))
    observations = observations_payload.get("metrics", observations_payload)
    if not isinstance(observations, dict):
        raise ValueError("observations.metrics must be an object")
    index = read_json(repo_path(args.evidence_index))
    artifacts = index.get("artifacts") if isinstance(index.get("artifacts"), list) else []
    evidence = index.get("evidence") if isinstance(index.get("evidence"), list) else []

    results = evaluate_metrics(profile, request, observations, root=ROOT)
    results["evidence.artifact_identity"] = verify_artifacts(
        artifacts, root=ROOT, product_id=str(request["productId"]), request_digest=digest
    )
    results["evidence.verified_ratio"] = verified_evidence_ratio(
        evidence, root=ROOT, product_id=str(request["productId"]), request_digest=digest
    )
    candidate_sha, candidate_error = candidate_identity(index)
    if not candidate_error and candidate_sha != ledger["currentCandidateSha256"]:
        candidate_error = "CANDIDATE_LEDGER_HASH_MISMATCH"
    if candidate_error:
        results["evidence.artifact_identity"] = MetricResult(
            "evidence.artifact_identity",
            "reproducibility-evidence",
            None,
            0,
            MetricState.UNVERIFIED,
            "artifact-verifier",
            None,
            candidate_error,
            "runner-audit-v1",
        )

    attempts = len(ledger["attempts"])
    final_decision = None
    if attempts:
        final_decision = Decision(str(ledger["attempts"][-1]["decision"]))
    required = required_metric_ids(profile, request)
    complete = runner_complete(
        results,
        required_ids=required,
        request_digest=digest,
        audit_request_digest=digest,
        candidate_sha256=candidate_sha,
        audit_candidate_sha256=str(ledger["currentCandidateSha256"]),
        final_attempt_decision=final_decision,
    )
    blocker = select_blocker(profile, results)
    elapsed = float(index.get("elapsedMinutes", 0) or 0)
    blocker_attempts = 0
    accepted = 0
    if blocker:
        blocker_attempts, accepted = blocker_stats(ledger, blocker)
    stop = stop_reason(
        complete=complete,
        failed_hard=bool(index.get("failedHard", False)),
        total_attempts=attempts,
        elapsed_minutes=elapsed,
        max_total_attempts=int(request["maxTotalAttempts"]),
        max_runner_minutes=int(request["maxRunnerMinutes"]),
        blocker_attempts=blocker_attempts,
        max_attempts_per_blocker=int(request["maxAttemptsPerBlocker"]),
        accepted_for_blocker=accepted,
    )
    result = audit_result(
        request_digest=digest,
        candidate_sha256=candidate_sha,
        results=results,
        attempts=attempts,
        stop=stop,
    )
    result["runnerComplete"] = complete
    result["highestBlocker"] = blocker
    result["requiredMetricIds"] = required
    result["attemptLedgerSha256"] = sha256_file(repo_path(args.attempt_ledger))
    output = repo_path(args.output)
    write_json(output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if complete else 2


def compare_command(args: argparse.Namespace) -> int:
    request = read_json(repo_path(args.request))
    profile = frozen_profile(request)
    before = read_json(repo_path(args.before))
    after = read_json(repo_path(args.after))
    before_metrics = {
        key: metric_from_json(key, value)
        for key, value in before.get("metrics", {}).items()
        if isinstance(value, dict)
    }
    after_metrics = {
        key: metric_from_json(key, value)
        for key, value in after.get("metrics", {}).items()
        if isinstance(value, dict)
    }
    decision = pareto_decision(profile, before_metrics, after_metrics)
    print(json.dumps({"decision": decision.value}, indent=2))
    return 0 if decision is Decision.KEEP else 2


def ledger_init_command(args: argparse.Namespace) -> int:
    request = read_json(repo_path(args.request))
    digest = request_sha256(request)
    candidate = repo_path(args.candidate)
    if not candidate.is_file():
        raise ValueError("initial candidate does not exist")
    ledger = new_ledger(digest, sha256_file(candidate))
    write_json(repo_path(args.output), ledger)
    print(json.dumps(ledger, indent=2))
    return 0


def ledger_record_command(args: argparse.Namespace) -> int:
    request = read_json(repo_path(args.request))
    digest = request_sha256(request)
    ledger_path = repo_path(args.ledger)
    ledger = read_json(ledger_path)
    validate_ledger(ledger, digest)
    before_candidate = repo_path(args.before_candidate)
    after_candidate = repo_path(args.after_candidate)
    before_audit = repo_path(args.before_audit)
    after_audit = repo_path(args.after_audit)
    for path in (before_candidate, after_candidate, before_audit, after_audit):
        if not path.is_file():
            raise ValueError(f"ledger input missing: {path.relative_to(ROOT)}")
    updated = record_attempt(
        ledger,
        request_sha256=digest,
        blocker=args.blocker,
        before_candidate_sha256=sha256_file(before_candidate),
        after_candidate_sha256=sha256_file(after_candidate),
        before_audit_sha256=sha256_file(before_audit),
        after_audit_sha256=sha256_file(after_audit),
        patch_id=args.patch_id,
        decision=Decision(args.decision),
        elapsed_minutes=args.elapsed_minutes,
    )
    write_json(ledger_path, updated)
    print(json.dumps(updated, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    freeze = commands.add_parser("freeze")
    freeze.add_argument("--request", required=True)
    freeze.add_argument("--profile", default=DEFAULT_PROFILE.relative_to(ROOT).as_posix())
    freeze.add_argument("--output", required=True)

    validate = commands.add_parser("validate")
    validate.add_argument("--request", required=True)

    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--request", required=True)
    evaluate.add_argument("--observations", required=True)
    evaluate.add_argument("--evidence-index", required=True)
    evaluate.add_argument("--attempt-ledger", required=True)
    evaluate.add_argument("--output", required=True)

    compare = commands.add_parser("compare")
    compare.add_argument("--request", required=True)
    compare.add_argument("--before", required=True)
    compare.add_argument("--after", required=True)

    ledger_init = commands.add_parser("ledger-init")
    ledger_init.add_argument("--request", required=True)
    ledger_init.add_argument("--candidate", required=True)
    ledger_init.add_argument("--output", required=True)

    ledger_record = commands.add_parser("ledger-record")
    ledger_record.add_argument("--request", required=True)
    ledger_record.add_argument("--ledger", required=True)
    ledger_record.add_argument("--blocker", required=True)
    ledger_record.add_argument("--patch-id", required=True)
    ledger_record.add_argument("--decision", choices=["KEEP", "REVERT"], required=True)
    ledger_record.add_argument("--before-candidate", required=True)
    ledger_record.add_argument("--after-candidate", required=True)
    ledger_record.add_argument("--before-audit", required=True)
    ledger_record.add_argument("--after-audit", required=True)
    ledger_record.add_argument("--elapsed-minutes", type=float, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        handlers = {
            "freeze": freeze_command,
            "validate": validate_command,
            "evaluate": evaluate_command,
            "compare": compare_command,
            "ledger-init": ledger_init_command,
            "ledger-record": ledger_record_command,
        }
        return handlers[args.command](args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"runner-machine-audit: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
