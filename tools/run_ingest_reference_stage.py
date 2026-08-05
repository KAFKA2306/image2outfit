#!/usr/bin/env python3
"""Run ingest-reference and bind a validated product identity ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from image2outfit.identity import load_reference_identity


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("ingest-reference",), required=True)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    return parser.parse_args()


def repo_path(value: str | Path, *, label: str) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise ValueError(f"{label} escapes repository: {value}")
    return resolved


def read_object(path: Path, label: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return payload


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def main() -> int:
    args = parse_args()
    job_path = repo_path(args.job, label="job")
    request_path = repo_path(args.request, label="request")
    result_path = repo_path(args.result, label="result")
    job = read_object(job_path, "job")
    request = read_object(request_path, "request")
    identity_value = job.get("garmentPipeline", {}).get("identityManifestPath")
    if identity_value is None:
        identity_value = (
            f"config/products/{job.get('id', '')}/reference-identity.json"
        )
    if not isinstance(identity_value, str) or not identity_value:
        raise ValueError("identity manifest path must be a non-empty string")
    identity_path = repo_path(identity_value, label="identity manifest")
    identity = load_reference_identity(identity_path)
    if identity.product_id != job.get("id") or identity.product_id != request.get(
        "productId"
    ):
        raise ValueError("identity manifest product identity mismatch")
    if identity.source_reference != request.get("sourceReference"):
        raise ValueError("identity manifest sourceReference mismatch")

    command = [
        sys.executable,
        str(ROOT / "tools" / "run_reference_product_stage.py"),
        "--stage",
        args.stage,
        "--job",
        str(job_path),
        "--request",
        str(request_path),
        "--result",
        str(result_path),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="")
    if completed.returncode != 0:
        return completed.returncode

    payload = read_object(result_path, "ingest stage result")
    binding_path = (
        ROOT
        / ".image2outfit"
        / "products"
        / identity.product_id
        / "reference"
        / "identity-binding.json"
    )
    binding = {
        "schemaVersion": 1,
        "productId": identity.product_id,
        "sourceReference": identity.source_reference,
        "identityManifestPath": relative(identity_path),
        "identityManifestDigest": identity.manifest_digest,
        "statusSummary": identity.status_summary,
        "verifiedMarketIdentifiers": identity.verified_market_identifiers,
        "marketIdentityClaimed": bool(identity.verified_market_identifiers),
        "internalProductIdIsMarketIdentifier": False,
        "historyTailDigest": identity.history[-1].event_digest,
        "status": "PASS",
    }
    write_json(binding_path, binding)
    identity_evidence = [
        {"path": relative(identity_path), "sha256": sha256(identity_path)},
        {"path": relative(binding_path), "sha256": sha256(binding_path)},
    ]
    existing = payload.get("evidence")
    if not isinstance(existing, list):
        raise ValueError("ingest stage result evidence must be a list")
    existing_digests = {
        item.get("sha256") for item in existing if isinstance(item, dict)
    }
    for item in identity_evidence:
        if item["sha256"] in existing_digests:
            raise ValueError("identity evidence duplicates existing stage evidence")
        existing.append(item)
        existing_digests.add(item["sha256"])
    payload["identity"] = {
        "manifestPath": relative(identity_path),
        "manifestDigest": identity.manifest_digest,
        "statusSummary": identity.status_summary,
        "verifiedMarketIdentifiers": identity.verified_market_identifiers,
        "marketIdentityClaimed": bool(identity.verified_market_identifiers),
    }
    write_json(result_path, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
