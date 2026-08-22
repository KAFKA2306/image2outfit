#!/usr/bin/env python3
"""Audit the single internal runtime layout and reject obsolete output contracts."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_JOB_FIELDS = ("artifactDir", "candidateDir", "releaseDir")
FORBIDDEN_ROOTS = ("Artifacts", "Candidates", "Release")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def audit(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    errors: list[str] = []

    schema_path = root / "config" / "job.schema.v2.json"
    try:
        schema = _read_json(schema_path)
    except (OSError, json.JSONDecodeError) as exc:
        schema = {}
        errors.append(f"invalid job schema: {exc}")
    required = set(schema.get("required", []))
    properties = set(schema.get("properties", {}))
    for field in FORBIDDEN_JOB_FIELDS:
        if field in required or field in properties:
            errors.append(f"job schema still owns runtime field: {field}")

    products_root = root / "config" / "products"
    if products_root.is_dir():
        for job_path in sorted(products_root.glob("*/job.json")):
            try:
                job = _read_json(job_path)
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"invalid product job {job_path.relative_to(root)}: {exc}")
                continue
            for field in FORBIDDEN_JOB_FIELDS:
                if field in job:
                    errors.append(
                        f"{job_path.relative_to(root).as_posix()} configures runtime field {field}"
                    )

    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    for directory in FORBIDDEN_ROOTS:
        prefix = f"{directory}/"
        residue = sorted(
            path for path in tracked if path == directory or path.startswith(prefix)
        )
        if residue:
            errors.append(f"tracked obsolete runtime root {directory}: {residue}")

    gitignore = (root / ".gitignore").read_text(encoding="utf-8")
    for directory in FORBIDDEN_ROOTS:
        if f"/{directory}/" in gitignore:
            errors.append(f".gitignore hides obsolete runtime root: {directory}")
    if "/.image2outfit/" not in gitignore:
        errors.append(".image2outfit runtime root is not ignored")

    result = {
        "schemaVersion": 1,
        "runtimePattern": ".image2outfit/products/<product-id>/{reports,candidate,release}",
        "forbiddenJobFields": list(FORBIDDEN_JOB_FIELDS),
        "forbiddenRoots": list(FORBIDDEN_ROOTS),
        "errors": errors,
        "passed": not errors,
    }
    return result


def main() -> int:
    result = audit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
