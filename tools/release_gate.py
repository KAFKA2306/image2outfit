#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import audit_toolchain
import pipeline as legacy

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "release-policy.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
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


def load(job_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    policy = read(POLICY_PATH)
    job = read(job_path)
    if policy.get("schemaVersion") != 1:
        raise ValueError("release-policy.json must use schemaVersion 1")
    if job.get("schemaVersion") != 2:
        raise ValueError("legacy jobs are disabled; schemaVersion must be 2")
    required = (
        "id", "productName", "adapterId", "buildScript", "blendPath", "fbxAssetPath",
        "prefabAssetPath", "integratedPrefabAssetPath", "targetAvatarAssetPath",
        "artifactDir", "candidateDir", "releaseDir", "licenseEvidence",
        "privateSourceRoots", "deliveryAssets", "previewPaths", "humanEvidence",
    )
    missing = [key for key in required if key not in job or job[key] in (None, "")]
    if missing:
        raise ValueError(f"job v2 missing: {', '.join(missing)}")
    if not rel(path(job["artifactDir"])).startswith("Artifacts/"):
        raise ValueError("artifactDir must be under Artifacts/")
    if not rel(path(job["candidateDir"])).startswith("Candidates/"):
        raise ValueError("candidateDir must be under Candidates/")
    if not rel(path(job["releaseDir"])).startswith("Release/"):
        raise ValueError("releaseDir must be under Release/")
    views = set(policy["minimumPreview"]["requiredViews"])
    if views - set(job["previewPaths"]):
        raise ValueError("previewPaths does not contain every required view")
    kinds = set(policy["requiredHumanEvidenceKinds"])
    if kinds - set(job["humanEvidence"]):
        raise ValueError("humanEvidence does not contain every required kind")
    license_path = path(job["licenseEvidence"])
    outputs = [path(job[key]) for key in ("artifactDir", "candidateDir", "releaseDir")]
    if any(inside(license_path, output) for output in outputs):
        raise ValueError("licenseEvidence must be outside generated output directories")
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


def preview_gate(job: dict[str, Any], policy: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
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
        "toolchainLock": ROOT / "config" / "toolchain-lock.json",
        "vpmManifest": ROOT / "Packages" / "vpm-manifest.json",
        "upmManifest": ROOT / "Packages" / "manifest.json",
        "projectVersion": ROOT / "ProjectSettings" / "ProjectVersion.txt",
        "unityPipeline": ROOT / "Assets" / "Editor" / "Image2OutfitPipeline.cs",
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


def run_candidate(job_path: Path, job: dict[str, Any], policy: dict[str, Any]) -> int:
    artifact = path(job["artifactDir"])
    candidate = path(job["candidateDir"])
    release = path(job["releaseDir"])
    shutil.rmtree(artifact, ignore_errors=True)
    shutil.rmtree(candidate, ignore_errors=True)
    shutil.rmtree(release, ignore_errors=True)
    artifact.mkdir(parents=True)
    run_id = os.environ.get("IMAGE2OUTFIT_RUN_ID") or os.environ.get("GITHUB_RUN_ID") or now()
    stages: dict[str, Any] = {}

    toolchain = audit_toolchain.audit(ROOT)
    write(artifact / "toolchain-source.json", toolchain)
    stages["toolchainSource"] = {
        "passed": toolchain.get("passed") is True,
        "errors": toolchain.get("errors", []),
        "warnings": toolchain.get("warnings", []),
    }

    passed, errors = license_gate(job)
    stages["license"] = {"passed": passed, "errors": errors}

    blender = legacy.find_executable(
        "BLENDER_EXE",
        ("blender",),
        (
            r"%ProgramFiles%\Blender Foundation\Blender 4.4\blender.exe",
        ),
    )
    build_exit = legacy.run_command(
        [
            blender,
            "--background",
            "--python",
            str(path(job["buildScript"])),
            "--",
            "--job",
            str(job_path),
        ],
        artifact / "blender-build.log",
    )
    stages["blenderBuild"] = {
        "passed": build_exit == 0
        and path(job["blendPath"]).is_file()
        and path(job["fbxAssetPath"]).is_file(),
        "exitCode": build_exit,
    }

    temporary_job = dict(job)
    temporary_job.update(
        deliveryDir=job["candidateDir"],
        requiredEvidence=[job["licenseEvidence"]],
    )
    temporary_job_path = artifact / "legacy-blender-gate-job.json"
    write(temporary_job_path, temporary_job)
    if stages["blenderBuild"]["passed"]:
        gate_exit = legacy.run_command(
            [
                blender,
                "--background",
                str(path(job["blendPath"])),
                "--python",
                str(ROOT / "tools" / "pipeline.py"),
                "--",
                "--mode",
                "blender-gate",
                "--job",
                str(temporary_job_path),
            ],
            artifact / "blender-gate.log",
        )
        blender_report = read(artifact / "blender.json")
        expected_blender = toolchain.get("blender", {}).get("expected")
        stages["blenderStructure"] = {
            "passed": gate_exit == 0
            and blender_report.get("passed") is True
            and blender_report.get("blenderVersion") == expected_blender,
            "exitCode": gate_exit,
            "expectedVersion": expected_blender,
            "actualVersion": blender_report.get("blenderVersion"),
        }
    else:
        stages["blenderStructure"] = {"passed": False, "error": "not run"}

    if stages["blenderStructure"]["passed"]:
        unity = legacy.find_executable(
            "UNITY_EXE",
            ("Unity", "unity-editor", "unity"),
            (
                r"%ProgramFiles%\Unity\Hub\Editor\2022.3.22f1\Editor\Unity.exe",
                r"%ProgramFiles%\Unity Hub\Editor\2022.3.22f1\Editor\Unity.exe",
            ),
        )
        unity_exit = legacy.run_command(
            [
                unity,
                "-batchmode",
                "-projectPath",
                str(ROOT),
                "-executeMethod",
                "Image2Outfit.Editor.Pipeline.RunStatic",
                "-image2outfitJob",
                str(job_path),
                "-logFile",
                str(artifact / "unity.log"),
            ],
            artifact / "unity-process.log",
        )
        unity_report = read(artifact / "unity.json")
        stages["unityStatic"] = {
            "passed": unity_exit == 0
            and unity_report.get("passed") is True
            and unity_report.get("targetValidated") is True
            and unity_report.get("toolchainValidated") is True
            and unity_report.get("modularAvatarValidated") is True,
            "exitCode": unity_exit,
            "toolchainValidated": unity_report.get("toolchainValidated") is True,
            "modularAvatarValidated": unity_report.get("modularAvatarValidated") is True,
        }
    else:
        stages["unityStatic"] = {"passed": False, "error": "not run"}

    if stages["unityStatic"]["passed"]:
        resolved_toolchain = audit_toolchain.audit(ROOT, require_unity_lock=True)
        write(artifact / "toolchain-resolved.json", resolved_toolchain)
        stages["toolchainResolved"] = {
            "passed": resolved_toolchain.get("passed") is True,
            "unityPackageLockPresent": resolved_toolchain.get("unityPackageLockPresent") is True,
            "errors": resolved_toolchain.get("errors", []),
        }
    else:
        stages["toolchainResolved"] = {"passed": False, "error": "not run"}

    preview_passed, previews = (
        preview_gate(job, policy)
        if stages["unityStatic"]["passed"]
        else (False, {})
    )
    stages["previewSet"] = {"passed": preview_passed, "views": previews}
    technical_pass = all(value.get("passed") is True for value in stages.values())

    candidate_manifest = candidate / "candidate-manifest.json"
    if technical_pass:
        copied = []
        for source in candidate_files(job, policy):
            destination = candidate / "UnityAssets" / source.relative_to(ROOT / "Assets")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied.append(destination)
        for view, value in job["previewPaths"].items():
            source = path(value)
            destination = candidate / "Preview" / f"{view}.png"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied.append(destination)
        write(
            candidate_manifest,
            {
                "schemaVersion": 2,
                "kind": "image2outfit-candidate",
                "jobId": job["id"],
                "productName": job["productName"],
                "adapterId": job["adapterId"],
                "runId": str(run_id),
                "createdAt": now(),
                "sourceCommit": os.environ.get("GITHUB_SHA", "local"),
                "inputHashes": inputs(job_path, job),
                "files": manifest(copied, candidate),
                "releaseDecision": "REVIEW_REQUIRED",
            },
        )

    decision = "REVIEW_REQUIRED" if technical_pass else "NO-GO"
    write(
        artifact / "audit.json",
        {
            "schemaVersion": 2,
            "phase": "candidate",
            "jobId": job["id"],
            "adapterId": job["adapterId"],
            "checkedAt": now(),
            "decision": decision,
            "releaseEligible": False,
            "stages": stages,
            "candidateManifest": rel(candidate_manifest)
            if candidate_manifest.is_file()
            else None,
            "candidateManifestSha256": digest(candidate_manifest)
            if candidate_manifest.is_file()
            else None,
            "note": "Technical validity is not product approval. Visual, pose and VRChat runtime evidence are mandatory.",
        },
    )
    return 0 if technical_pass else 2


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


def evidence_gate(
    job: dict[str, Any],
    policy: dict[str, Any],
    candidate_hash: str,
) -> tuple[dict[str, Any], list[str]]:
    result: dict[str, Any] = {}
    errors = []
    for kind in policy["requiredHumanEvidenceKinds"]:
        evidence = read(path(job["humanEvidence"][kind]))
        item = []
        for name, passed in {
            "schemaVersion": evidence.get("schemaVersion") == 2,
            "kind": evidence.get("kind") == kind,
            "jobId": evidence.get("jobId") == job["id"],
            "adapterId": evidence.get("adapterId") == job["adapterId"],
            "candidateManifestSha256": evidence.get("candidateManifestSha256")
            == candidate_hash,
            "status": evidence.get("status") == "PASS",
            "checkedAt": bool(evidence.get("checkedAt")),
            "reviewer": bool(evidence.get("reviewer")),
        }.items():
            if not passed:
                item.append(name)
        if kind == "visual-review":
            scores = evidence.get("scores", {})
            for score in ("silhouette", "fit", "material", "presentation"):
                if (
                    not isinstance(scores.get(score), (int, float))
                    or scores[score] < policy["minimumVisualScore"]
                ):
                    item.append(score)
            if evidence.get("criticalDefects") != 0:
                item.append("criticalDefects")
        elif kind == "pose-penetration-review":
            poses = evidence.get("poses", {})
            for pose_name in policy["requiredPoses"]:
                if poses.get(pose_name) != "PASS":
                    item.append(pose_name)
            if evidence.get("criticalPenetrations") != 0:
                item.append("criticalPenetrations")
        elif kind == "vrchat-runtime-review":
            if evidence.get("vrchatBuildAndTest") != "PASS":
                item.append("vrchatBuildAndTest")
            if evidence.get("testedInVRChat") is not True:
                item.append("testedInVRChat")
        result[kind] = {"passed": not item, "failedFields": item}
        errors.extend(f"{kind}: {name}" for name in item)
    return result, errors


def run_release(job_path: Path, job: dict[str, Any], policy: dict[str, Any]) -> int:
    artifact, candidate, release = (
        path(job[key]) for key in ("artifactDir", "candidateDir", "releaseDir")
    )
    candidate_manifest = candidate / "candidate-manifest.json"
    data = read(candidate_manifest)
    errors = []
    if job["adapterId"] in policy["blockedReleaseAdapterIds"]:
        errors.append(f"adapter blocked from release: {job['adapterId']}")
    errors.extend(verify_candidate(job_path, job, candidate, data))
    candidate_hash = digest(candidate_manifest) if candidate_manifest.is_file() else ""
    evidence, evidence_errors = evidence_gate(job, policy, candidate_hash)
    errors.extend(evidence_errors)
    shutil.rmtree(release, ignore_errors=True)
    if errors:
        write(
            artifact / "audit.json",
            {
                "schemaVersion": 2,
                "phase": "release",
                "jobId": job["id"],
                "adapterId": job["adapterId"],
                "checkedAt": now(),
                "decision": "NO-GO",
                "releaseEligible": False,
                "errors": errors,
                "evidence": evidence,
                "candidateManifestSha256": candidate_hash or None,
            },
        )
        return 2

    package = release / "Package"
    shutil.copytree(candidate, package)
    release.mkdir(parents=True, exist_ok=True)
    release_manifest = release / "release-manifest.json"
    files = [file for file in package.rglob("*") if file.is_file()]
    write(
        release_manifest,
        {
            "schemaVersion": 2,
            "kind": "image2outfit-release",
            "jobId": job["id"],
            "productName": job["productName"],
            "adapterId": job["adapterId"],
            "releasedAt": now(),
            "sourceCommit": data.get("sourceCommit"),
            "candidateManifestSha256": candidate_hash,
            "files": manifest(files, release),
            "evidence": evidence,
            "decision": "GO",
        },
    )
    archive = release / f"{job['id']}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for file in sorted(release.rglob("*")):
            if file.is_file() and file != archive:
                output.write(file, file.relative_to(release))
    write(
        artifact / "audit.json",
        {
            "schemaVersion": 2,
            "phase": "release",
            "jobId": job["id"],
            "adapterId": job["adapterId"],
            "checkedAt": now(),
            "decision": "GO",
            "releaseEligible": True,
            "candidateManifestSha256": candidate_hash,
            "releaseManifest": rel(release_manifest),
            "releaseManifestSha256": digest(release_manifest),
            "zip": {
                "path": rel(archive),
                "sha256": digest(archive),
                "bytes": archive.stat().st_size,
            },
        },
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("candidate", "release"), required=True)
    parser.add_argument("--job", required=True)
    options = parser.parse_args()
    try:
        job_path = Path(options.job).resolve()
        job, policy = load(job_path)
        if options.mode == "release":
            return run_release(job_path, job, policy)
        return run_candidate(job_path, job, policy)
    except Exception as exc:
        print(f"image2outfit v2: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
