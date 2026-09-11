#!/usr/bin/env python3
"""Compute deterministic fingerprints for pipeline execution sources.

The fingerprint intentionally covers source/config inputs, not generated product
artifacts. A changed fingerprint means a cached pipeline checkpoint may no longer
represent the code that will execute now.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache"}

# Canonical machine-readable contracts that can change production execution,
# validation, completion, or release semantics. Keep this as the single owner for
# repository-wide checkpoint source dependencies.
PRODUCTION_RUNTIME_DEPENDENCIES = (
    "config/release-policy.json",
    "config/genworks-handoff-policy.json",
    "contracts/quality/quality-spec.json",
    "config/job.schema.v2.json",
    "config/products/construction.schema.v1.json",
    "config/pipeline/visual-quality-defaults.v1.json",
    "config/toolchain-lock.json",
    "pyproject.toml",
    "uv.lock",
)

# These profile fields point at validation contracts read by the canonical audit
# path. Generated storageRoot values are deliberately not source dependencies.
PROFILE_AUDIT_DEPENDENCY_FIELDS = ("recordSchema", "manifestSchema")


def _iter_files(path: Path) -> Iterable[Path]:
    if path.is_file():
        yield path
        return
    if not path.is_dir():
        raise FileNotFoundError(path)
    for candidate in sorted(path.rglob("*")):
        if not candidate.is_file():
            continue
        if any(part in IGNORED_PARTS for part in candidate.parts):
            continue
        if candidate.suffix in {".pyc", ".pyo"}:
            continue
        yield candidate


def fingerprint_paths(root: Path, paths: Iterable[Path]) -> str:
    """Hash repository-relative path names and bytes in stable order."""
    root = root.resolve()
    files: dict[str, Path] = {}
    for path in paths:
        resolved = path.resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError(f"fingerprint input escapes repository: {path}")
        for candidate in _iter_files(resolved):
            relative = candidate.relative_to(root).as_posix()
            files[relative] = candidate

    digest = hashlib.sha256()
    for relative in sorted(files):
        payload = files[relative].read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(payload).digest())
        digest.update(b"\n")
    return digest.hexdigest()


def _profile_dependency_paths(root: Path, profile_path: Path) -> list[Path]:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    audit_contract = profile.get("auditContract")
    if not isinstance(audit_contract, dict):
        raise ValueError("pipeline profile auditContract must be an object")

    dependencies: list[Path] = []
    for field in PROFILE_AUDIT_DEPENDENCY_FIELDS:
        value = audit_contract.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"pipeline profile auditContract.{field} must be a repository path")
        dependencies.append(root / value)
    return dependencies


def pipeline_source_dependencies(
    root: Path,
    *,
    product_id: str,
    request_path: Path,
    profile_path: Path,
) -> tuple[Path, ...]:
    """Return the fail-closed source dependency closure for checkpoint reuse."""
    inputs = [
        root / "src" / "image2outfit",
        root / "tools",
        root / "config" / "products" / product_id,
        request_path,
        profile_path,
        *(root / relative for relative in PRODUCTION_RUNTIME_DEPENDENCIES),
        *_profile_dependency_paths(root, profile_path),
    ]
    return tuple(inputs)


def pipeline_source_fingerprint(
    root: Path,
    *,
    product_id: str,
    request_path: Path,
    profile_path: Path,
) -> str:
    """Fingerprint all runtime sources that can affect a canonical product run."""
    return fingerprint_paths(
        root,
        pipeline_source_dependencies(
            root,
            product_id=product_id,
            request_path=request_path,
            profile_path=profile_path,
        ),
    )
