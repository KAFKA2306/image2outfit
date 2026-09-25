"""Derive dbt input rows from canonical image2outfit product evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PRODUCT_STATES = {"WORKING", "COMPLETE", "REJECTED"}
GATE_STATES = {
    "PASS",
    "FAIL",
    "PENDING",
    "UNVERIFIED",
    "OUT_OF_SCOPE",
    "VERIFIED",
    "REJECTED",
    "SKIPPED",
    "NOT_APPLICABLE",
}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _load_optional(path: Path) -> dict[str, Any] | None:
    return _read_json(path) if path.is_file() else None


def _state(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip().upper() or None


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    )
    path.write_text(payload, encoding="utf-8")


def extract(root: Path, output_dir: Path) -> dict[str, Any]:
    """Project canonical product evidence into generated JSONL for dbt."""
    root = root.resolve()
    output_dir = output_dir.resolve()
    products_root = root / "config" / "products"

    product_rows: list[dict[str, Any]] = []
    gate_rows: list[dict[str, Any]] = []
    run_rows: list[dict[str, Any]] = []

    for job_path in sorted(products_root.glob("*/job.json")):
        job = _read_json(job_path)
        product_id = str(job.get("id") or job_path.parent.name)

        construction_path = job_path.parent / "construction.json"
        manifest_text = job.get("productManifestPath")
        manifest_path = (
            root / manifest_text
            if isinstance(manifest_text, str) and manifest_text
            else root / "Assets" / "GenWorks" / product_id / "ProductManifest.json"
        )

        construction = _load_optional(construction_path)
        manifest = _load_optional(manifest_path)
        job_hash = _sha256(job_path)
        construction_hash = (
            _sha256(construction_path) if construction_path.is_file() else None
        )
        manifest_hash = _sha256(manifest_path) if manifest_path.is_file() else None

        product_rows.append(
            {
                "product_id": product_id,
                "product_name": job.get("productName"),
                "product_status": _state(manifest.get("status")) if manifest else None,
                "job_path": _relative(root, job_path),
                "construction_path": _relative(root, construction_path),
                "manifest_path": _relative(root, manifest_path),
                "job_exists": True,
                "construction_exists": construction_path.is_file(),
                "manifest_exists": manifest_path.is_file(),
                "job_product_id": job.get("id"),
                "construction_product_id": (
                    construction.get("productId") if construction else None
                ),
                "manifest_product_id": manifest.get("productId") if manifest else None,
                "job_sha256": job_hash,
                "construction_sha256": construction_hash,
                "manifest_sha256": manifest_hash,
            }
        )

        if manifest is None or manifest_hash is None:
            continue

        run_rows.append(
            {
                "run_id": f"{product_id}:{manifest_hash}",
                "product_id": product_id,
                "manifest_path": _relative(root, manifest_path),
                "manifest_sha256": manifest_hash,
                "generated_at": manifest.get("generatedAt"),
                "design_revision": manifest.get("designRevision"),
                "run_status": _state(manifest.get("status")),
            }
        )

        for family, field in (
            ("completion", "completionGates"),
            ("technical", "technicalGates"),
        ):
            values = manifest.get(field)
            if not isinstance(values, dict):
                continue
            for gate_name, gate_state in sorted(values.items()):
                gate_rows.append(
                    {
                        "product_id": product_id,
                        "run_id": f"{product_id}:{manifest_hash}",
                        "gate_family": family,
                        "gate_name": str(gate_name),
                        "gate_state": _state(gate_state),
                        "manifest_path": _relative(root, manifest_path),
                        "manifest_sha256": manifest_hash,
                    }
                )

    paths = {
        "products": output_dir / "products.jsonl",
        "runs": output_dir / "runs.jsonl",
        "gates": output_dir / "gates.jsonl",
    }
    _write_jsonl(paths["products"], product_rows)
    _write_jsonl(paths["runs"], run_rows)
    _write_jsonl(paths["gates"], gate_rows)

    return {
        "schemaVersion": 1,
        "productCount": len(product_rows),
        "runCount": len(run_rows),
        "gateCount": len(gate_rows),
        "paths": {name: str(path) for name, path in paths.items()},
    }
