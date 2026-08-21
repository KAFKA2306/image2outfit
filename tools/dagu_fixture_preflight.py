#!/usr/bin/env python3
"""Preflight canonical research fixtures before handing them to Dagu.

The scheduler must never invent a pipeline request or source identity merely to
make a fixture queueable. This module derives readiness from tracked canonical
files and emits only requests that are executable under the existing pipeline
contract.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_CONFIG = Path("config/pipeline/research-benchmark-fixtures.v1.json")
REQUEST_ROOT = Path("config/pipeline/requests")
QUEUE_NAME = "product-execution"


def _read_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object: {path}")
    return value


def _relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _identity_path(job: dict[str, Any], product_id: str) -> Path:
    garment_pipeline = job.get("garmentPipeline")
    configured = (
        garment_pipeline.get("identityManifestPath")
        if isinstance(garment_pipeline, dict)
        else None
    )
    if isinstance(configured, str) and configured:
        return ROOT / configured
    return ROOT / "config" / "products" / product_id / "reference-identity.json"


def build_preflight() -> dict[str, Any]:
    fixture_path = ROOT / FIXTURE_CONFIG
    config = _read_object(fixture_path, "fixture config")
    fixtures = config.get("fixtures")
    if not isinstance(fixtures, list):
        raise ValueError("fixture config fixtures must be a list")

    entries: list[dict[str, Any]] = []
    queue_candidates: list[dict[str, str]] = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise ValueError("fixture entries must be JSON objects")
        fixture_id = str(fixture["fixtureId"])
        product_id = str(fixture["productId"])
        job_path = ROOT / str(fixture["jobPath"])
        blockers: list[str] = []

        if not job_path.is_file():
            blockers.append("missing-product-job")
            job: dict[str, Any] = {}
        else:
            job = _read_object(job_path, "product job")
            if job.get("id") != product_id:
                blockers.append("product-job-identity-mismatch")

        request_path = ROOT / REQUEST_ROOT / f"{product_id}.json"
        request: dict[str, Any] | None = None
        if not request_path.is_file():
            blockers.append("missing-canonical-request")
        else:
            request = _read_object(request_path, "pipeline request")
            if request.get("schemaVersion") != 1:
                blockers.append("unsupported-request-schema")
            if request.get("productId") != product_id:
                blockers.append("request-product-identity-mismatch")

        identity_path = _identity_path(job, product_id)
        identity: dict[str, Any] | None = None
        if not identity_path.is_file():
            blockers.append("missing-reference-identity")
        else:
            identity = _read_object(identity_path, "reference identity")
            if identity.get("productId") != product_id:
                blockers.append("reference-identity-product-mismatch")

        if request is not None and identity is not None:
            if request.get("sourceReference") != identity.get("sourceReference"):
                blockers.append("reference-identity-source-mismatch")

        blockers = list(dict.fromkeys(blockers))
        status = "READY" if not blockers else "BLOCKED"
        entry = {
            "fixtureId": fixture_id,
            "productId": product_id,
            "jobPath": _relative(job_path),
            "requestPath": _relative(request_path) if request_path.is_file() else None,
            "referenceIdentityPath": (
                _relative(identity_path) if identity_path.is_file() else None
            ),
            "status": status,
            "blockers": blockers,
        }
        entries.append(entry)
        if status == "READY":
            queue_candidates.append(
                {
                    "fixtureId": fixture_id,
                    "productId": product_id,
                    "request": _relative(request_path),
                }
            )

    return {
        "schemaVersion": 1,
        "fixtureConfig": FIXTURE_CONFIG.as_posix(),
        "queue": QUEUE_NAME,
        "schedulerOwnsCompletion": False,
        "entries": entries,
        "readyCount": len(queue_candidates),
        "blockedCount": len(entries) - len(queue_candidates),
        "queueCandidates": queue_candidates,
    }


def main() -> int:
    print(json.dumps(build_preflight(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
