#!/usr/bin/env python3
"""Validate once and package the unchanged reviewed candidate."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import customer_quality
import production_contract as contract
import release_gate as legacy
from candidate_orchestrator import _research_state
from runtime_transaction import DirectoryTransaction


def _strict_release_audit(
    job_path: Path,
    job: dict[str, Any],
    policy: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[str], str]:
    candidate = legacy.path(job["candidateDir"])
    candidate_manifest_path = candidate / "candidate-manifest.json"
    candidate_manifest = legacy.read(candidate_manifest_path)
    candidate_hash = (
        legacy.digest(candidate_manifest_path)
        if candidate_manifest_path.is_file()
        else ""
    )
    errors = legacy.verify_candidate(job_path, job, candidate, candidate_manifest)
    if job["adapterId"] in policy.get("blockedReleaseAdapterIds", []):
        errors.append(f"adapter blocked from release: {job['adapterId']}")

    research, baseline, baseline_hash = _research_state()
    if research.get("passed") is not True:
        errors.extend(
            f"researchBaseline: {value}"
            for value in research.get("errors", [])
        )
    bound = candidate_manifest.get("researchBaseline")
    if not isinstance(bound, dict):
        errors.append("candidate research baseline is missing")
    else:
        expected = {
            "path": research.get("path"),
            "baselineId": baseline.get("baselineId"),
            "surveyYear": baseline.get("surveyYear"),
            "reviewedAt": baseline.get("reviewedAt"),
            "sha256": baseline_hash,
            "requiredCapabilities": baseline.get("requiredCapabilities"),
        }
        for field, value in expected.items():
            if bound.get(field) != value:
                errors.append(f"candidate research baseline changed: {field}")

    pose_contract = candidate_manifest.get("poseContract")
    if not isinstance(pose_contract, dict):
        errors.append("candidate pose contract is missing")
    elif pose_contract.get("requiredPoses") != policy.get("requiredPoses"):
        errors.append("candidate pose contract changed")

    evidence_documents = {
        kind: legacy.read(legacy.path(job["humanEvidence"][kind]))
        for kind in policy.get("requiredHumanEvidenceKinds", [])
    }
    quality, quality_errors = customer_quality.validate(
        job=job,
        policy=policy,
        candidate_manifest=candidate_manifest,
        candidate_hash=candidate_hash,
        evidence=evidence_documents,
        resolve_repo_path=legacy.path,
        digest=legacy.digest,
    )
    errors.extend(quality_errors)
    return quality, research, list(dict.fromkeys(errors)), candidate_hash


def _run_release(job_path: Path, job: dict[str, Any], policy: dict[str, Any]) -> int:
    artifact = legacy.path(job["artifactDir"])
    candidate = legacy.path(job["candidateDir"])
    release = legacy.path(job["releaseDir"])
    artifact.mkdir(parents=True, exist_ok=True)
    quality, research, errors, candidate_hash = _strict_release_audit(
        job_path, job, policy
    )
    legacy.write(artifact / "research-baseline.json", research)
    legacy.write(
        artifact / "customer-quality.json",
        {
            "schemaVersion": 2,
            "phase": "customer-quality",
            "jobId": job["id"],
            "adapterId": job["adapterId"],
            "candidateManifestSha256": candidate_hash or None,
            "passed": not errors,
            "errors": errors,
            "evidence": quality,
            "researchBaseline": {
                "passed": research.get("passed") is True,
                "baselineId": research.get("baselineId"),
                "reviewedAt": research.get("reviewedAt"),
            },
        },
    )
    if errors:
        legacy.write(
            artifact / "audit.json",
            {
                "schemaVersion": 2,
                "phase": "release",
                "jobId": job["id"],
                "adapterId": job["adapterId"],
                "checkedAt": legacy.now(),
                "decision": "NO-GO",
                "releaseEligible": False,
                "errors": errors,
                "evidence": quality,
                "researchBaseline": research,
                "candidateManifestSha256": candidate_hash or None,
                "stateProtection": {
                    "customerReleaseProtected": True,
                    "previousReleasePreserved": release.exists(),
                },
            },
        )
        return 2

    release_tx = DirectoryTransaction(release)
    release_had_original = release_tx.begin()
    try:
        candidate_manifest = legacy.read(candidate / "candidate-manifest.json")
        package = contract.package_release(
            root=legacy.ROOT,
            job_path=job_path,
            job=job,
            policy=policy,
            candidate=candidate,
            release=release,
            candidate_manifest=candidate_manifest,
            candidate_hash=candidate_hash,
            human_evidence=quality,
            verify_candidate=legacy.verify_candidate,
            now=legacy.now,
        )
        release_tx.commit(release_had_original)
        legacy.write(
            artifact / "audit.json",
            {
                "schemaVersion": 2,
                "phase": "release",
                "jobId": job["id"],
                "adapterId": job["adapterId"],
                "checkedAt": legacy.now(),
                "decision": "GO",
                "releaseEligible": True,
                "candidateManifestSha256": candidate_hash,
                **package,
                "stateProtection": {
                    "customerReleaseProtected": True,
                    "previousReleaseExisted": release_had_original,
                    "previousReleaseRestored": False,
                    "strictCustomerQualityPassed": True,
                    "researchBaselinePassed": True,
                    "singleReleaseValidator": "tools/customer_quality.py",
                    "rawEvidencePackaged": True,
                },
            },
        )
        return 0
    except Exception:
        release_tx.rollback(release_had_original)
        raise
