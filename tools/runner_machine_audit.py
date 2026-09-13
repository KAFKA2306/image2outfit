#!/usr/bin/env python3
"""Freeze and evaluate Runner-only machine audit requests."""
from __future__ import annotations

import argparse
import json
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

DEFAULT_PROFILE = ROOT / "contracts" / "quality" / "runner-only-machine-audit-v1.json"


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
    output.with_suffix(output.suffix + ".sha256").write_text(
        digest + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"requestSha256": digest, "output": output.relative_to(ROOT).as_posix()},
            indent=2,
        )
    )
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
    )


def evaluate_command(args: argparse.Namespace) -> int:
    request = read_json(repo_path(args.request))
    validate_request_manifest(request)
    digest = request_sha256(request)
    profile = frozen_profile(request)
    observations_payload = read_json(repo_path(args.observations))
    observations = observations_payload.get("metrics", observations_payload)
    if not isinstance(observations, dict):
        raise ValueError("observations.metrics must be an object")
    index = read_json(repo_path(args.evidence_index))
    artifacts = index.get("artifacts")
    evidence = index.get("evidence")
    if not isinstance(artifacts, list):
        artifacts = []
    if not isinstance(evidence, list):
        evidence = []

    results = evaluate_metrics(profile, request, observations, root=ROOT)
    results["evidence.artifact_identity"] = verify_artifacts(
        artifacts,
        root=ROOT,
        product_id=str(request["productId"]),
        request_digest=digest,
    )
    results["evidence.verified_ratio"] = verified_evidence_ratio(
        evidence,
        root=ROOT,
        product_id=str(request["productId"]),
        request_digest=digest,
    )

    candidate_sha = index.get("candidateSha256")
    if not isinstance(candidate_sha, str) or len(candidate_sha) != 64:
        candidate_sha = ""
    required = required_metric_ids(profile, request)
    complete = runner_complete(
        results,
        required_ids=required,
        request_digest=digest,
        audit_request_digest=digest,
        candidate_sha256=candidate_sha,
        audit_candidate_sha256=candidate_sha,
        final_attempt_decision=None,
    )
    blocker = select_blocker(profile, results)
    attempts = int(index.get("attempts", 0) or 0)
    elapsed = float(index.get("elapsedMinutes", 0) or 0)
    blocker_attempts = int(index.get("blockerAttempts", 0) or 0)
    accepted = int(index.get("acceptedForBlocker", 0) or 0)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    freeze = commands.add_parser("freeze")
    freeze.add_argument("--request", required=True)
    freeze.add_argument(
        "--profile", default=DEFAULT_PROFILE.relative_to(ROOT).as_posix()
    )
    freeze.add_argument("--output", required=True)

    validate = commands.add_parser("validate")
    validate.add_argument("--request", required=True)

    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--request", required=True)
    evaluate.add_argument("--observations", required=True)
    evaluate.add_argument("--evidence-index", required=True)
    evaluate.add_argument("--output", required=True)

    compare = commands.add_parser("compare")
    compare.add_argument("--request", required=True)
    compare.add_argument("--before", required=True)
    compare.add_argument("--after", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "freeze":
            return freeze_command(args)
        if args.command == "validate":
            return validate_command(args)
        if args.command == "evaluate":
            return evaluate_command(args)
        if args.command == "compare":
            return compare_command(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"runner-machine-audit: {exc}", file=sys.stderr)
        return 1
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
