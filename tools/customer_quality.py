#!/usr/bin/env python3
from __future__ import annotations

import re
import struct
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


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


def _candidate_index(manifest: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    result: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        return result, ["candidateManifest.files"]
    for index, item in enumerate(files):
        if not isinstance(item, dict):
            errors.append(f"candidateManifest.files[{index}]")
            continue
        name = _candidate_path(item.get("path"))
        if name is None:
            errors.append(f"candidateManifest.files[{index}].path")
            continue
        if name in result:
            errors.append(f"candidateManifest.duplicate:{name}")
            continue
        if not isinstance(item.get("bytes"), int) or item["bytes"] < 0:
            errors.append(f"candidateManifest.bytes:{name}")
        if not _text(item.get("sha256")) or not _SHA256.fullmatch(item["sha256"]):
            errors.append(f"candidateManifest.sha256:{name}")
        result[name] = item
    return result, errors


def _reviewed_assets(
    evidence: dict[str, Any],
    required: list[str],
    candidate_files: dict[str, dict[str, Any]],
) -> list[str]:
    failures: list[str] = []
    values = evidence.get("reviewedAssets")
    if not isinstance(values, list) or not values:
        return ["reviewedAssets"]
    normalized: set[str] = set()
    for index, value in enumerate(values):
        name = _candidate_path(value)
        if name is None:
            failures.append(f"reviewedAssets[{index}]")
            continue
        normalized.add(name)
        if name not in candidate_files:
            failures.append(f"reviewedAssets.missing:{name}")
    for name in required:
        if name not in normalized:
            failures.append(f"reviewedAssets.required:{name}")
    return failures


def _defects(
    evidence: dict[str, Any],
    contract: dict[str, Any],
    candidate_files: dict[str, dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]]]:
    failures: list[str] = []
    blocking: list[dict[str, Any]] = []
    defects = evidence.get("defects")
    if not isinstance(defects, list):
        return ["defects"], blocking

    severities = set(contract.get("allowedDefectSeverities", []))
    statuses = set(contract.get("allowedDefectStatuses", []))
    blocking_severities = set(contract.get("blockingDefectSeverities", []))
    closed_statuses = set(contract.get("closedDefectStatuses", []))
    accepted_status = contract.get("acceptedDefectStatus")

    seen: set[str] = set()
    for index, defect in enumerate(defects):
        prefix = f"defects[{index}]"
        if not isinstance(defect, dict):
            failures.append(prefix)
            continue
        defect_id = defect.get("id")
        severity = defect.get("severity")
        status = defect.get("status")
        if not _text(defect_id) or defect_id in seen:
            failures.append(f"{prefix}.id")
        else:
            seen.add(defect_id)
        if severity not in severities:
            failures.append(f"{prefix}.severity")
        if status not in statuses:
            failures.append(f"{prefix}.status")
        for field in ("category", "description"):
            if not _text(defect.get(field)):
                failures.append(f"{prefix}.{field}")
        paths = defect.get("evidencePaths")
        if not isinstance(paths, list) or not paths:
            failures.append(f"{prefix}.evidencePaths")
        else:
            for path_index, value in enumerate(paths):
                name = _candidate_path(value)
                if name is None or name not in candidate_files:
                    failures.append(f"{prefix}.evidencePaths[{path_index}]")
        if severity in blocking_severities and status not in closed_statuses:
            blocking.append(defect)
        if status == accepted_status and not _text(defect.get("acceptanceRationale")):
            failures.append(f"{prefix}.acceptanceRationale")
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
    required_kinds = policy.get("requiredHumanEvidenceKinds", [])

    for kind in required_kinds:
        item_failures: list[str] = []
        blocking_defects: list[dict[str, Any]] = []
        value = evidence.get(kind, {})
        if not isinstance(value, dict):
            value = {}

        checked_at = _utc(value.get("checkedAt"))
        reviewer = value.get("reviewer")
        common_checks = {
            "schemaVersion": value.get("schemaVersion") == contracts.get("schemaVersion"),
            "kind": value.get("kind") == kind,
            "jobId": value.get("jobId") == job.get("id"),
            "adapterId": value.get("adapterId") == job.get("adapterId"),
            "candidateManifestSha256": value.get("candidateManifestSha256") == candidate_hash,
            "status": value.get("status") == contracts.get("passStatus"),
            "checkedAt": checked_at is not None,
            "checkedAfterCandidate": checked_at is not None
            and candidate_created_at is not None
            and checked_at >= candidate_created_at,
            "reviewer": _text(reviewer)
            and reviewer.startswith(reviewer_prefix)
            and reviewer.strip().lower() not in forbidden_reviewers,
        }
        item_failures.extend(name for name, passed in common_checks.items() if not passed)

        contract = contracts.get(kind)
        if not isinstance(contract, dict):
            item_failures.append("contract")
            contract = {}
        for field in contract.get("requiredFields", []):
            if field not in value:
                item_failures.append(field)

        defect_failures, blocking_defects = _defects(value, common, candidate_files)
        item_failures.extend(defect_failures)

        if kind == "visual-review":
            scores = value.get("scores")
            collected: list[float] = []
            if not isinstance(scores, dict):
                item_failures.append("scores")
                scores = {}
            for field in contract.get("scoreFields", []):
                score = scores.get(field)
                if not isinstance(score, (int, float)) or isinstance(score, bool):
                    item_failures.append(f"scores.{field}")
                    continue
                collected.append(float(score))
                if score < contract.get("minimumScore", 0):
                    item_failures.append(f"scores.{field}")
            minimum_average = contract.get("minimumAverageScore", 0)
            if not collected or sum(collected) / len(collected) < minimum_average:
                item_failures.append("scores.average")
            if value.get("criticalDefects") != 0:
                item_failures.append("criticalDefects")
            for field in contract.get("requiredTextFields", []):
                if not _text(value.get(field)):
                    item_failures.append(field)
            item_failures.extend(
                _reviewed_assets(
                    value,
                    list(contract.get("requiredPreviewAssets", [])),
                    candidate_files,
                )
            )

        elif kind == "pose-penetration-review":
            poses = value.get("poses")
            pose_evidence = value.get("poseEvidence")
            if not isinstance(poses, dict):
                item_failures.append("poses")
                poses = {}
            if not isinstance(pose_evidence, dict):
                item_failures.append("poseEvidence")
                pose_evidence = {}
            required_assets: list[str] = []
            for pose in contract.get("requiredPoses", []):
                if poses.get(pose) != contract.get("passValue"):
                    item_failures.append(f"poses.{pose}")
                name = _candidate_path(pose_evidence.get(pose))
                if name is None or name not in candidate_files:
                    item_failures.append(f"poseEvidence.{pose}")
                else:
                    required_assets.append(name)
            if value.get("criticalPenetrations") != 0:
                item_failures.append("criticalPenetrations")
            if not _text(value.get("poseNotes")):
                item_failures.append("poseNotes")
            item_failures.extend(_reviewed_assets(value, required_assets, candidate_files))

        elif kind == "vrchat-runtime-review":
            if value.get("vrchatBuildAndTest") != contract.get("passValue"):
                item_failures.append("vrchatBuildAndTest")
            if value.get("testedInVRChat") is not True:
                item_failures.append("testedInVRChat")
            for field in ("runtimeNotes", "testedPlatform"):
                if not _text(value.get(field)):
                    item_failures.append(field)
            for field in ("installationStepsVerified", "customerReady"):
                if value.get(field) is not True:
                    item_failures.append(field)
            acceptance = value.get("customerAcceptance")
            if not isinstance(acceptance, dict):
                item_failures.append("customerAcceptance")
                acceptance = {}
            for field in contract.get("customerAcceptanceFields", []):
                if acceptance.get(field) != contract.get("passValue"):
                    item_failures.append(f"customerAcceptance.{field}")

            screenshot = value.get("runtimeScreenshot")
            screenshot_hash = value.get("runtimeScreenshotSha256")
            if not _text(screenshot):
                item_failures.append("runtimeScreenshot")
            else:
                try:
                    screenshot_path = resolve_repo_path(screenshot)
                    width, height = png_size(screenshot_path)
                    if width < contract.get("minimumScreenshotWidth", 0):
                        item_failures.append("runtimeScreenshot.width")
                    if height < contract.get("minimumScreenshotHeight", 0):
                        item_failures.append("runtimeScreenshot.height")
                    if not _SHA256.fullmatch(str(screenshot_hash or "")):
                        item_failures.append("runtimeScreenshotSha256")
                    elif digest(screenshot_path) != screenshot_hash:
                        item_failures.append("runtimeScreenshotSha256")
                except (OSError, ValueError):
                    item_failures.append("runtimeScreenshot")

        unique = sorted(set(item_failures))
        result[kind] = {
            "passed": not unique,
            "failedFields": unique,
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

    return result, errors
