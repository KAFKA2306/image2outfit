#!/usr/bin/env python3
"""Normalize hash-verified private reference bytes without fabricating garment pixels."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
NORMALIZATION_METHOD = "crop-from-private-source"
PRIVATE_REFERENCE_VARIABLE = "privateReferencePath"
IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    return parser.parse_args()


def read_object(path: Path, label: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return payload


def repo_path(value: str | Path, *, label: str) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise ValueError(f"{label} escapes repository: {value}")
    return resolved


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def _private_roots(job: Mapping[str, Any]) -> list[Path]:
    configured = job.get("privateSourceRoots", [])
    if not isinstance(configured, list) or not configured or not all(
        isinstance(value, str) and value for value in configured
    ):
        raise ValueError("job.privateSourceRoots must be a non-empty string list")
    return [repo_path(value, label="private source root") for value in configured]


def _assert_private_source_location(source: Path, roots: list[Path]) -> None:
    source = source.resolve()
    if source != ROOT and ROOT not in source.parents:
        return
    if not any(source == root or root in source.parents for root in roots):
        raise ValueError(
            "repository-local private reference must be under job.privateSourceRoots"
        )


def _explicit_private_source(
    request: Mapping[str, Any], roots: list[Path], expected_sha256: str
) -> Path | None:
    variables = request.get("variables")
    if variables is None:
        return None
    if not isinstance(variables, Mapping):
        raise ValueError("request.variables must be an object")
    value = variables.get(PRIVATE_REFERENCE_VARIABLE)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(
            f"request.variables.{PRIVATE_REFERENCE_VARIABLE} must be a non-empty path"
        )
    source = Path(value).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"private reference file is missing: {source}")
    _assert_private_source_location(source, roots)
    actual_sha256 = sha256(source)
    if actual_sha256 != expected_sha256:
        raise ValueError(
            "private reference hash mismatch: "
            f"expected {expected_sha256}, found {actual_sha256}"
        )
    return source


def _discover_private_source(roots: list[Path], expected_sha256: str) -> Path:
    matches: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for candidate in sorted(root.rglob("*")):
            if (
                candidate.is_file()
                and candidate.suffix.lower() in IMAGE_SUFFIXES
                and sha256(candidate) == expected_sha256
            ):
                matches.append(candidate.resolve())
    if not matches:
        raise FileNotFoundError(
            "no private reference image under job.privateSourceRoots matches "
            f"SHA-256 {expected_sha256}"
        )
    unique = sorted(set(matches))
    if len(unique) != 1:
        raise ValueError(
            "multiple private reference images match the audited SHA-256; "
            "remove duplicate private copies or bind privateReferencePath explicitly"
        )
    return unique[0]


def _private_source(
    request: Mapping[str, Any], job: Mapping[str, Any], expected_sha256: str
) -> Path:
    roots = _private_roots(job)
    explicit = _explicit_private_source(request, roots, expected_sha256)
    if explicit is not None:
        return explicit
    return _discover_private_source(roots, expected_sha256)


def _bounding_box(
    value: object, *, width: int, height: int
) -> tuple[int, int, int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or not all(
            isinstance(item, int) and not isinstance(item, bool) for item in value
        )
    ):
        raise ValueError("variant.boundingBoxPx must contain four integers")
    left, top, right, bottom = value
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError(
            f"variant.boundingBoxPx is outside source image bounds {width}x{height}: {value}"
        )
    return left, top, right, bottom


def _evidence(paths: list[Path]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"stage evidence file is missing: {relative(path)}")
        digest = sha256(path)
        if digest in seen:
            raise ValueError(f"duplicate evidence digest: {relative(path)}")
        seen.add(digest)
        records.append({"path": relative(path), "sha256": digest})
    return records


def normalize(
    job: Mapping[str, Any], request: Mapping[str, Any], result_path: Path
) -> dict[str, Any]:
    product_id = str(job["id"])
    audit_path = repo_path(
        job["garmentPipeline"]["referenceAuditPath"], label="audit"
    )
    audit = read_object(audit_path, "reference audit")
    if audit.get("schemaVersion") != 1 or audit.get("productId") != product_id:
        raise ValueError("reference audit schema or product identity mismatch")
    source_info = audit.get("source")
    if not isinstance(source_info, Mapping):
        raise ValueError("reference audit source is required")
    expected_sha256 = source_info.get("originalSha256")
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise ValueError("reference audit source.originalSha256 is invalid")
    expected_reference = f"private-reference://sha256/{expected_sha256}"
    if request.get("sourceReference") != expected_reference:
        raise ValueError("request sourceReference does not match reference audit")

    source = _private_source(request, job, expected_sha256)
    output_root = ROOT / ".image2outfit" / "products" / product_id / "normalized"
    output_root.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    outputs: list[Path] = []
    with Image.open(source) as image:
        image.load()
        width, height = image.size
        if source_info.get("widthPx") != width or source_info.get("heightPx") != height:
            raise ValueError(
                "private reference dimensions do not match reference audit: "
                f"expected {source_info.get('widthPx')}x{source_info.get('heightPx')}, "
                f"found {width}x{height}"
            )
        variants = audit.get("variants")
        if not isinstance(variants, list) or not variants:
            raise ValueError("reference audit variants must be a non-empty list")
        for variant in variants:
            if not isinstance(variant, Mapping):
                raise ValueError("reference audit variant must be an object")
            variant_id = variant.get("variantId")
            if not isinstance(variant_id, str) or not variant_id:
                raise ValueError("variant.variantId is required")
            bbox = _bounding_box(
                variant.get("boundingBoxPx"), width=width, height=height
            )
            output = output_root / f"{variant_id}.png"
            image.crop(bbox).save(output, format="PNG", optimize=True)
            outputs.append(output)
            records.append(
                {
                    "variantId": variant_id,
                    "sourceBoundingBoxPx": list(bbox),
                    "output": relative(output),
                    "normalizationMethod": NORMALIZATION_METHOD,
                }
            )

    report = write_json(
        output_root / "normalized-view.json",
        {
            "schemaVersion": 1,
            "productId": product_id,
            "status": "PASS",
            "sourceReference": expected_reference,
            "sourceSha256": expected_sha256,
            "sourceBytesVerified": True,
            "normalizationMethod": NORMALIZATION_METHOD,
            "sourceImageRedistributed": False,
            "records": records,
        },
    )
    result_payload = {
        "schemaVersion": 1,
        "stage": "normalize-view",
        "productId": product_id,
        "status": "PASS",
        "sourceBytesVerified": True,
        "normalizationMethod": NORMALIZATION_METHOD,
        "evidence": _evidence([audit_path, report, *outputs]),
    }
    write_json(result_path, result_payload)
    return result_payload


def main() -> int:
    args = parse_args()
    job_path = repo_path(args.job, label="job")
    request_path = repo_path(args.request, label="request")
    result_path = repo_path(args.result, label="result")
    runtime = (ROOT / ".image2outfit").resolve()
    if result_path != runtime and runtime not in result_path.parents:
        raise ValueError("result must be inside .image2outfit runtime state")
    job = read_object(job_path, "job")
    request = read_object(request_path, "request")
    if job.get("schemaVersion") != 2 or request.get("schemaVersion") != 1:
        raise ValueError("job/request schema version mismatch")
    if job.get("id") != request.get("productId"):
        raise ValueError("job/request product identity mismatch")
    normalize(job, request, result_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
