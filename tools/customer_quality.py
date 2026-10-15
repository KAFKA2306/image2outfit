#!/usr/bin/env python3
from __future__ import annotations

import struct
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import production_contract as contract
from quality_schema import load_schema, violation_labels

HUMAN_EVIDENCE_SCHEMA = "human-evidence.schema.v2.json"


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _member(value: Any, options: set[str]) -> bool:
    return isinstance(value, str) and value in options


def _utc(value: Any) -> datetime | None:
    if not _text(value):
        return None
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _candidate_path(value: Any) -> str | None:
    if not _text(value):
        return None
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or normalized.startswith("./"):
        return None
    return path.as_posix()


def _candidate_manifest_schema() -> dict[str, Any]:
    base = load_schema(HUMAN_EVIDENCE_SCHEMA)
    return {**base, "$ref": "#/$defs/candidateManifest"}


def _candidate_index(
    manifest: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    errors = [
        f"candidateManifest.{label}"
        for label in violation_labels(_candidate_manifest_schema(), manifest)
    ]
    result: dict[str, dict[str, Any]] = {}
    files = manifest.get("files")
    for index, item in enumerate(files if isinstance(files, list) else []):
        if not isinstance(item, dict):
            continue
        name = _candidate_path(item.get("path"))
        if name is None:
            errors.append(f"candidateManifest.files[{index}].path")
            continue
        if name in result:
            errors.append(f"candidateManifest.duplicate:{name}")
            continue
        result[name] = item
    return result, errors


def _reviewed_assets(
    evidence: dict[str, Any],
    required: list[str],
    candidate_files: dict[str, dict[str, Any]],
) -> list[str]:
    failures: list[str] = []
    values = evidence.get("reviewedAssets")
    if not isinstance(values, list):
        return failures
    normalized: set[str] = set()
    for index, value in enumerate(values):
        name = _candidate_path(value)
        if name is None:
            failures.append(f"reviewedAssets[{index}]")
            continue
        if name in normalized:
            failures.append(f"reviewedAssets.duplicate:{name}")
        normalized.add(name)
        if name not in candidate_files:
            failures.append(f"reviewedAssets.missing:{name}")
    for name in required:
        if name not in normalized:
            failures.append(f"reviewedAssets.required:{name}")
    return failures


def _defect_rules(common: dict[str, Any]) -> dict[str, Any]:
    return {
        "allOf": [
            {
                "properties": {
                    "severity": {
                        "enum": list(common.get("allowedDefectSeverities", []))
                    },
                    "status": {"enum": list(common.get("allowedDefectStatuses", []))},
                }
            },
            {
                "if": {
                    "required": ["status"],
                    "properties": {
                        "status": {"const": common.get("acceptedDefectStatus")}
                    },
                },
                "then": {
                    "required": ["acceptanceRationale"],
                    "properties": {
                        "acceptanceRationale": {"$ref": "#/$defs/text"}
                    },
                },
            },
        ]
    }


def _kind_rules(
    kind: str, kind_contract: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    pass_value = kind_contract.get("passValue")
    if kind == "visual-review":
        score_fields = list(kind_contract.get("scoreFields", []))
        minimum = kind_contract.get("minimumScore", 0)
        return {
            "properties": {
                "scores": {
                    "required": score_fields,
                    "properties": {
                        field: {"type": "number", "minimum": minimum}
                        for field in score_fields
                    },
                },
                **{
                    field: {"$ref": "#/$defs/text"}
                    for field in kind_contract.get("requiredTextFields", [])
                },
            }
        }
    if kind == "pose-penetration-review":
        poses = list(policy.get("requiredPoses", []))
        return {
            "properties": {
                "poses": {
                    "required": poses,
                    "properties": {pose: {"const": pass_value} for pose in poses},
                },
                "poseEvidence": {
                    "required": poses,
                    "properties": {
                        pose: {"$ref": "#/$defs/candidatePath"} for pose in poses
                    },
                },
            }
        }
    if kind == "vrchat-runtime-review":
        fields = list(kind_contract.get("customerAcceptanceFields", []))
        return {
            "properties": {
                "vrchatBuildAndTest": {"const": pass_value},
                "customerAcceptance": {
                    "required": fields,
                    "properties": {field: {"const": pass_value} for field in fields},
                },
            }
        }
    return {}


def _evidence_schema(
    kind: str,
    policy: dict[str, Any],
    job: dict[str, Any],
    candidate_hash: str,
) -> dict[str, Any]:
    """Compose the shared evidence shapes with this release policy's values."""
    contracts = policy["humanEvidenceContracts"]
    common = contracts.get("common", {})
    kind_contract = contracts.get(kind)
    if not isinstance(kind_contract, dict):
        kind_contract = {}
    base = load_schema(HUMAN_EVIDENCE_SCHEMA)
    parts: list[dict[str, Any]] = [
        {"$ref": "#/$defs/common"},
        {
            "required": [
                *contracts.get("commonRequiredFields", []),
                *kind_contract.get("requiredFields", []),
            ]
        },
        {
            "properties": {
                "schemaVersion": {"const": contracts.get("schemaVersion")},
                "kind": {"const": kind},
                "jobId": {"const": job.get("id")},
                "adapterId": {"const": job.get("adapterId")},
                "candidateManifestSha256": {"const": candidate_hash},
                "status": {"const": contracts.get("passStatus")},
                "defects": {"items": _defect_rules(common)},
            }
        },
        _kind_rules(kind, kind_contract, policy),
    ]
    if kind in base["$defs"]:
        parts.append({"$ref": f"#/$defs/{kind}"})
    return {**base, "allOf": parts}


def _defects(
    evidence: dict[str, Any],
    common: dict[str, Any],
    candidate_files: dict[str, dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Semantic defect checks; shape is enforced by the human-evidence schema."""
    failures: list[str] = []
    blocking: list[dict[str, Any]] = []
    defects = evidence.get("defects")
    if not isinstance(defects, list):
        return failures, blocking

    blocking_severities = set(common.get("blockingDefectSeverities", []))
    closed_statuses = set(common.get("closedDefectStatuses", []))

    seen: set[str] = set()
    for index, defect in enumerate(defects):
        if not isinstance(defect, dict):
            continue
        prefix = f"defects[{index}]"
        defect_id = defect.get("id")
        if isinstance(defect_id, str):
            if defect_id in seen:
                failures.append(f"{prefix}.id")
            seen.add(defect_id)
        paths = defect.get("evidencePaths")
        for path_index, value in enumerate(paths if isinstance(paths, list) else []):
            name = _candidate_path(value)
            if name is None or name not in candidate_files:
                failures.append(f"{prefix}.evidencePaths[{path_index}]")
        if _member(defect.get("severity"), blocking_severities) and not _member(
            defect.get("status"), closed_statuses
        ):
            blocking.append(defect)
    if blocking:
        failures.append("blockingDefects")
    return failures, blocking


def png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("runtime screenshot must be PNG")
    return struct.unpack(">II", header[16:24])


def validate(
    *,
    job: dict[str, Any],
    policy: dict[str, Any],
    candidate_manifest: dict[str, Any],
    candidate_hash: str,
    evidence: dict[str, dict[str, Any]],
    resolve_repo_path: Callable[[str], Path],
    digest: Callable[[Path], str],
) -> tuple[dict[str, Any], list[str]]:
    contracts = policy.get("humanEvidenceContracts")
    if not isinstance(contracts, dict):
        return {}, ["release-policy: humanEvidenceContracts"]

    candidate_files, manifest_failures = _candidate_index(candidate_manifest)
    errors = list(manifest_failures)
    result: dict[str, Any] = {}
    candidate_created_at = _utc(candidate_manifest.get("createdAt"))
    if candidate_created_at is None:
        errors.append("candidateManifest.createdAt")

    common = contracts.get("common", {})
    reviewer_prefix = common.get("reviewerPrefix", "human:")
    forbidden_reviewers = {
        str(value).strip().lower() for value in common.get("forbiddenReviewers", [])
    }
    allowed_reference_hosts = set(common.get("reviewerReferenceHosts", ["github.com"]))
    required_kinds = policy.get("requiredHumanEvidenceKinds", [])

    for kind in required_kinds:
        item_failures: list[str] = []
        value = evidence.get(kind, {})
        if not isinstance(value, dict):
            value = {}

        evidence_contract = contracts.get(kind)
        if not isinstance(evidence_contract, dict):
            item_failures.append("contract")
            evidence_contract = {}
        item_failures.extend(
            violation_labels(_evidence_schema(kind, policy, job, candidate_hash), value)
        )

        checked_at = _utc(value.get("checkedAt"))
        reviewer = value.get("reviewer")
        if checked_at is None:
            item_failures.append("checkedAt")
        if not (
            checked_at is not None
            and candidate_created_at is not None
            and checked_at >= candidate_created_at
        ):
            item_failures.append("checkedAfterCandidate")
        if not (
            _text(reviewer)
            and reviewer.startswith(reviewer_prefix)
            and reviewer.strip().lower() not in forbidden_reviewers
        ):
            item_failures.append("reviewer")
        if not contract.valid_review_reference(
            value.get("reviewerReference"), allowed_reference_hosts
        ):
            item_failures.append("reviewerReference")

        defect_failures, blocking_defects = _defects(value, common, candidate_files)
        item_failures.extend(defect_failures)

        if kind == "visual-review":
            scores = value.get("scores")
            if not isinstance(scores, dict):
                scores = {}
            collected = [
                float(scores[field])
                for field in evidence_contract.get("scoreFields", [])
                if _is_number(scores.get(field))
            ]
            minimum_average = evidence_contract.get("minimumAverageScore", 0)
            if not collected or sum(collected) / len(collected) < minimum_average:
                item_failures.append("scores.average")
            if value.get("criticalDefects") != 0:
                item_failures.append("criticalDefects")
            item_failures.extend(
                _reviewed_assets(
                    value,
                    list(evidence_contract.get("requiredPreviewAssets", [])),
                    candidate_files,
                )
            )

        elif kind == "pose-penetration-review":
            pose_evidence = value.get("poseEvidence")
            if not isinstance(pose_evidence, dict):
                pose_evidence = {}
            required_assets: list[str] = []
            seen_pose_assets: set[str] = set()
            for pose in policy.get("requiredPoses", []):
                name = _candidate_path(pose_evidence.get(pose))
                if name is None or name not in candidate_files:
                    item_failures.append(f"poseEvidence.{pose}")
                elif name in seen_pose_assets:
                    item_failures.append(f"poseEvidence.duplicate:{name}")
                else:
                    seen_pose_assets.add(name)
                    required_assets.append(name)
            if value.get("criticalPenetrations") != 0:
                item_failures.append("criticalPenetrations")
            item_failures.extend(_reviewed_assets(value, required_assets, candidate_files))

        elif kind == "vrchat-runtime-review":
            screenshot = value.get("runtimeScreenshot")
            if _text(screenshot):
                try:
                    screenshot_path = resolve_repo_path(screenshot)
                    width, height = png_size(screenshot_path)
                    if width < evidence_contract.get("minimumScreenshotWidth", 0):
                        item_failures.append("runtimeScreenshot.width")
                    if height < evidence_contract.get("minimumScreenshotHeight", 0):
                        item_failures.append("runtimeScreenshot.height")
                    if digest(screenshot_path) != value.get("runtimeScreenshotSha256"):
                        item_failures.append("runtimeScreenshotSha256")
                except (OSError, ValueError):
                    item_failures.append("runtimeScreenshot")

        unique = sorted(set(item_failures))
        result[kind] = {
            "passed": not unique,
            "failedFields": unique,
            "reviewer": value.get("reviewer"),
            "reviewerReference": value.get("reviewerReference"),
            "evidenceSha256": digest(resolve_repo_path(job["humanEvidence"][kind]))
            if kind in job.get("humanEvidence", {})
            and resolve_repo_path(job["humanEvidence"][kind]).is_file()
            else None,
            "blockingDefects": [
                {
                    "id": defect.get("id"),
                    "severity": defect.get("severity"),
                    "status": defect.get("status"),
                }
                for defect in blocking_defects
            ],
        }
        errors.extend(f"{kind}: {failure}" for failure in unique)

    return result, list(dict.fromkeys(errors))
