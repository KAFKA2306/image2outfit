#!/usr/bin/env python3
"""Single fail-close mutation owner for ProductManifest.json."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Callable

from contract_io import digest, read_json, relative, repo_path, write_json
import production_contract

ROOT = Path(__file__).resolve().parents[1]
UNITY_GATE_NAMES = (
    "unityImport",
    "prefabSerialized",
    "prefabReload",
    "modularAvatar",
    "ndmf",
)


def _manifest_errors(manifest: dict[str, Any], job: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("schemaVersion") != 1:
        errors.append("ProductManifest schemaVersion must be 1")
    if manifest.get("productId") != job.get("id"):
        errors.append("ProductManifest productId must match job.id")
    if manifest.get("productRoot") != job.get("productRoot"):
        errors.append("ProductManifest productRoot must match job.productRoot")
    if not isinstance(manifest.get("technicalGates"), dict):
        errors.append("ProductManifest technicalGates must be an object")
    release_readiness = manifest.get("releaseReadiness")
    if release_readiness is not None and not isinstance(release_readiness, dict):
        errors.append("ProductManifest releaseReadiness must be an object")
    return errors


def _validate_with_completion_policy(
    manifest: dict[str, Any], job: dict[str, Any], root: Path, *, suffix: str
) -> list[str]:
    errors = _manifest_errors(manifest, job)
    manifest_path = repo_path(root, str(job["productManifestPath"]))
    staged = manifest_path.with_name(f".{manifest_path.name}.{suffix}.tmp")
    staged.parent.mkdir(parents=True, exist_ok=True)
    try:
        write_json(staged, manifest)
        staged_job = dict(job)
        staged_job["productManifestPath"] = relative(root, staged)
        errors.extend(production_contract.product_state_errors(staged_job, root))
    finally:
        staged.unlink(missing_ok=True)
    return list(dict.fromkeys(errors))


def _validate_unity_ready_payload(payload: Any, root: Path) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("unity-ready payload must be an object")
    forbidden = {"state", "status", "completionGates", "completionBlocker"} & set(payload)
    if forbidden:
        raise ValueError(
            "policy-derived completion fields cannot be supplied by callers: "
            + ", ".join(sorted(forbidden))
        )
    required = {
        "status",
        "multiMaterialSetup",
        "modularAvatarSetup",
        "ndmfBake",
        "reimport",
        "targetAvatarAssetPath",
        "materialRoles",
        "evidencePath",
        "evidenceSha256",
    }
    if set(payload) != required:
        missing = sorted(required - set(payload))
        extra = sorted(set(payload) - required)
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if extra:
            details.append("extra=" + ",".join(extra))
        raise ValueError("invalid unity-ready payload: " + " ".join(details))
    for field in ("status", "multiMaterialSetup", "modularAvatarSetup", "ndmfBake", "reimport"):
        if payload.get(field) != "VERIFIED":
            raise ValueError(f"unity-ready {field} must be VERIFIED")
    evidence_path = repo_path(root, str(payload["evidencePath"]))
    if not evidence_path.is_file():
        raise ValueError("unity-ready evidence does not exist")
    if digest(evidence_path) != payload.get("evidenceSha256"):
        raise ValueError("unity-ready evidence SHA-256 mismatch")
    if not isinstance(payload.get("materialRoles"), dict):
        raise ValueError("unity-ready materialRoles must be an object")
    return copy.deepcopy(payload)


def apply_update(
    *,
    manifest_path: Path,
    job: dict[str, Any],
    intent: dict[str, Any],
    root: Path = ROOT,
    before_replace: Callable[[Path, Path], None] | None = None,
) -> dict[str, Any]:
    """Apply one typed ProductManifest transition and atomically replace the file."""
    if intent.get("kind") != "unity-ready":
        raise ValueError(f"unknown ProductManifest update kind: {intent.get('kind')!r}")
    if intent.get("productId") != job.get("id"):
        raise ValueError("ProductManifest update product identity mismatch")
    if intent.get("buildRevision") != job.get("buildRevision"):
        raise ValueError("ProductManifest update revision mismatch")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"ProductManifest missing: {manifest_path}")
    expected_hash = intent.get("expectedManifestSha256")
    if not isinstance(expected_hash, str) or digest(manifest_path) != expected_hash:
        raise ValueError("ProductManifest update is stale: manifest SHA-256 mismatch")

    current = read_json(manifest_path)
    pre_errors = _validate_with_completion_policy(current, job, root, suffix="precheck")
    if pre_errors:
        raise ValueError("ProductManifest precondition failed: " + "; ".join(pre_errors))

    updated = copy.deepcopy(current)
    technical = updated.setdefault("technicalGates", {})
    if not isinstance(technical, dict):
        raise ValueError("ProductManifest technicalGates must be an object")
    for name in UNITY_GATE_NAMES:
        technical[name] = "PASS"
    readiness = updated.setdefault("releaseReadiness", {})
    if not isinstance(readiness, dict):
        raise ValueError("ProductManifest releaseReadiness must be an object")
    readiness["unityReady"] = _validate_unity_ready_payload(intent.get("payload"), root)

    post_errors = _validate_with_completion_policy(updated, job, root, suffix="postcheck")
    if post_errors:
        raise ValueError("ProductManifest transition invalid: " + "; ".join(post_errors))

    staged = manifest_path.with_name(f".{manifest_path.name}.replace.tmp")
    try:
        write_json(staged, updated)
        staged_job = dict(job)
        staged_job["productManifestPath"] = relative(root, staged)
        final_errors = production_contract.product_state_errors(staged_job, root)
        if final_errors:
            raise ValueError("staged ProductManifest invalid: " + "; ".join(final_errors))
        if before_replace is not None:
            before_replace(staged, manifest_path)
        os.replace(staged, manifest_path)
    finally:
        staged.unlink(missing_ok=True)

    stored = read_json(manifest_path)
    stored_errors = _manifest_errors(stored, job)
    if stored_errors:
        raise RuntimeError("stored ProductManifest failed post-write validation: " + "; ".join(stored_errors))
    return stored


def replace_legacy_snapshot(
    manifest_path: Path,
    proposed: dict[str, Any],
    *,
    root: Path = ROOT,
    before_replace: Callable[[Path, Path], None] | None = None,
) -> dict[str, Any]:
    """Convert the existing Unity-ready caller snapshot into the typed transition."""
    if not manifest_path.is_file():
        raise FileNotFoundError(f"ProductManifest missing: {manifest_path}")
    current = read_json(manifest_path)
    job_path_value = current.get("sourceJobPath")
    if not isinstance(job_path_value, str) or not job_path_value:
        raise ValueError("ProductManifest sourceJobPath is required for mutation")
    job = read_json(repo_path(root, job_path_value))
    if not isinstance(job, dict) or not job:
        raise ValueError("ProductManifest source job is unreadable")

    allowed_top_level = {"technicalGates", "releaseReadiness"}
    for key in set(current) | set(proposed):
        if key not in allowed_top_level and current.get(key) != proposed.get(key):
            raise ValueError(f"direct ProductManifest field mutation is forbidden: {key}")

    current_technical = current.get("technicalGates")
    proposed_technical = proposed.get("technicalGates")
    if not isinstance(current_technical, dict) or not isinstance(proposed_technical, dict):
        raise ValueError("ProductManifest technicalGates must be objects")
    for key in set(current_technical) | set(proposed_technical):
        if key in UNITY_GATE_NAMES:
            if proposed_technical.get(key) != "PASS":
                raise ValueError(f"Unity-ready transition requires {key}=PASS")
        elif current_technical.get(key) != proposed_technical.get(key):
            raise ValueError(f"direct technical gate mutation is forbidden: {key}")

    current_readiness = current.get("releaseReadiness", {})
    proposed_readiness = proposed.get("releaseReadiness", {})
    if not isinstance(current_readiness, dict) or not isinstance(proposed_readiness, dict):
        raise ValueError("ProductManifest releaseReadiness must be objects")
    for key in set(current_readiness) | set(proposed_readiness):
        if key != "unityReady" and current_readiness.get(key) != proposed_readiness.get(key):
            raise ValueError(f"direct release readiness mutation is forbidden: {key}")
    payload = proposed_readiness.get("unityReady")

    return apply_update(
        manifest_path=manifest_path,
        job=job,
        intent={
            "kind": "unity-ready",
            "productId": job.get("id"),
            "buildRevision": job.get("buildRevision"),
            "expectedManifestSha256": digest(manifest_path),
            "payload": payload,
        },
        root=root,
        before_replace=before_replace,
    )
