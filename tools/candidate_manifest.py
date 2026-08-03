#!/usr/bin/env python3
"""Candidate identity, input, preview, and file-manifest contracts."""

from __future__ import annotations

import json
import os
import struct
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pipeline as legacy

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "release-policy.json"
JOB_SCHEMA_PATH = ROOT / "config" / "job.schema.v2.json"
UNITY_PIPELINE_PATH = (
    ROOT / "Assets" / "GenWorks" / "Shared" / "Editor" / "Image2OutfitPipeline.cs"
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(path)


def digest(path: Path) -> str:
    return legacy.sha256(path)


def path(value: str) -> Path:
    return legacy.repo_path(value)


def rel(value: Path) -> str:
    return str(value.resolve().relative_to(ROOT)).replace("\\", "/")


def inside(value: Path, root: Path) -> bool:
    value = value.resolve()
    root = root.resolve()
    return value == root or root in value.parents


def required_job_fields() -> tuple[str, ...]:
    schema = read(JOB_SCHEMA_PATH)
    required = schema.get("required")
    if (
        not isinstance(required, list)
        or not required
        or not all(isinstance(value, str) and value for value in required)
    ):
        raise ValueError("job.schema.v2.json must define a non-empty required array")
    expected_version = (
        schema.get("properties", {}).get("schemaVersion", {}).get("const")
    )
    if expected_version != 2:
        raise ValueError("job.schema.v2.json must require schemaVersion 2")
    return tuple(required)


def load(job_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    policy = read(POLICY_PATH)
    job = read(job_path)
    if policy.get("schemaVersion") != 1:
        raise ValueError("release-policy.json must use schemaVersion 1")
    if job.get("schemaVersion") != 2:
        raise ValueError("legacy jobs are disabled; schemaVersion must be 2")
    missing = [
        key for key in required_job_fields() if key not in job or job[key] in (None, "")
    ]
    if missing:
        raise ValueError(f"job v2 missing: {', '.join(missing)}")
    for field, prefix in (
        ("artifactDir", ".image2outfit/products/"),
        ("candidateDir", ".image2outfit/products/"),
        ("releaseDir", ".image2outfit/products/"),
    ):
        if field not in job or not rel(path(job[field])).startswith(prefix):
            raise ValueError(f"{field} must use the derived .image2outfit runtime root")
    views = set(policy["minimumPreview"]["requiredViews"])
    if views - set(job["previewPaths"]):
        raise ValueError("previewPaths does not contain every required view")
    kinds = set(policy["requiredHumanEvidenceKinds"])
    if kinds - set(job["humanEvidence"]):
        raise ValueError("humanEvidence does not contain every required kind")
    return job, policy


def license_gate(job: dict[str, Any]) -> tuple[bool, list[str]]:
    evidence = read(path(job["licenseEvidence"]))
    errors = []
    checks = {
        "adapterId": evidence.get("adapterId") == job["adapterId"],
        "sourceUrl": bool(evidence.get("sourceUrl")),
        "checkedAt": bool(evidence.get("checkedAt")),
        "commercialOutfitAllowed": evidence.get("commercialOutfitAllowed") is True,
        "avatarFilesRedistributed": evidence.get("avatarFilesRedistributed") is False,
    }
    errors.extend(name for name, passed in checks.items() if not passed)
    return not errors, errors


def png_size(file: Path) -> tuple[int, int]:
    header = file.read_bytes()[:24]
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not PNG")
    return struct.unpack(">II", header[16:24])


def preview_gate(
    job: dict[str, Any], policy: dict[str, Any]
) -> tuple[bool, dict[str, Any]]:
    minimum = policy["minimumPreview"]
    result: dict[str, Any] = {}
    passed = True
    for view in minimum["requiredViews"]:
        file = path(job["previewPaths"][view])
        item: dict[str, Any] = {"path": rel(file), "passed": False}
        try:
            width, height = png_size(file)
            item.update(width=width, height=height, sha256=digest(file))
            item["passed"] = width >= minimum["width"] and height >= minimum["height"]
        except (OSError, ValueError) as exc:
            item["error"] = str(exc)
        passed = passed and item["passed"]
        result[view] = item
    return passed, result


def inputs(job_path: Path, job: dict[str, Any]) -> dict[str, str]:
    files = {
        "job": job_path,
        "policy": POLICY_PATH,
        "jobSchema": JOB_SCHEMA_PATH,
        "toolchainLock": ROOT / "config" / "toolchain-lock.json",
        "pythonProject": ROOT / "pyproject.toml",
        "vpmManifest": ROOT / "Packages" / "vpm-manifest.json",
        "upmManifest": ROOT / "Packages" / "manifest.json",
        "projectVersion": ROOT / "ProjectSettings" / "ProjectVersion.txt",
        "unityPipeline": UNITY_PIPELINE_PATH,
        "buildScript": path(job["buildScript"]),
        "licenseEvidence": path(job["licenseEvidence"]),
        "targetAvatarAsset": path(job["targetAvatarAssetPath"]),
    }
    if job.get("targetSourcePath"):
        files["targetSource"] = path(job["targetSourcePath"])
    upm_lock = ROOT / "Packages" / "packages-lock.json"
    if upm_lock.is_file():
        files["upmLock"] = upm_lock
    missing = [name for name, file in files.items() if not file.is_file()]
    if missing:
        raise FileNotFoundError(f"input missing: {', '.join(missing)}")
    return {name: digest(file) for name, file in files.items()}


def candidate_files(job: dict[str, Any], policy: dict[str, Any]) -> list[Path]:
    private = [path(value) for value in job["privateSourceRoots"]]
    allowed = {value.lower() for value in policy["allowedDeliveryExtensions"]}
    target = {path(job["targetAvatarAssetPath"])}
    if job.get("targetSourcePath"):
        target.add(path(job["targetSourcePath"]))
    result = []
    for value in job["deliveryAssets"]:
        file = path(value)
        if not rel(file).startswith("Assets/"):
            raise ValueError(f"delivery asset outside Assets/: {value}")
        if file in target or any(inside(file, root) for root in private):
            raise ValueError(f"private avatar source selected for delivery: {value}")
        if file.suffix.lower() not in allowed:
            raise ValueError(f"delivery extension not allowed: {value}")
        if not file.is_file():
            raise FileNotFoundError(f"delivery asset missing: {value}")
        result.append(file)
    return result


def manifest(files: list[Path], base: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": str(file.relative_to(base)).replace("\\", "/"),
            "bytes": file.stat().st_size,
            "sha256": digest(file),
        }
        for file in sorted(files)
    ]


def verify_candidate(
    job_path: Path,
    job: dict[str, Any],
    candidate: Path,
    data: dict[str, Any],
) -> list[str]:
    errors = []
    if data.get("schemaVersion") != 2 or data.get("kind") != "image2outfit-candidate":
        errors.append("candidate manifest invalid")
    if data.get("jobId") != job["id"] or data.get("adapterId") != job["adapterId"]:
        errors.append("candidate identity mismatch")
    current_commit = os.environ.get("GITHUB_SHA")
    if current_commit and data.get("sourceCommit") != current_commit:
        errors.append("candidate source commit differs from current commit")
    current_inputs = inputs(job_path, job)
    for name, expected in data.get("inputHashes", {}).items():
        if current_inputs.get(name) != expected:
            errors.append(f"candidate input changed: {name}")
    expected_paths = set()
    for item in data.get("files", []):
        file = (candidate / item.get("path", "")).resolve()
        if not inside(file, candidate):
            errors.append("candidate manifest path escapes directory")
            continue
        expected_paths.add(file)
        if (
            not file.is_file()
            or digest(file) != item.get("sha256")
            or file.stat().st_size != item.get("bytes")
        ):
            errors.append(f"candidate file changed: {item.get('path')}")
    actual = {file.resolve() for file in candidate.rglob("*") if file.is_file()}
    actual.discard((candidate / "candidate-manifest.json").resolve())
    if actual != expected_paths:
        errors.append("candidate file set changed")
    return errors
