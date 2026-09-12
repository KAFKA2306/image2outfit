#!/usr/bin/env python3
"""Validate once and package the unchanged reviewed candidate."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from image2outfit.quality import validate_quality_assessment

import candidate_manifest as candidate_contract
import customer_quality
import production_contract as contract
from candidate_orchestrator import _research_state
from runtime_transaction import ReceiptBoundDirectoryTransaction

QUALITY_SPEC_PATH = Path("contracts/quality/quality-spec.json")


def _quality_spec_audit(
    *,
    job: dict[str, Any],
    candidate_hash: str,
    evidence_documents: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    spec_data = candidate_contract.read(candidate_contract.ROOT / QUALITY_SPEC_PATH)
    visual_review = evidence_documents.get("visual-review", {})
    assessment = (
        visual_review.get("qualitySpec") if isinstance(visual_review, dict) else None
    )
    result, errors = validate_quality_assessment(
        spec_data=spec_data,
        assessment=assessment,
        job_id=str(job.get("id", "")),
        adapter_id=str(job.get("adapterId", "")),
        candidate_manifest_sha256=candidate_hash,
        resolve_repo_path=candidate_contract.path,
        digest=candidate_contract.digest,
    )
    result["specPath"] = QUALITY_SPEC_PATH.as_posix()
    if errors:
        result["passed"] = False
        result["releaseReady"] = False
        result["errors"] = sorted(set([*result.get("errors", []), *errors]))
    return result, [f"qualitySpec: {error}" for error in sorted(set(errors))]


def _strict_release_audit(
    job_path: Path,
    job: dict[str, Any],
    policy: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[str], str]:
    candidate = candidate_contract.path(job["candidateDir"])
    candidate_manifest_path = candidate / "candidate-manifest.json"
    candidate_manifest = candidate_contract.read(candidate_manifest_path)
    candidate_hash = (
        candidate_contract.digest(candidate_manifest_path)
        if candidate_manifest_path.is_file()
        else ""
    )
    errors = candidate_contract.verify_candidate(
        job_path, job, candidate, candidate_manifest
    )
    if job["adapterId"] in policy.get("blockedReleaseAdapterIds", []):
        errors.append(f"adapter blocked from release: {job['adapterId']}")

    research, baseline, baseline_hash = _research_state()
    if research.get("passed") is not True:
        errors.extend(
            f"researchBaseline: {value}" for value in research.get("errors", [])
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
        kind: candidate_contract.read(
            candidate_contract.path(job["humanEvidence"][kind])
        )
        for kind in policy.get("requiredHumanEvidenceKinds", [])
    }
    quality, quality_errors = customer_quality.validate(
        job=job,
        policy=policy,
        candidate_manifest=candidate_manifest,
        candidate_hash=candidate_hash,
        evidence=evidence_documents,
        resolve_repo_path=candidate_contract.path,
        digest=candidate_contract.digest,
    )
    errors.extend(quality_errors)

    quality_spec, quality_spec_errors = _quality_spec_audit(
        job=job,
        candidate_hash=candidate_hash,
        evidence_documents=evidence_documents,
    )
    quality["qualitySpec"] = quality_spec
    errors.extend(quality_spec_errors)
    return quality, research, list(dict.fromkeys(errors)), candidate_hash


def _go_receipt(
    *,
    job: dict[str, Any],
    candidate_hash: str,
    package: dict[str, Any],
    release_had_original: bool,
) -> dict[str, Any]:
    return {
        "schemaVersion": 2,
        "phase": "release",
        "jobId": job["id"],
        "adapterId": job["adapterId"],
        "checkedAt": candidate_contract.now(),
        "decision": "GO",
        "releaseEligible": True,
        "candidateManifestSha256": candidate_hash,
        **package,
        "stateProtection": {
            "customerReleaseProtected": True,
            "previousReleaseExisted": release_had_original,
            "previousReleaseRestored": False,
            "strictCustomerQualityPassed": True,
            "qualitySpecPassed": True,
            "researchBaselinePassed": True,
            "singleReleaseValidator": "tools/customer_quality.py",
            "qualitySpecValidator": "src/image2outfit/quality.py",
            "qualitySpecPath": QUALITY_SPEC_PATH.as_posix(),
            "rawEvidencePackaged": True,
            "receiptBoundToRelease": True,
        },
    }


def validate_go_release_pair(
    *,
    release: Path,
    receipt_path: Path,
    job_id: str,
    adapter_id: str,
    candidate_hash: str,
) -> list[str]:
    """Verify that a GO receipt identifies the exact release payload."""
    errors: list[str] = []
    try:
        receipt = candidate_contract.read(receipt_path)
    except Exception as exc:
        return [f"GO receipt unreadable: {exc}"]

    expected = {
        "decision": "GO",
        "releaseEligible": True,
        "jobId": job_id,
        "adapterId": adapter_id,
        "candidateManifestSha256": candidate_hash,
    }
    for field, value in expected.items():
        if receipt.get(field) != value:
            errors.append(f"GO receipt {field} mismatch")

    manifest = release / "release-manifest.json"
    archive = release / f"{job_id}.zip"
    if not manifest.is_file():
        errors.append("release manifest is missing")
    else:
        actual = candidate_contract.digest(manifest)
        if receipt.get("releaseManifestSha256") != actual:
            errors.append("GO receipt releaseManifestSha256 mismatch")
        try:
            manifest_data = candidate_contract.read(manifest)
        except Exception as exc:
            errors.append(f"release manifest unreadable: {exc}")
        else:
            for field, value in (
                ("jobId", job_id),
                ("adapterId", adapter_id),
                ("candidateManifestSha256", candidate_hash),
            ):
                if manifest_data.get(field) != value:
                    errors.append(f"release manifest {field} mismatch")

    zip_data = receipt.get("zip")
    if not isinstance(zip_data, dict):
        errors.append("GO receipt zip binding is missing")
    elif not archive.is_file():
        errors.append("release archive is missing")
    elif zip_data.get("sha256") != candidate_contract.digest(archive):
        errors.append("GO receipt archive sha256 mismatch")

    return list(dict.fromkeys(errors))


def _run_release(job_path: Path, job: dict[str, Any], policy: dict[str, Any]) -> int:
    artifact = candidate_contract.path(job["artifactDir"])
    candidate = candidate_contract.path(job["candidateDir"])
    release = candidate_contract.path(job["releaseDir"])
    artifact.mkdir(parents=True, exist_ok=True)
    quality, research, errors, candidate_hash = _strict_release_audit(
        job_path, job, policy
    )
    candidate_contract.write(artifact / "research-baseline.json", research)
    candidate_contract.write(
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
        candidate_contract.write(
            artifact / "audit.json",
            {
                "schemaVersion": 2,
                "phase": "release",
                "jobId": job["id"],
                "adapterId": job["adapterId"],
                "checkedAt": candidate_contract.now(),
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

    audit_path = artifact / "audit.json"
    release_tx = ReceiptBoundDirectoryTransaction(release, audit_path)
    release_had_original = release_tx.begin()
    try:
        candidate_manifest = candidate_contract.read(
            candidate / "candidate-manifest.json"
        )
        package = contract.package_release(
            root=candidate_contract.ROOT,
            job_path=job_path,
            job=job,
            policy=policy,
            candidate=candidate,
            release=release,
            candidate_manifest=candidate_manifest,
            candidate_hash=candidate_hash,
            human_evidence=quality,
            verify_candidate=candidate_contract.verify_candidate,
            now=candidate_contract.now,
        )
        receipt = _go_receipt(
            job=job,
            candidate_hash=candidate_hash,
            package=package,
            release_had_original=release_had_original,
        )
        candidate_contract.write(release_tx.receipt_staging, receipt)
        pair_errors = validate_go_release_pair(
            release=release,
            receipt_path=release_tx.receipt_staging,
            job_id=job["id"],
            adapter_id=job["adapterId"],
            candidate_hash=candidate_hash,
        )
        if pair_errors:
            raise ValueError("release pair validation failed: " + "; ".join(pair_errors))
        release_tx.commit(release_had_original)
        return 0
    except Exception:
        if release_tx.journal.exists():
            release_tx.rollback(release_had_original)
        raise
