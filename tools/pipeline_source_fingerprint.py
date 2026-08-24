#!/usr/bin/env python3
"""Compute deterministic fingerprints for pipeline execution sources.

The fingerprint intentionally covers source/config inputs, not generated product
artifacts. A changed fingerprint means a cached pipeline checkpoint may no longer
represent the code that will execute now.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path

IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache"}


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


def pipeline_source_fingerprint(
    root: Path,
    *,
    product_id: str,
    request_path: Path,
    profile_path: Path,
) -> str:
    """Fingerprint all runtime sources that can affect a canonical product run."""
    inputs = [
        root / "src" / "image2outfit",
        root / "tools",
        root / "config" / "products" / product_id,
        request_path,
        profile_path,
        root / "config" / "visual-quality-defaults.v1.json",
        root / "config" / "toolchain-lock.json",
        root / "pyproject.toml",
        root / "uv.lock",
    ]
    return fingerprint_paths(root, inputs)
