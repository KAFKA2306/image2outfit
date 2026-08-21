from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API_VERSION = "2026-03-10"
ROOT = Path(__file__).resolve().parents[1]
MERGE_POLICY = ROOT / "config" / "pr-merge-policy.json"


def load_merge_gate_contract(root: Path = ROOT) -> tuple[str, str]:
    policy_path = root / "config" / "pr-merge-policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8-sig"))
    gate = policy.get("mergeGate") if isinstance(policy, dict) else None
    if not isinstance(gate, dict):
        raise ValueError("pr-merge-policy.json mergeGate is required")
    workflow_file = gate.get("workflowFile")
    workflow_name = gate.get("workflowName")
    if (
        not isinstance(workflow_file, str)
        or not workflow_file
        or Path(workflow_file).name != workflow_file
    ):
        raise ValueError("mergeGate.workflowFile must be a workflow file name")
    if not isinstance(workflow_name, str) or not workflow_name:
        raise ValueError("mergeGate.workflowName is required")
    return workflow_file, workflow_name


def evaluate_release_provenance(
    *,
    release_ref: str,
    release_sha: str,
    default_branch: str,
    associated_pulls: list[dict[str, Any]],
    workflow_runs: list[dict[str, Any]],
    merge_gate_name: str | None = None,
) -> dict[str, Any]:
    if merge_gate_name is None:
        _, merge_gate_name = load_merge_gate_contract()

    expected_ref = f"refs/heads/{default_branch}"
    if release_ref != expected_ref:
        return {
            "state": "BLOCKED",
            "failure_class": "NON_DEFAULT_BRANCH",
            "release_sha": release_sha,
            "release_ref": release_ref,
        }

    merged = [
        pr
        for pr in associated_pulls
        if pr.get("merged_at")
        and pr.get("base", {}).get("ref") == default_branch
        and pr.get("merge_commit_sha") == release_sha
    ]
    if len(merged) != 1:
        return {
            "state": "BLOCKED",
            "failure_class": "MERGED_PR_PROVENANCE_MISSING",
            "release_sha": release_sha,
            "release_ref": release_ref,
            "associated_pr_count": len(associated_pulls),
            "matching_merged_pr_count": len(merged),
        }

    pr = merged[0]
    head_sha = pr.get("head", {}).get("sha")
    if not head_sha:
        return {
            "state": "BLOCKED",
            "failure_class": "PR_HEAD_SHA_MISSING",
            "release_sha": release_sha,
            "pr_number": pr.get("number"),
        }

    matching_runs = [
        run
        for run in workflow_runs
        if run.get("name") == merge_gate_name and run.get("head_sha") == head_sha
    ]
    matching_runs.sort(key=lambda run: run.get("created_at") or "", reverse=True)
    latest = matching_runs[0] if matching_runs else None
    if latest is None:
        return {
            "state": "BLOCKED",
            "failure_class": "MERGE_GATE_RUN_MISSING",
            "release_sha": release_sha,
            "pr_number": pr.get("number"),
            "pr_head_sha": head_sha,
        }
    if latest.get("status") != "completed" or latest.get("conclusion") != "success":
        return {
            "state": "BLOCKED",
            "failure_class": "MERGE_GATE_NOT_SUCCESSFUL",
            "release_sha": release_sha,
            "pr_number": pr.get("number"),
            "pr_head_sha": head_sha,
            "merge_gate_run_id": latest.get("id"),
            "merge_gate_status": latest.get("status"),
            "merge_gate_conclusion": latest.get("conclusion"),
        }

    return {
        "state": "VERIFIED",
        "failure_class": None,
        "release_sha": release_sha,
        "release_ref": release_ref,
        "pr_number": pr.get("number"),
        "pr_head_sha": head_sha,
        "merge_gate_run_id": latest.get("id"),
        "merge_gate_run_url": latest.get("html_url"),
        "merge_gate_conclusion": latest.get("conclusion"),
    }


def github_json(url: str, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "image2outfit-release-provenance-gate",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def collect_receipt(
    repository: str, release_ref: str, release_sha: str, default_branch: str, token: str
) -> dict[str, Any]:
    workflow_file, merge_gate_name = load_merge_gate_contract()
    base = f"https://api.github.com/repos/{repository}"
    pulls = github_json(f"{base}/commits/{release_sha}/pulls?per_page=100", token)

    head_shas = [
        pr.get("head", {}).get("sha")
        for pr in pulls
        if pr.get("merged_at")
        and pr.get("base", {}).get("ref") == default_branch
        and pr.get("merge_commit_sha") == release_sha
        and pr.get("head", {}).get("sha")
    ]
    runs: list[dict[str, Any]] = []
    for head_sha in sorted(set(head_shas)):
        query = urllib.parse.urlencode(
            {"event": "pull_request", "head_sha": head_sha, "per_page": 100}
        )
        payload = github_json(
            f"{base}/actions/workflows/{workflow_file}/runs?{query}", token
        )
        runs.extend(payload.get("workflow_runs", []))

    return evaluate_release_provenance(
        release_ref=release_ref,
        release_sha=release_sha,
        default_branch=default_branch,
        associated_pulls=pulls,
        workflow_runs=runs,
        merge_gate_name=merge_gate_name,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail closed unless a release revision is current main, came through a merged PR, "
            "and that PR's exact-head merge gate succeeded. Product release quality is checked "
            "separately by production_gate.py --mode release."
        )
    )
    parser.add_argument("--repository", required=True)
    parser.add_argument("--ref", required=True, dest="release_ref")
    parser.add_argument("--sha", required=True, dest="release_sha")
    parser.add_argument("--default-branch", default="main")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is required")

    receipt = collect_receipt(
        repository=args.repository,
        release_ref=args.release_ref,
        release_sha=args.release_sha,
        default_branch=args.default_branch,
        token=token,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    if receipt["state"] != "VERIFIED":
        raise SystemExit(f"release provenance blocked: {receipt['failure_class']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
