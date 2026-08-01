#!/usr/bin/env python3
"""Create the three release-gate evidence files from an explicit approval record."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import release_gate as gate


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    args = parser.parse_args()
    job_path = args.job.resolve()
    job, policy = gate.load(job_path)
    approval = read(args.approval.resolve())
    candidate_manifest = gate.path(job["candidateDir"]) / "candidate-manifest.json"
    if not candidate_manifest.is_file():
        raise FileNotFoundError(f"candidate manifest missing: {candidate_manifest}")
    candidate_hash = digest(candidate_manifest)

    required = {
        "schemaVersion": approval.get("schemaVersion") == 1,
        "jobId": approval.get("jobId") == job["id"],
        "adapterId": approval.get("adapterId") == job["adapterId"],
        "candidateManifestSha256": approval.get("candidateManifestSha256")
        == candidate_hash,
        "reviewer": bool(approval.get("reviewer")),
        "checkedAt": bool(approval.get("checkedAt")),
        "decision": approval.get("decision") == "APPROVE",
    }
    failed = [name for name, passed in required.items() if not passed]
    if failed:
        raise ValueError("approval record failed: " + ", ".join(failed))

    scores = approval.get("visualScores", {})
    for name in ("silhouette", "fit", "material", "presentation"):
        if not isinstance(scores.get(name), (int, float)) or scores[name] < policy["minimumVisualScore"]:
            raise ValueError(f"visual score below policy: {name}")
    poses = approval.get("poses", {})
    failed_poses = [name for name in policy["requiredPoses"] if poses.get(name) != "PASS"]
    if failed_poses:
        raise ValueError("pose review failed: " + ", ".join(failed_poses))
    if approval.get("vrchatBuildAndTest") != "PASS":
        raise ValueError("VRChat Build & Test approval is not PASS")
    if approval.get("testedInVRChat") is not True:
        raise ValueError("testedInVRChat must be true")

    common = {
        "schemaVersion": 2,
        "jobId": job["id"],
        "adapterId": job["adapterId"],
        "candidateManifestSha256": candidate_hash,
        "status": "PASS",
        "checkedAt": approval["checkedAt"],
        "reviewer": approval["reviewer"],
    }
    evidence = {
        "visual-review": {
            **common,
            "kind": "visual-review",
            "scores": scores,
            "criticalDefects": 0,
            "reviewedAssets": approval.get("reviewedAssets", []),
            "notes": approval.get("visualNotes", ""),
        },
        "pose-penetration-review": {
            **common,
            "kind": "pose-penetration-review",
            "poses": poses,
            "criticalPenetrations": 0,
            "notes": approval.get("poseNotes", ""),
        },
        "vrchat-runtime-review": {
            **common,
            "kind": "vrchat-runtime-review",
            "vrchatBuildAndTest": "PASS",
            "testedInVRChat": True,
            "runtimeScreenshot": approval.get("runtimeScreenshot", ""),
            "notes": approval.get("runtimeNotes", ""),
        },
    }
    for kind, value in evidence.items():
        write(gate.path(job["humanEvidence"][kind]), value)
    print(json.dumps({"passed": True, "candidateManifestSha256": candidate_hash}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
