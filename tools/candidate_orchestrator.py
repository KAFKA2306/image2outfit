#!/usr/bin/env python3
"""Build and promote one technically valid, policy-bound candidate."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import audit_research_baseline
import production_contract as contract
import release_gate as legacy
from runtime_transaction import DirectoryTransaction


def _augment_audit(artifact: Path, values: dict[str, Any]) -> None:
    audit_path = artifact / "audit.json"
    audit = legacy.read(audit_path)
    audit.setdefault("schemaVersion", 2)
    state = audit.setdefault("stateProtection", {})
    if not isinstance(state, dict):
        state = {}
        audit["stateProtection"] = state
    state.update(values)
    legacy.write(audit_path, audit)


def _research_state() -> tuple[dict[str, Any], dict[str, Any], str]:
    report = audit_research_baseline.audit(legacy.ROOT)
    baseline_path = audit_research_baseline.BASELINE_PATH
    baseline = legacy.read(baseline_path)
    baseline_hash = (
        legacy.digest(baseline_path) if baseline_path.is_file() else ""
    )
    return report, baseline, baseline_hash


def _write_research_failure(
    artifact: Path,
    job: dict[str, Any],
    report: dict[str, Any],
) -> None:
    artifact.mkdir(parents=True, exist_ok=True)
    legacy.write(artifact / "research-baseline.json", report)
    legacy.write(
        artifact / "audit.json",
        {
            "schemaVersion": 2,
            "phase": "candidate",
            "jobId": job["id"],
            "adapterId": job["adapterId"],
            "checkedAt": legacy.now(),
            "decision": "NO-GO",
            "releaseEligible": False,
            "stages": {
                "researchBaseline": {
                    "passed": False,
                    "errors": report.get("errors", []),
                    "warnings": report.get("warnings", []),
                }
            },
            "note": (
                "Candidate generation is blocked until the current "
                "primary-source research baseline passes."
            ),
        },
    )


def _bind_research_to_candidate(
    candidate: Path,
    artifact: Path,
    report: dict[str, Any],
    baseline: dict[str, Any],
    baseline_hash: str,
) -> None:
    manifest_path = candidate / "candidate-manifest.json"
    manifest = legacy.read(manifest_path)
    if not manifest_path.is_file() or not manifest:
        raise RuntimeError(
            "candidate manifest is missing after a successful candidate run"
        )
    manifest["researchBaseline"] = {
        "path": report["path"],
        "baselineId": baseline["baselineId"],
        "surveyYear": baseline["surveyYear"],
        "reviewedAt": baseline["reviewedAt"],
        "sha256": baseline_hash,
        "requiredCapabilities": baseline["requiredCapabilities"],
    }
    legacy.write(manifest_path, manifest)

    audit_path = artifact / "audit.json"
    audit = legacy.read(audit_path)
    stages = audit.setdefault("stages", {})
    stages["researchBaseline"] = {
        "passed": True,
        "baselineId": baseline["baselineId"],
        "surveyYear": baseline["surveyYear"],
        "reviewedAt": baseline["reviewedAt"],
        "sha256": baseline_hash,
        "methodCount": report.get("methodCount"),
        "productionCoverage": report.get("productionCoverage", []),
        "warnings": report.get("warnings", []),
    }
    audit["candidateManifestSha256"] = legacy.digest(manifest_path)
    legacy.write(audit_path, audit)


def _bind_pose_contract_to_candidate(
    candidate: Path,
    artifact: Path,
    job: dict[str, Any],
    policy: dict[str, Any],
) -> list[str]:
    manifest_path = candidate / "candidate-manifest.json"
    manifest = legacy.read(manifest_path)
    if not manifest_path.is_file() or not manifest:
        return ["candidate manifest is missing before pose binding"]

    errors: list[str] = []
    pose_records: dict[str, Any] = {}
    seen_hashes: set[str] = set()
    files = manifest.get("files")
    if not isinstance(files, list):
        return ["candidate manifest files are invalid"]

    for pose, source_value in contract.required_pose_paths(job, policy).items():
        source = legacy.path(source_value)
        destination = candidate / "Pose" / f"{pose}.png"
        if not source.is_file():
            errors.append(f"required pose image missing: {source_value}")
            continue
        try:
            width, height = legacy.png_size(source)
        except (OSError, ValueError) as exc:
            errors.append(f"required pose image invalid: {source_value}: {exc}")
            continue
        source_hash = legacy.digest(source)
        if source_hash in seen_hashes:
            errors.append(f"required pose image is duplicated by content: {pose}")
            continue
        seen_hashes.add(source_hash)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        record = {
            "path": destination.relative_to(candidate).as_posix(),
            "bytes": destination.stat().st_size,
            "sha256": source_hash,
        }
        files.append(record)
        pose_records[pose] = {
            **record,
            "sourcePath": source_value,
            "width": width,
            "height": height,
        }

    if errors:
        return errors
    manifest["poseContract"] = {
        "source": "config/release-policy.json#requiredPoses",
        "requiredPoses": list(policy.get("requiredPoses", [])),
        "poses": pose_records,
    }
    legacy.write(manifest_path, manifest)

    audit = legacy.read(artifact / "audit.json")
    stages = audit.setdefault("stages", {})
    stages["poseContract"] = {
        "passed": True,
        "requiredPoses": list(policy.get("requiredPoses", [])),
        "poses": pose_records,
    }
    audit["candidateManifestSha256"] = legacy.digest(manifest_path)
    legacy.write(artifact / "audit.json", audit)
    return []


def _record_candidate_failure(
    artifact: Path,
    errors: list[str],
    stage: str,
) -> None:
    audit_path = artifact / "audit.json"
    audit = legacy.read(audit_path)
    audit.setdefault("schemaVersion", 2)
    audit["decision"] = "NO-GO"
    audit["releaseEligible"] = False
    stages = audit.setdefault("stages", {})
    stages[stage] = {"passed": False, "errors": errors}
    audit["errors"] = list(dict.fromkeys([*audit.get("errors", []), *errors]))
    legacy.write(audit_path, audit)


def _run_candidate(job_path: Path, job: dict[str, Any], policy: dict[str, Any]) -> int:
    candidate = legacy.path(job["candidateDir"])
    release = legacy.path(job["releaseDir"])
    artifact = legacy.path(job["artifactDir"])
    product_root = legacy.path(job["productRoot"])
    research, baseline, baseline_hash = _research_state()
    if research.get("passed") is not True:
        _write_research_failure(artifact, job, research)
        return 2

    candidate_tx = DirectoryTransaction(candidate)
    release_tx = DirectoryTransaction(release)
    workspace_tx = contract.WorkspaceSnapshot(product_root)
    candidate_had_original = candidate_tx.begin()
    release_started = False
    release_had_original = False
    workspace_started = False
    workspace_had_original = False

    try:
        release_had_original = release_tx.begin()
        release_started = True
        workspace_had_original = workspace_tx.begin()
        workspace_started = True
        result = legacy.run_candidate(job_path, job, policy)
        legacy.write(artifact / "research-baseline.json", research)
        release_tx.rollback(release_had_original)
        release_started = False

        if result == 0:
            state_errors = contract.product_state_errors(job, legacy.ROOT)
            if state_errors:
                _record_candidate_failure(
                    artifact, state_errors, "canonicalProductState"
                )
                result = 2

        if result == 0:
            pose_errors = _bind_pose_contract_to_candidate(
                candidate, artifact, job, policy
            )
            if pose_errors:
                _record_candidate_failure(artifact, pose_errors, "poseContract")
                result = 2

        if result == 0:
            _bind_research_to_candidate(
                candidate,
                artifact,
                research,
                baseline,
                baseline_hash,
            )
            candidate_tx.commit(candidate_had_original)
            workspace_tx.commit(workspace_had_original)
            workspace_started = False
        else:
            candidate_tx.rollback(candidate_had_original)
            workspace_tx.rollback(workspace_had_original)
            workspace_started = False

        _augment_audit(
            artifact,
            {
                "candidateLastGoodProtected": True,
                "previousCandidateExisted": candidate_had_original,
                "previousCandidateRestored": result != 0
                and candidate_had_original,
                "canonicalWorkspaceProtected": True,
                "previousWorkspaceExisted": workspace_had_original,
                "previousWorkspaceRestored": result != 0
                and workspace_had_original,
                "customerReleaseProtected": True,
                "previousReleaseExisted": release_had_original,
                "previousReleaseRestored": release_had_original,
            },
        )
        return result
    except Exception:
        if release_started:
            release_tx.rollback(release_had_original)
        if workspace_started:
            workspace_tx.rollback(workspace_had_original)
        candidate_tx.rollback(candidate_had_original)
        raise
