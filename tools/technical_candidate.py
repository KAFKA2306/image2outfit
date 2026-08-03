#!/usr/bin/env python3
"""Execute Blender and Unity checks and materialize a technical candidate."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import audit_toolchain
import blender_python_env
import pipeline as legacy
from candidate_manifest import (
    ROOT,
    candidate_files,
    digest,
    inputs,
    license_gate,
    manifest,
    now,
    path,
    preview_gate,
    read,
    rel,
    write,
)


def run_candidate(job_path: Path, job: dict[str, Any], policy: dict[str, Any]) -> int:
    artifact = path(job["artifactDir"])
    candidate = path(job["candidateDir"])
    release = path(job["releaseDir"])
    shutil.rmtree(artifact, ignore_errors=True)
    shutil.rmtree(candidate, ignore_errors=True)
    shutil.rmtree(release, ignore_errors=True)
    artifact.mkdir(parents=True)
    run_id = (
        os.environ.get("IMAGE2OUTFIT_RUN_ID")
        or os.environ.get("GITHUB_RUN_ID")
        or now()
    )
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
        (r"%ProgramFiles%\Blender Foundation\Blender 4.4\blender.exe",),
    )
    try:
        prepared = blender_python_env.prepare(blender, root=ROOT)
        stages["blenderPython"] = prepared.report
    except Exception as exc:
        stages["blenderPython"] = {"passed": False, "error": str(exc)}
        stages["blenderBuild"] = {"passed": False, "error": "not run"}
        stages["blenderStructure"] = {"passed": False, "error": "not run"}
        prepared = None

    if prepared is None:
        build_exit = None
    else:
        build_exit = legacy.run_command(
            [
                *prepared.command_prefix,
                "--background",
                "--python-exit-code",
                "1",
                "--python",
                str(path(job["buildScript"])),
                "--",
                "--job",
                str(job_path),
            ],
            artifact / "blender-build.log",
            prepared.environment,
        )
    stages["blenderBuild"] = {
        "passed": prepared is not None
        and build_exit == 0
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
                *prepared.command_prefix,
                "--background",
                str(path(job["blendPath"])),
                "--python-exit-code",
                "1",
                "--python",
                str(ROOT / "tools" / "pipeline.py"),
                "--",
                "--mode",
                "blender-gate",
                "--job",
                str(temporary_job_path),
            ],
            artifact / "blender-gate.log",
            prepared.environment,
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
            "modularAvatarValidated": unity_report.get(
                "modularAvatarValidated"
            )
            is True,
        }
    else:
        stages["unityStatic"] = {"passed": False, "error": "not run"}

    if stages["unityStatic"]["passed"]:
        resolved_toolchain = audit_toolchain.audit(ROOT, require_unity_lock=True)
        write(artifact / "toolchain-resolved.json", resolved_toolchain)
        stages["toolchainResolved"] = {
            "passed": resolved_toolchain.get("passed") is True,
            "unityPackageLockPresent": resolved_toolchain.get(
                "unityPackageLockPresent"
            )
            is True,
            "errors": resolved_toolchain.get("errors", []),
        }
    else:
        stages["toolchainResolved"] = {"passed": False, "error": "not run"}

    preview_passed, previews = (
        preview_gate(job, policy) if stages["unityStatic"]["passed"] else (False, {})
    )
    stages["previewSet"] = {"passed": preview_passed, "views": previews}
    technical_pass = all(value.get("passed") is True for value in stages.values())

    candidate_manifest = candidate / "candidate-manifest.json"
    if technical_pass:
        copied = []
        for source in candidate_files(job, policy):
            destination = (
                candidate
                / "UnityAssets"
                / source.relative_to(ROOT / "Assets")
            )
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
            "candidateManifest": (
                rel(candidate_manifest)
                if candidate_manifest.is_file()
                else None
            ),
            "candidateManifestSha256": digest(candidate_manifest)
            if candidate_manifest.is_file()
            else None,
            "note": (
                "Technical validity is not product approval. Visual, pose and "
                "VRChat runtime evidence are mandatory."
            ),
        },
    )
    return 0 if technical_pass else 2
