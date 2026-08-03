#!/usr/bin/env python3
"""Package one already validated candidate with its raw evidence."""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from typing import Any, Callable

from contract_io import digest, read_json, relative, repo_path, write_json


def _copy_evidence_document(
    source: Path,
    destination: Path,
    *,
    root: Path,
    copied: list[Path],
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    copied.append(destination)
    value = read_json(source)
    screenshot = value.get("runtimeScreenshot")
    if isinstance(screenshot, str) and screenshot:
        screenshot_path = repo_path(root, screenshot)
        runtime_destination = (
            destination.parent / "runtime" / screenshot_path.name
        )
        runtime_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(screenshot_path, runtime_destination)
        copied.append(runtime_destination)


def package_release(
    *,
    root: Path,
    job_path: Path,
    job: dict[str, Any],
    policy: dict[str, Any],
    candidate: Path,
    release: Path,
    candidate_manifest: dict[str, Any],
    candidate_hash: str,
    human_evidence: dict[str, dict[str, Any]],
    verify_candidate: Callable[
        [Path, dict[str, Any], Path, dict[str, Any]], list[str]
    ],
    now: Callable[[], str],
) -> dict[str, Any]:
    errors = verify_candidate(job_path, job, candidate, candidate_manifest)
    if job.get("adapterId") in policy.get("blockedReleaseAdapterIds", []):
        errors.append(f"adapter blocked from release: {job.get('adapterId')}")
    if errors:
        raise ValueError(
            "release packaging refused: " + "; ".join(errors)
        )

    package = release / "Package"
    shutil.copytree(candidate, package)
    copied = [path for path in package.rglob("*") if path.is_file()]

    human_root = package / "Evidence" / "Human"
    for kind, evidence_path_value in job.get("humanEvidence", {}).items():
        _copy_evidence_document(
            repo_path(root, evidence_path_value),
            human_root / f"{kind}.json",
            root=root,
            copied=copied,
        )

    commercial_source = repo_path(
        root, f"{job['productRoot']}/Evidence/Commercial"
    )
    if commercial_source.is_dir():
        commercial_destination = package / "Evidence" / "Commercial"
        shutil.copytree(commercial_source, commercial_destination)
        copied.extend(
            path
            for path in commercial_destination.rglob("*")
            if path.is_file()
        )

    evidence_summary = package / "Evidence" / "validated-human-evidence.json"
    write_json(
        evidence_summary,
        {
            "schemaVersion": 1,
            "candidateManifestSha256": candidate_hash,
            "evidence": human_evidence,
        },
    )
    copied.append(evidence_summary)

    release.mkdir(parents=True, exist_ok=True)
    files = [
        {
            "path": relative(release, path),
            "bytes": path.stat().st_size,
            "sha256": digest(path),
        }
        for path in sorted(set(copied))
    ]
    release_manifest = release / "release-manifest.json"
    write_json(
        release_manifest,
        {
            "schemaVersion": 2,
            "kind": "image2outfit-release",
            "jobId": job["id"],
            "productName": job["productName"],
            "adapterId": job["adapterId"],
            "releasedAt": now(),
            "sourceCommit": candidate_manifest.get("sourceCommit"),
            "candidateManifestSha256": candidate_hash,
            "files": files,
            "evidence": human_evidence,
            "decision": "GO",
        },
    )
    archive = release / f"{job['id']}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for path in sorted(release.rglob("*")):
            if path.is_file() and path != archive:
                output.write(path, path.relative_to(release))
    return {
        "releaseManifest": relative(root, release_manifest),
        "releaseManifestSha256": digest(release_manifest),
        "zip": {
            "path": relative(root, archive),
            "sha256": digest(archive),
            "bytes": archive.stat().st_size,
        },
    }
