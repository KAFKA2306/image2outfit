#!/usr/bin/env python3
"""Bind actual private source bytes to a tracked reference identity manifest.

The source file is hashed locally and is never copied into the repository. The
tracked manifest contains only the content-addressed sourceReference and an
UNVERIFIED market-identity ledger. This tool cannot create an identity without
real source bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from image2outfit.identity import (  # noqa: E402
    IdentityClaim,
    IdentityEvidence,
    IdentityField,
    IdentityStatus,
    ReferenceIdentityManifest,
    load_reference_identity,
    make_identity_history_event,
)

UNVERIFIED_REASON = (
    "Private reference intake establishes source-byte identity only; no "
    "primary-source commercial identity evidence was verified."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product-id", required=True)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument(
        "--recorded-at",
        help="ISO 8601 audit timestamp. Defaults to the current UTC time.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Override config/products/<product-id>/reference-identity.json.",
    )
    return parser.parse_args()


def _read_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _recorded_at(value: str | None) -> str:
    if value:
        return value
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_manifest(
    *, product_id: str, source_reference: str, recorded_at: str
) -> ReferenceIdentityManifest:
    evidence = IdentityEvidence(
        evidence_id="private-reference-bytes",
        evidence_type="private-source-byte-binding",
        source_reference=source_reference,
        captured_at=recorded_at,
        extraction_method="local-sha256",
        reviewer_role="reference-intake",
        note=(
            "Private source bytes were hashed locally and were not redistributed "
            "into the repository."
        ),
    )
    claims = tuple(
        IdentityClaim(
            field=field,
            status=IdentityStatus.UNVERIFIED,
            value=None,
            reason=UNVERIFIED_REASON,
            evidence_ids=(),
        )
        for field in IdentityField
    )
    history = []
    previous = "0" * 64
    for sequence, field in enumerate(IdentityField, start=1):
        event = make_identity_history_event(
            sequence=sequence,
            field=field,
            status=IdentityStatus.UNVERIFIED,
            value=None,
            reason=UNVERIFIED_REASON,
            evidence_ids=(),
            actor_role="reference-intake",
            recorded_at=recorded_at,
            previous_digest=previous,
        )
        history.append(event)
        previous = event.event_digest
    return ReferenceIdentityManifest(
        product_id=product_id,
        source_reference=source_reference,
        claims=claims,
        evidence=(evidence,),
        history=tuple(history),
    )


def _assert_private_source_location(source: Path, job: dict[str, Any]) -> None:
    root = ROOT.resolve()
    source = source.resolve()
    if source != root and root not in source.parents:
        return
    configured = job.get("privateSourceRoots", [])
    if not isinstance(configured, list):
        raise ValueError("job.privateSourceRoots must be a list")
    allowed = [
        (ROOT / value).resolve()
        for value in configured
        if isinstance(value, str) and value
    ]
    if not any(source == candidate or candidate in source.parents for candidate in allowed):
        raise ValueError(
            "repository-local private reference must be under job.privateSourceRoots"
        )


def _write_manifest(path: Path, manifest: ReferenceIdentityManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(manifest.to_mapping(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    args = parse_args()
    job_path = ROOT / "config" / "products" / args.product_id / "job.json"
    if not job_path.is_file():
        raise FileNotFoundError(f"tracked product job is missing: {job_path}")
    job = _read_object(job_path, "product job")
    if job.get("id") != args.product_id:
        raise ValueError("product job identity mismatch")

    source = args.source.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"private reference file is missing: {source}")
    _assert_private_source_location(source, job)
    digest = _sha256(source)
    source_reference = f"private-reference://sha256/{digest}"
    recorded_at = _recorded_at(args.recorded_at)
    output = (
        args.output
        if args.output is not None
        else Path("config/products") / args.product_id / "reference-identity.json"
    )
    output = output.resolve() if output.is_absolute() else (ROOT / output).resolve()
    if output != ROOT and ROOT not in output.parents:
        raise ValueError("identity output must remain inside the repository")

    if output.is_file():
        existing = load_reference_identity(output)
        if existing.product_id != args.product_id:
            raise ValueError("existing identity manifest product mismatch")
        if existing.source_reference != source_reference:
            raise ValueError(
                "existing identity is bound to different source bytes; identity "
                "history must be updated explicitly instead of overwritten"
            )
        manifest = existing
        unchanged = True
    else:
        manifest = build_manifest(
            product_id=args.product_id,
            source_reference=source_reference,
            recorded_at=recorded_at,
        )
        _write_manifest(output, manifest)
        unchanged = False

    print(
        json.dumps(
            {
                "schemaVersion": 1,
                "productId": args.product_id,
                "sourceReference": source_reference,
                "identityManifest": output.relative_to(ROOT).as_posix(),
                "manifestDigest": manifest.manifest_digest,
                "sourceRedistributed": False,
                "unchanged": unchanged,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
