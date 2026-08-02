#!/usr/bin/env python3
"""Derive Git-ignored runtime paths from a product id.

Tracked product jobs describe product inputs and canonical outputs only. Reports,
review snapshots, and release packages are local runtime state under
``.image2outfit/products/<product-id>/`` and are never configured per product.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PRODUCT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
LEGACY_RUNTIME_ROOTS = ("Artifacts", "Candidates", "Release")


@dataclass(frozen=True)
class ProductRuntimePaths:
    root: Path
    reports: Path
    candidate: Path
    release: Path


def for_product(repository_root: Path, product_id: str) -> ProductRuntimePaths:
    root = repository_root.resolve()
    if not PRODUCT_ID_PATTERN.fullmatch(product_id):
        raise ValueError(f"invalid product id for runtime path: {product_id!r}")
    runtime_root = (root / ".image2outfit" / "products" / product_id).resolve()
    if root not in runtime_root.parents:
        raise ValueError(f"runtime path escapes repository: {product_id!r}")
    return ProductRuntimePaths(
        root=runtime_root,
        reports=runtime_root / "reports",
        candidate=runtime_root / "candidate",
        release=runtime_root / "release",
    )


def for_job(repository_root: Path, job: dict[str, Any]) -> ProductRuntimePaths:
    product_id = job.get("id")
    if not isinstance(product_id, str):
        raise ValueError("job.id is required for runtime path derivation")
    return for_product(repository_root, product_id)


def relative(repository_root: Path, path: Path) -> str:
    return path.resolve().relative_to(repository_root.resolve()).as_posix()


def remove_legacy_product_outputs(repository_root: Path, product_id: str) -> list[str]:
    """Remove obsolete generated roots for one product and empty parents."""
    root = repository_root.resolve()
    removed: list[str] = []
    for directory_name in LEGACY_RUNTIME_ROOTS:
        parent = root / directory_name
        target = parent / product_id
        if target.exists():
            if not target.is_dir():
                raise RuntimeError(f"legacy runtime output is not a directory: {target}")
            shutil.rmtree(target)
            removed.append(target.relative_to(root).as_posix())
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
    return removed
