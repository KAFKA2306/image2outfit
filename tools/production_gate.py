#!/usr/bin/env python3
"""Mandatory construction-method and customer-quality production gate.

Tracked product jobs contain only canonical product inputs and outputs. Local
reports, review snapshots, and release packages are derived from ``job.id`` and
stored under ``.image2outfit/products/<product-id>/``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import candidate_manifest as candidate_contract
import method_selection
import runtime_paths
from candidate_orchestrator import _augment_audit, _run_candidate as run_candidate
from release_orchestrator import _run_release as run_release

ROOT = Path(__file__).resolve().parents[1]


def _repo_path(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"path escapes repository: {value}")
    return path


def _runtime_job(job: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    paths = runtime_paths.for_job(root, job)
    enriched = dict(job)
    enriched.update(
        artifactDir=runtime_paths.relative(root, paths.reports),
        candidateDir=runtime_paths.relative(root, paths.candidate),
        releaseDir=runtime_paths.relative(root, paths.release),
    )
    return enriched


def _materialize_runtime_job(job: dict[str, Any], root: Path = ROOT) -> Path:
    paths = runtime_paths.for_job(root, job)
    runtime_job_path = paths.root / "job.json"
    candidate_contract.write(runtime_job_path, job)
    return runtime_job_path


def _load(job_path: Path, root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any]]:
    policy_path = root / "config" / "release-policy.json"
    policy = candidate_contract.read(policy_path)
    job = candidate_contract.read(job_path)
    if policy.get("schemaVersion") != 1:
        raise ValueError("release-policy.json must use schemaVersion 1")
    if job.get("schemaVersion") != 2:
        raise ValueError("legacy jobs are disabled; schemaVersion must be 2")
    required = candidate_contract.required_job_fields()
    missing = [key for key in required if key not in job or job[key] in (None, "")]
    if missing:
        raise ValueError(f"job v2 missing: {', '.join(missing)}")
    runtime_paths.for_job(root, job)
    return _runtime_job(job, root), policy


def _candidate_manifest_path(job: dict[str, Any], root: Path = ROOT) -> Path:
    return runtime_paths.for_job(root, job).candidate / "candidate-manifest.json"


def _artifact_path(job: dict[str, Any], root: Path = ROOT) -> Path:
    return runtime_paths.for_job(root, job).reports


def _binding_snapshot(
    job: dict[str, Any], selection: dict[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    construction_path = _repo_path(root, str(selection["constructionPath"]))
    policy_path = root / "config" / "release-policy.json"
    if not construction_path.is_file():
        raise FileNotFoundError(f"construction config missing: {construction_path}")
    if not policy_path.is_file():
        raise FileNotFoundError(f"release policy missing: {policy_path}")
    return {
        "schemaVersion": 1,
        "commercialProfile": selection.get("commercialProfile"),
        "constructionProfile": selection.get("constructionProfile"),
        "constructionPath": selection.get("constructionPath"),
        "constructionSha256": method_selection.digest(construction_path),
        "releasePolicySha256": method_selection.digest(policy_path),
        "requiredCapabilities": list(selection.get("requiredCapabilities", [])),
        "requiredCommercialEvidence": list(
            selection.get("requiredCommercialEvidence", [])
        ),
        "buildScript": job.get("buildScript"),
    }


def _write_selection(
    job: dict[str, Any], selection: dict[str, Any], root: Path = ROOT
) -> None:
    artifact = _artifact_path(job, root)
    candidate_contract.write(artifact / "method-selection.json", selection)


def _write_no_go(
    job: dict[str, Any],
    phase: str,
    errors: list[str],
    root: Path = ROOT,
    **details: Any,
) -> None:
    paths = runtime_paths.for_job(root, job)
    value: dict[str, Any] = {
        "schemaVersion": 2,
        "phase": phase,
        "jobId": job.get("id"),
        "adapterId": job.get("adapterId"),
        "checkedAt": candidate_contract.now(),
        "decision": "NO-GO",
        "releaseEligible": False,
        "errors": errors,
        "stateProtection": {
            "customerReleaseProtected": True,
            "previousReleasePreserved": paths.release.exists(),
        },
    }
    value.update(details)
    candidate_contract.write(paths.reports / "audit.json", value)


def _bind_method_to_candidate(
    job: dict[str, Any], selection: dict[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    manifest_path = _candidate_manifest_path(job, root)
    manifest = candidate_contract.read(manifest_path)
    if not manifest_path.is_file() or not manifest:
        raise RuntimeError("candidate manifest is missing after candidate generation")
    binding = _binding_snapshot(job, selection, root)
    manifest["constructionMethod"] = binding
    candidate_contract.write(manifest_path, manifest)

    artifact = _artifact_path(job, root)
    audit_path = artifact / "audit.json"
    audit = candidate_contract.read(audit_path)
    stages = audit.setdefault("stages", {})
    stages["constructionMethod"] = {
        "passed": True,
        **binding,
    }
    audit["candidateManifestSha256"] = method_selection.digest(manifest_path)
    candidate_contract.write(audit_path, audit)
    _write_selection(job, selection, root)
    return binding


def _bound_method_errors(
    job: dict[str, Any],
    selection: dict[str, Any],
    candidate_manifest: dict[str, Any],
    root: Path = ROOT,
) -> list[str]:
    try:
        expected = _binding_snapshot(job, selection, root)
    except (OSError, ValueError, KeyError) as exc:
        return [f"candidate construction method binding cannot be resolved: {exc}"]
    actual = candidate_manifest.get("constructionMethod")
    if not isinstance(actual, dict):
        return ["candidate construction method binding is missing"]
    return [
        f"candidate construction method changed: {field}"
        for field, value in expected.items()
        if actual.get(field) != value
    ]


def _evaluate_release(
    job: dict[str, Any], root: Path = ROOT
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    selection = method_selection.select(job, root)
    manifest_path = _candidate_manifest_path(job, root)
    manifest = candidate_contract.read(manifest_path)
    binding_errors = _bound_method_errors(job, selection, manifest, root)
    commercial = method_selection.validate_commercial_evidence(job, manifest_path, root)
    errors = list(selection.get("errors", []))
    errors.extend(binding_errors)
    errors.extend(commercial.get("errors", []))
    errors = list(dict.fromkeys(errors))
    commercial["bindingErrors"] = binding_errors
    commercial["passed"] = not errors
    commercial["errors"] = errors
    return selection, commercial, errors


def _run_candidate(
    job_path: Path,
    job: dict[str, Any],
    policy: dict[str, Any],
    root: Path = ROOT,
) -> int:
    selection = method_selection.select(job, root)
    if selection.get("passed") is not True:
        _write_selection(job, selection, root)
        errors = list(selection.get("errors", []))
        _write_no_go(job, "candidate", errors, root, methodSelection=selection)
        return 2

    result = run_candidate(job_path, job, policy)
    if result != 0:
        _write_selection(job, selection, root)
        return result
    try:
        _bind_method_to_candidate(job, selection, root)
    except Exception as exc:
        error = f"candidate construction method binding failed: {exc}"
        _write_no_go(job, "candidate", [error], root, methodSelection=selection)
        print(f"image2outfit production gate: {error}", file=sys.stderr)
        return 1
    return 0


def _run_release(
    job_path: Path,
    job: dict[str, Any],
    policy: dict[str, Any],
    root: Path = ROOT,
) -> int:
    selection, commercial, errors = _evaluate_release(job, root)
    artifact = _artifact_path(job, root)
    _write_selection(job, selection, root)
    candidate_contract.write(artifact / "commercial-method-quality.json", commercial)
    if errors:
        _write_no_go(
            job,
            "release",
            errors,
            root,
            methodSelection=selection,
            commercialMethodQuality=commercial,
            candidateManifestSha256=commercial.get("candidateManifestSha256"),
        )
        return 2

    result = run_release(job_path, job, policy)
    if result == 0:
        _augment_audit(
            artifact,
            {
                "commercialMethodPassed": True,
                "commercialProfile": selection.get("commercialProfile"),
                "constructionProfile": selection.get("constructionProfile"),
            },
        )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Transactional, research-bound commercial and customer-quality gate"
    )
    parser.add_argument("--mode", choices=("candidate", "release"), required=True)
    parser.add_argument("--job", required=True)
    return parser


def main() -> int:
    options = build_parser().parse_args()
    try:
        source_job_path = Path(options.job).resolve()
        job, policy = _load(source_job_path)
        runtime_paths.remove_legacy_product_outputs(ROOT, str(job["id"]))
        runtime_job_path = _materialize_runtime_job(job)
        if options.mode == "release":
            return _run_release(runtime_job_path, job, policy)
        return _run_candidate(runtime_job_path, job, policy)
    except Exception as exc:
        print(f"image2outfit production gate: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
