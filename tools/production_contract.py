#!/usr/bin/env python3
"""Canonical image2outfit validation and release-packaging contract."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any, Callable

from contract_io import (
    PRODUCT_ID,
    SHA256,
    STABLE_SCRIPT,
    canonical_manifest_path,
    canonical_product_root,
    digest,
    read_json,
    relative,
    repo_path,
    required_pose_paths,
    valid_review_reference,
    validate_schema_file,
    write_json,
)


def validate_job(job: dict[str, Any], policy: dict[str, Any], root: Path) -> list[str]:
    errors = validate_schema_file(job, root / "config" / "job.schema.v2.json", "job")
    product_id = job.get("id")
    if not isinstance(product_id, str) or not PRODUCT_ID.fullmatch(product_id):
        errors.append("job.id must be a canonical product slug")
        product_id = ""
    if product_id:
        expected_root = canonical_product_root(product_id)
        if job.get("productRoot") != expected_root:
            errors.append(f"job.productRoot must be {expected_root}")
        expected_manifest = canonical_manifest_path(product_id)
        if job.get("productManifestPath") != expected_manifest:
            errors.append(f"job.productManifestPath must be {expected_manifest}")

    build_script = job.get("buildScript")
    if isinstance(build_script, str):
        if STABLE_SCRIPT.search(Path(build_script).stem):
            errors.append(
                "job.buildScript must use a stable product entrypoint without "
                "version, entry, refit, or legacy naming"
            )
        else:
            try:
                if not repo_path(root, build_script).is_file():
                    errors.append(f"job.buildScript does not exist: {build_script}")
            except ValueError as exc:
                errors.append(str(exc))

    hosted_pose = job.get("hostedPoseScript")
    if isinstance(hosted_pose, str):
        try:
            if not repo_path(root, hosted_pose).is_file():
                errors.append(f"job.hostedPoseScript does not exist: {hosted_pose}")
        except ValueError as exc:
            errors.append(str(exc))

    previews = job.get("previewPaths")
    for view in policy.get("minimumPreview", {}).get("requiredViews", []):
        expected = f"{job.get('productRoot')}/Previews/{view}.png"
        if not isinstance(previews, dict) or previews.get(view) != expected:
            errors.append(f"job.previewPaths.{view} must be {expected}")

    human = job.get("humanEvidence")
    for kind in policy.get("requiredHumanEvidenceKinds", []):
        if not isinstance(human, dict) or not human.get(kind):
            errors.append(f"job.humanEvidence.{kind} is required")

    declared_pose_paths = job.get("posePaths")
    canonical_poses = required_pose_paths(job, policy)
    if declared_pose_paths is not None and declared_pose_paths != canonical_poses:
        errors.append(
            "job.posePaths must exactly match the canonical release-policy pose paths"
        )

    for field in (
        "blendPath",
        "fbxAssetPath",
        "prefabAssetPath",
        "integratedPrefabAssetPath",
    ):
        value = job.get(field)
        if isinstance(value, str) and product_id:
            prefix = canonical_product_root(product_id) + "/"
            if not value.startswith(prefix):
                errors.append(f"job.{field} must stay inside {prefix[:-1]}")
    return list(dict.fromkeys(errors))


def construction_path(root: Path, product_id: str) -> Path:
    return root / "config" / "products" / product_id / "construction.json"


def validate_construction(
    job: dict[str, Any], policy: dict[str, Any], root: Path
) -> tuple[dict[str, Any], list[str], list[str]]:
    product_id = str(job.get("id", ""))
    path = construction_path(root, product_id)
    warnings: list[str] = []
    try:
        value = read_json(path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {}, [f"construction contract unreadable: {exc}"], warnings
    errors = validate_schema_file(
        value,
        root / "config" / "products" / "construction.schema.v1.json",
        "construction",
    )
    if value.get("productId") != product_id:
        errors.append("construction.productId must match job.id")
    profile = value.get("profile")
    profiles = policy.get("commercialMethodPolicy", {}).get("profiles", {})
    if not isinstance(profile, str) or profile not in profiles:
        errors.append(f"unknown construction.profile: {profile!r}")
    if "requiredPoses" in value:
        if value.get("requiredPoses") != policy.get("requiredPoses"):
            errors.append(
                "construction.requiredPoses conflicts with release-policy.requiredPoses"
            )
        else:
            warnings.append(
                "construction.requiredPoses is deprecated; "
                "release-policy.requiredPoses is authoritative"
            )
    return value, list(dict.fromkeys(errors)), warnings


def _normalize_gate_name(value: Any) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


def _handoff_policy(root: Path) -> dict[str, Any]:
    try:
        value = read_json(root / "config" / "genworks-handoff-policy.json")
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def product_state_errors(job: dict[str, Any], root: Path) -> list[str]:
    manifest_value = job.get("productManifestPath")
    if not isinstance(manifest_value, str):
        return ["job.productManifestPath is required"]
    try:
        manifest = read_json(repo_path(root, manifest_value))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [f"product manifest unreadable: {exc}"]

    handoff = _handoff_policy(root)
    rules = handoff.get("rules", {})
    if not isinstance(rules, dict):
        rules = {}
    out_of_scope = {
        _normalize_gate_name(name) for name in handoff.get("outOfScopeGates", [])
    }

    errors: list[str] = []
    if manifest.get("schemaVersion") != 1:
        errors.append("product manifest schemaVersion must be 1")
    if manifest.get("productId") != job.get("id"):
        errors.append("product manifest productId must match job.id")
    if manifest.get("productRoot") != job.get("productRoot"):
        errors.append("product manifest productRoot must match job.productRoot")

    technical_gates = manifest.get("technicalGates")
    if isinstance(technical_gates, dict):
        failed = sorted(
            name
            for name, value in technical_gates.items()
            if value == "FAIL"
            and _normalize_gate_name(name) not in out_of_scope
            and not name.lower().startswith("human")
        )
        errors.extend(f"product technical gate failed: {name}" for name in failed)

    fit = manifest.get("fitAuditSummary")
    if (
        isinstance(fit, dict)
        and fit.get("pass") is False
        and rules.get("fitAuditFailureBlocksCompletion", True)
    ):
        errors.append("product fit audit is explicitly failing")

    state = str(manifest.get("state", manifest.get("status", "WORKING"))).upper()
    completion_status = str(handoff.get("completionStatus", "COMPLETE")).upper()
    if state == completion_status:
        completion_gates = manifest.get("completionGates")
        if not isinstance(completion_gates, dict):
            errors.append("complete product requires completionGates")
        else:
            for name in handoff.get("requiredCompletionGates", []):
                if completion_gates.get(name) != "PASS":
                    errors.append(f"complete product gate is not PASS: {name}")

    return list(dict.fromkeys(errors))


def validate_hashed_artifacts(
    values: Any, *, root: Path
) -> tuple[list[dict[str, Any]], list[str]]:
    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    if not isinstance(values, list) or not values:
        return normalized, ["sourceArtifacts must be a non-empty list"]
    seen: set[str] = set()
    for index, item in enumerate(values):
        prefix = f"sourceArtifacts[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object with path and sha256")
            continue
        path_value = item.get("path")
        expected_hash = item.get("sha256")
        if not isinstance(path_value, str) or not path_value:
            errors.append(f"{prefix}.path is required")
            continue
        if path_value in seen:
            errors.append(f"{prefix}.path is duplicated")
            continue
        seen.add(path_value)
        if not isinstance(expected_hash, str) or not SHA256.fullmatch(expected_hash):
            errors.append(f"{prefix}.sha256 must be a lowercase SHA-256")
            continue
        try:
            source = repo_path(root, path_value)
        except ValueError as exc:
            errors.append(f"{prefix}: {exc}")
            continue
        if not source.is_file():
            errors.append(f"{prefix}.path is missing: {path_value}")
        elif digest(source) != expected_hash:
            errors.append(f"{prefix}.sha256 mismatch: {path_value}")
        else:
            normalized.append({"path": path_value, "sha256": expected_hash})
    return normalized, errors


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
        runtime_destination = destination.parent / "runtime" / screenshot_path.name
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
    verify_candidate: Callable[[Path, dict[str, Any], Path, dict[str, Any]], list[str]],
    now: Callable[[], str],
) -> dict[str, Any]:
    """Package one already validated candidate with its raw evidence."""
    errors = verify_candidate(job_path, job, candidate, candidate_manifest)
    if job.get("adapterId") in policy.get("blockedReleaseAdapterIds", []):
        errors.append(f"adapter blocked from release: {job.get('adapterId')}")
    if errors:
        raise ValueError("release packaging refused: " + "; ".join(errors))

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

    commercial_source = repo_path(root, f"{job['productRoot']}/Evidence/Commercial")
    if commercial_source.is_dir():
        commercial_destination = package / "Evidence" / "Commercial"
        shutil.copytree(commercial_source, commercial_destination)
        copied.extend(
            path for path in commercial_destination.rglob("*") if path.is_file()
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


__all__ = [
    "construction_path",
    "digest",
    "package_release",
    "product_state_errors",
    "read_json",
    "repo_path",
    "required_pose_paths",
    "valid_review_reference",
    "validate_construction",
    "validate_hashed_artifacts",
    "validate_job",
    "validate_schema_file",
]
