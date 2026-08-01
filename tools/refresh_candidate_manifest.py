#!/usr/bin/env python3
"""Rebuild a candidate manifest after deterministic Unity post-processing."""
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

import release_gate as gate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True, type=Path)
    args = parser.parse_args()
    job_path = args.job.resolve()
    job, policy = gate.load(job_path)
    artifact = gate.path(job["artifactDir"])
    candidate = gate.path(job["candidateDir"])
    preview_passed, previews = gate.preview_gate(job, policy)
    if not preview_passed:
        raise RuntimeError("preview gate failed during candidate refresh")

    shutil.rmtree(candidate, ignore_errors=True)
    copied: list[Path] = []
    for source in gate.candidate_files(job, policy):
        destination = candidate / "UnityAssets" / source.relative_to(gate.ROOT / "Assets")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(destination)
    for view, value in job["previewPaths"].items():
        source = gate.path(value)
        destination = candidate / "Preview" / f"{view}.png"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(destination)

    manifest_path = candidate / "candidate-manifest.json"
    gate.write(
        manifest_path,
        {
            "schemaVersion": 2,
            "kind": "image2outfit-candidate",
            "jobId": job["id"],
            "productName": job["productName"],
            "adapterId": job["adapterId"],
            "runId": os.environ.get("IMAGE2OUTFIT_RUN_ID")
            or os.environ.get("GITHUB_RUN_ID")
            or gate.now(),
            "createdAt": gate.now(),
            "sourceCommit": os.environ.get("GITHUB_SHA", "local"),
            "inputHashes": gate.inputs(job_path, job),
            "files": gate.manifest(copied, candidate),
            "postprocessing": [
                "external Unity materials extracted from FBX",
                "outfit and integrated prefabs remapped to product materials",
            ],
            "releaseDecision": "REVIEW_REQUIRED",
        },
    )
    audit_path = artifact / "audit.json"
    audit = gate.read(audit_path)
    audit.update(
        {
            "schemaVersion": 2,
            "phase": "candidate",
            "jobId": job["id"],
            "adapterId": job["adapterId"],
            "checkedAt": gate.now(),
            "decision": "REVIEW_REQUIRED",
            "releaseEligible": False,
            "candidateManifest": gate.rel(manifest_path),
            "candidateManifestSha256": gate.digest(manifest_path),
            "previews": previews,
            "postprocessed": True,
            "note": "Candidate was refreshed after deterministic Unity material extraction. Human visual, pose and VRChat runtime evidence remain mandatory.",
        }
    )
    gate.write(audit_path, audit)
    print(gate.digest(manifest_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
