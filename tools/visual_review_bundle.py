#!/usr/bin/env python3
"""Build and validate hash-bound visual review bundles for image2outfit."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def read_object(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise ValueError(f"path escapes repository: {value}")
    return resolved


def _bundle_digest(bundle: Mapping[str, Any]) -> str:
    return stable_sha256(
        {key: value for key, value in bundle.items() if key != "bundleSha256"}
    )


def _criterion_map(spec: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for aspect in spec.get("aspects", []):
        if isinstance(aspect, dict) and not aspect.get("computed"):
            result[str(aspect["id"])] = {
                "defectCode": aspect["defectCode"],
                "recommendedReturnStage": aspect["returnStage"],
                "completionGate": aspect["completionGate"],
                "targetViews": list(aspect.get("targetViews", [])),
                "targetPoses": list(aspect.get("targetPoses", [])),
            }
    return result


def _reference_identity(
    product_id: str,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    path = ROOT / "config" / "products" / product_id / "reference.json"
    if path.is_file():
        reference = read_object(path)
        if reference.get("productId") != product_id:
            raise ValueError("reference product identity mismatch")
        digest = reference.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError("reference SHA-256 is missing")
        observed = reference.get("observedViews")
        observed_views = (
            [str(value) for value in observed] if isinstance(observed, list) else []
        )
        return {
            "kind": "reference-manifest",
            "path": path.relative_to(ROOT).as_posix(),
            "manifestSha256": sha256_file(path),
            "sourceSha256": digest,
            "observedViews": observed_views,
        }

    source = str(request.get("sourceReference") or "")
    prefix = "private-reference://sha256/"
    digest = source.removeprefix(prefix)
    if not source.startswith(prefix) or len(digest) != 64:
        raise ValueError("reference identity is unavailable")
    return {
        "kind": "private-reference",
        "path": None,
        "manifestSha256": None,
        "sourceSha256": digest,
        "observedViews": [],
    }


def build_review_bundle(
    job_path: str | Path,
    request_path: str | Path,
    *,
    previous_bundle_path: str | Path | None = None,
) -> dict[str, Any]:
    job_path = repo_path(job_path)
    request_path = repo_path(request_path)
    job = read_object(job_path)
    request = read_object(request_path)
    if (
        job.get("schemaVersion") != 2
        or request.get("schemaVersion") != 1
        or job.get("id") != request.get("productId")
    ):
        raise ValueError("job/request identity mismatch")

    product_id = str(job["id"])
    manifest_path = repo_path(job["productManifestPath"])
    manifest = read_object(manifest_path)
    if manifest.get("productId") != product_id:
        raise ValueError("product manifest identity mismatch")

    quality_path = ROOT / "contracts" / "quality" / "quality-spec.json"
    quality = read_object(quality_path)
    direct = quality["directImageReview"]
    required_views = list(direct["requiredViews"])
    required_poses = list(direct["requiredPoses"])
    previews = job.get("previewPaths") or {}
    poses = job.get("posePaths") or {}

    missing_views = [view for view in required_views if view not in previews]
    missing_poses = [pose for pose in required_poses if pose not in poses]
    if missing_views or missing_poses:
        raise ValueError(
            "required visual evidence paths missing: "
            f"views={missing_views}, poses={missing_poses}"
        )

    images: list[dict[str, Any]] = []
    for kind, names, mapping in (
        ("view", required_views, previews),
        ("pose", required_poses, poses),
    ):
        for name in names:
            path = repo_path(mapping[name])
            if not path.is_file():
                raise FileNotFoundError(path)
            images.append(
                {
                    "kind": kind,
                    "name": name,
                    "path": path.relative_to(ROOT).as_posix(),
                    "sha256": sha256_file(path),
                }
            )

    protocol = {
        "schemaVersion": 1,
        "renderLoopRevision": job.get("renderLoopRevision")
        or job.get("buildRevision"),
        "adapterId": job["adapterId"],
        "views": required_views,
        "poses": required_poses,
    }
    if not protocol["renderLoopRevision"]:
        raise ValueError("job must bind renderLoopRevision or buildRevision")

    reference = _reference_identity(product_id, request)
    observed = set(reference.get("observedViews") or [])
    assessability = {
        view: "ASSESSABLE" if view in observed else "NOT_ASSESSABLE"
        for view in required_views
    }

    bundle: dict[str, Any] = {
        "schemaVersion": 1,
        "productId": product_id,
        "revisionId": str(request.get("revisionId") or ""),
        "jobSha256": sha256_file(job_path),
        "candidateManifest": {
            "path": manifest_path.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(manifest_path),
        },
        "reference": reference,
        "referenceAssessability": assessability,
        "renderProtocol": protocol,
        "renderProtocolSha256": stable_sha256(protocol),
        "qualitySpec": {
            "path": quality_path.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(quality_path),
            "specId": quality["specId"],
        },
        "criteria": _criterion_map(quality),
        "currentImages": images,
        "previousBundle": None,
    }

    if previous_bundle_path:
        previous_path = repo_path(previous_bundle_path)
        previous = read_object(previous_path)
        if (
            previous.get("productId") != product_id
            or previous.get("renderProtocolSha256")
            != bundle["renderProtocolSha256"]
        ):
            raise ValueError("previous bundle identity/protocol mismatch")
        if previous.get("bundleSha256") != _bundle_digest(previous):
            raise ValueError("previous bundle hash mismatch")
        bundle["previousBundle"] = {
            "path": previous_path.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(previous_path),
            "bundleSha256": previous["bundleSha256"],
            "candidateManifestSha256": previous["candidateManifest"]["sha256"],
        }

    bundle["bundleSha256"] = _bundle_digest(bundle)
    return bundle


def validate_review_result(
    review: Mapping[str, Any],
    bundle: Mapping[str, Any],
) -> list[dict[str, Any]]:
    expected = {
        "schemaVersion": 1,
        "productId": bundle["productId"],
        "reviewBundleSha256": bundle["bundleSha256"],
        "candidateManifestSha256": bundle["candidateManifest"]["sha256"],
        "renderProtocolSha256": bundle["renderProtocolSha256"],
    }
    for key, value in expected.items():
        if review.get(key) != value:
            raise ValueError(f"review binding mismatch: {key}")

    opinions = review.get("opinions")
    if not isinstance(opinions, list) or not opinions:
        raise ValueError("review opinions are required")

    criteria = bundle["criteria"]
    findings: list[dict[str, Any]] = []
    for index, item in enumerate(opinions):
        if not isinstance(item, dict):
            raise ValueError(f"opinion[{index}] must be an object")

        criterion = item.get("criterionId")
        if criterion not in criteria:
            raise ValueError(f"opinion[{index}] criterion is unknown")

        status = item.get("status")
        if status not in {"PASS", "FAIL", "NOT_ASSESSABLE"}:
            raise ValueError(f"opinion[{index}] status is invalid")

        view = item.get("view")
        pose = item.get("pose")
        if view is not None and view not in bundle["renderProtocol"]["views"]:
            raise ValueError(f"opinion[{index}] view is invalid")
        if pose is not None and pose not in bundle["renderProtocol"]["poses"]:
            raise ValueError(f"opinion[{index}] pose is invalid")

        if (
            status == "PASS"
            and view is not None
            and bundle["referenceAssessability"].get(view) == "NOT_ASSESSABLE"
            and criterion in {"silhouette", "styling-fidelity"}
        ):
            raise ValueError(
                f"opinion[{index}] cannot PASS reference fidelity for an unobserved view"
            )

        for field in ("observedDefect", "probableCause"):
            if status == "FAIL" and (
                not isinstance(item.get(field), str) or not item[field].strip()
            ):
                raise ValueError(f"opinion[{index}].{field} is required")

        confidence = item.get("confidence")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
        ):
            raise ValueError(f"opinion[{index}].confidence is invalid")

        if status == "FAIL":
            metadata = criteria[criterion]
            findings.append(
                {
                    "code": metadata["defectCode"],
                    "aspect": criterion,
                    "view": view,
                    "pose": pose,
                    "region": item.get("region"),
                    "observedDefect": item["observedDefect"],
                    "probableCause": item["probableCause"],
                    "confidence": confidence,
                    "recommendedReturnStage": metadata[
                        "recommendedReturnStage"
                    ],
                    "completionGate": metadata["completionGate"],
                }
            )

    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    bundle_parser = subparsers.add_parser("bundle")
    bundle_parser.add_argument("--job", required=True)
    bundle_parser.add_argument("--request", required=True)
    bundle_parser.add_argument("--output", required=True)
    bundle_parser.add_argument("--previous")

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--bundle", required=True)
    validate_parser.add_argument("--review", required=True)
    validate_parser.add_argument("--output", required=True)

    args = parser.parse_args()
    if args.command == "bundle":
        result = build_review_bundle(
            args.job,
            args.request,
            previous_bundle_path=args.previous,
        )
    else:
        result = {
            "schemaVersion": 1,
            "findings": validate_review_result(
                read_object(args.review),
                read_object(args.bundle),
            ),
        }

    output = (
        repo_path(args.output)
        if not Path(args.output).is_absolute()
        else Path(args.output)
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
