#!/usr/bin/env python3
"""Execute technical Blender/Unity checks and materialize a candidate."""

from __future__ import annotations

import argparse
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import audit_toolchain
import blender_python_env
import candidate_manifest as candidate_contract

ROOT = candidate_contract.ROOT


def find_executable(
    env_name: str,
    names: tuple[str, ...],
    candidates: tuple[str, ...],
) -> str:
    configured = os.environ.get(env_name)
    if configured and Path(configured).is_file():
        return configured
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    for candidate in candidates:
        expanded = Path(os.path.expandvars(candidate))
        if expanded.is_file():
            return str(expanded)
    raise FileNotFoundError(f"{env_name} is not set and executable was not found")


def run_command(
    command: list[str],
    log_path: Path,
    environment: dict[str, str] | None = None,
) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        process = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
            text=True,
        )
    return process.returncode


def run_blender_structure_gate(job_path: Path) -> int:
    """Validate the current Blender scene without a legacy job adapter."""
    import bmesh  # type: ignore
    import bpy  # type: ignore

    job = candidate_contract.read(job_path)
    if job.get("schemaVersion") != 2:
        raise ValueError("Blender structure gate requires schemaVersion 2 job")
    artifact_value = job.get("artifactDir")
    if not isinstance(artifact_value, str) or not artifact_value:
        raise ValueError("job.artifactDir is required for Blender structure gate")
    artifact_dir = candidate_contract.path(artifact_value)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    warnings: list[str] = []
    metrics = {
        "meshObjects": 0,
        "vertices": 0,
        "triangles": 0,
        "materials": 0,
        "shapeKeys": 0,
        "maxBoneInfluences": 0,
        "nonFiniteValues": 0,
        "degenerateTriangles": 0,
        "nonManifoldEdges": 0,
        "unweightedVertices": 0,
        "weightSumErrors": 0,
    }

    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        metrics["meshObjects"] += 1
        mesh = obj.data
        metrics["vertices"] += len(mesh.vertices)
        metrics["materials"] += len(mesh.materials)
        metrics["shapeKeys"] += (
            max(0, len(mesh.shape_keys.key_blocks) - 1) if mesh.shape_keys else 0
        )
        mesh.calc_loop_triangles()
        metrics["triangles"] += len(mesh.loop_triangles)

        for vertex in mesh.vertices:
            if not all(math.isfinite(value) for value in vertex.co):
                metrics["nonFiniteValues"] += 1
            groups = [group for group in vertex.groups if group.weight > 1e-8]
            metrics["maxBoneInfluences"] = max(
                metrics["maxBoneInfluences"], len(groups)
            )
            if obj.vertex_groups:
                if not groups:
                    metrics["unweightedVertices"] += 1
                elif abs(sum(group.weight for group in groups) - 1.0) > 1e-4:
                    metrics["weightSumErrors"] += 1

        for uv_layer in mesh.uv_layers:
            for loop in uv_layer.data:
                if not all(math.isfinite(value) for value in loop.uv):
                    metrics["nonFiniteValues"] += 1

        for triangle in mesh.loop_triangles:
            a, b, c = (mesh.vertices[index].co for index in triangle.vertices)
            if (b - a).cross(c - a).length_squared <= 1e-20:
                metrics["degenerateTriangles"] += 1

        bm = bmesh.new()
        bm.from_mesh(mesh)
        metrics["nonManifoldEdges"] += sum(
            1 for edge in bm.edges if not edge.is_manifold
        )
        bm.free()

    if metrics["meshObjects"] == 0:
        errors.append("no mesh objects")
    if metrics["nonFiniteValues"]:
        errors.append("non-finite geometry or UV values")
    if metrics["degenerateTriangles"]:
        errors.append("degenerate triangles")
    if metrics["unweightedVertices"]:
        errors.append("unweighted vertices")
    if metrics["weightSumErrors"]:
        errors.append("vertex weight sums outside tolerance")
    if metrics["maxBoneInfluences"] > 4:
        errors.append("more than four bone influences")
    if metrics["nonManifoldEdges"]:
        warnings.append("non-manifold edges require visual review")

    candidate_contract.write(
        artifact_dir / "blender.json",
        {
            "passed": not errors,
            "errors": errors,
            "warnings": warnings,
            "metrics": metrics,
            "blenderVersion": bpy.app.version_string,
        },
    )
    return 0 if not errors else 2


def run_candidate(job_path: Path, job: dict[str, Any], policy: dict[str, Any]) -> int:
    artifact = candidate_contract.path(job["artifactDir"])
    candidate = candidate_contract.path(job["candidateDir"])
    release = candidate_contract.path(job["releaseDir"])
    shutil.rmtree(artifact, ignore_errors=True)
    shutil.rmtree(candidate, ignore_errors=True)
    shutil.rmtree(release, ignore_errors=True)
    artifact.mkdir(parents=True)
    run_id = (
        os.environ.get("IMAGE2OUTFIT_RUN_ID")
        or os.environ.get("GITHUB_RUN_ID")
        or candidate_contract.now()
    )
    stages: dict[str, Any] = {}

    toolchain = audit_toolchain.audit(ROOT)
    candidate_contract.write(artifact / "toolchain-source.json", toolchain)
    stages["toolchainSource"] = {
        "passed": toolchain.get("passed") is True,
        "errors": toolchain.get("errors", []),
        "warnings": toolchain.get("warnings", []),
    }

    passed, errors = candidate_contract.license_gate(job)
    stages["license"] = {"passed": passed, "errors": errors}

    blender = find_executable(
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
        build_exit = run_command(
            [
                *prepared.command_prefix,
                "--background",
                "--python-exit-code",
                "1",
                "--python",
                str(ROOT / "tools" / "render_evidence_bootstrap.py"),
                "--python",
                str(candidate_contract.path(job["buildScript"])),
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
        and candidate_contract.path(job["blendPath"]).is_file()
        and candidate_contract.path(job["fbxAssetPath"]).is_file(),
        "exitCode": build_exit,
    }

    if stages["blenderBuild"]["passed"]:
        gate_exit = run_command(
            [
                *prepared.command_prefix,
                "--background",
                str(candidate_contract.path(job["blendPath"])),
                "--python-exit-code",
                "1",
                "--python",
                str(Path(__file__).resolve()),
                "--",
                "--mode",
                "blender-structure",
                "--job",
                str(job_path),
            ],
            artifact / "blender-gate.log",
            prepared.environment,
        )
        blender_report = candidate_contract.read(artifact / "blender.json")
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
        unity = find_executable(
            "UNITY_EXE",
            ("Unity", "unity-editor", "unity"),
            (
                r"%ProgramFiles%\Unity\Hub\Editor\2022.3.22f1\Editor\Unity.exe",
                r"%ProgramFiles%\Unity Hub\Editor\2022.3.22f1\Editor\Unity.exe",
            ),
        )
        unity_exit = run_command(
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
        unity_report = candidate_contract.read(artifact / "unity.json")
        stages["unityStatic"] = {
            "passed": unity_exit == 0
            and unity_report.get("passed") is True
            and unity_report.get("targetValidated") is True
            and unity_report.get("toolchainValidated") is True
            and unity_report.get("modularAvatarValidated") is True,
            "exitCode": unity_exit,
            "toolchainValidated": unity_report.get("toolchainValidated") is True,
            "modularAvatarValidated": unity_report.get("modularAvatarValidated")
            is True,
        }
    else:
        stages["unityStatic"] = {"passed": False, "error": "not run"}

    if stages["unityStatic"]["passed"]:
        resolved_toolchain = audit_toolchain.audit(ROOT, require_unity_lock=True)
        candidate_contract.write(
            artifact / "toolchain-resolved.json", resolved_toolchain
        )
        stages["toolchainResolved"] = {
            "passed": resolved_toolchain.get("passed") is True,
            "unityPackageLockPresent": resolved_toolchain.get("unityPackageLockPresent")
            is True,
            "errors": resolved_toolchain.get("errors", []),
        }
    else:
        stages["toolchainResolved"] = {"passed": False, "error": "not run"}

    preview_passed, previews = (
        candidate_contract.preview_gate(job, policy)
        if stages["unityStatic"]["passed"]
        else (False, {})
    )
    stages["previewSet"] = {"passed": preview_passed, "views": previews}
    technical_pass = all(value.get("passed") is True for value in stages.values())

    candidate_manifest_path = candidate / "candidate-manifest.json"
    if technical_pass:
        copied = []
        for source in candidate_contract.candidate_files(job, policy):
            destination = (
                candidate / "UnityAssets" / source.relative_to(ROOT / "Assets")
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied.append(destination)
        for view, value in job["previewPaths"].items():
            source = candidate_contract.path(value)
            destination = candidate / "Preview" / f"{view}.png"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied.append(destination)
        candidate_contract.write(
            candidate_manifest_path,
            {
                "schemaVersion": 2,
                "kind": "image2outfit-candidate",
                "jobId": job["id"],
                "productName": job["productName"],
                "adapterId": job["adapterId"],
                "runId": str(run_id),
                "createdAt": candidate_contract.now(),
                "sourceCommit": os.environ.get("GITHUB_SHA", "local"),
                "inputHashes": candidate_contract.inputs(job_path, job),
                "files": candidate_contract.manifest(copied, candidate),
                "releaseDecision": "REVIEW_REQUIRED",
            },
        )

    decision = "REVIEW_REQUIRED" if technical_pass else "NO-GO"
    candidate_contract.write(
        artifact / "audit.json",
        {
            "schemaVersion": 2,
            "phase": "candidate",
            "jobId": job["id"],
            "adapterId": job["adapterId"],
            "checkedAt": candidate_contract.now(),
            "decision": decision,
            "releaseEligible": False,
            "stages": stages,
            "candidateManifest": (
                candidate_contract.rel(candidate_manifest_path)
                if candidate_manifest_path.is_file()
                else None
            ),
            "candidateManifestSha256": (
                candidate_contract.digest(candidate_manifest_path)
                if candidate_manifest_path.is_file()
                else None
            ),
            "note": (
                "Technical validity is not product approval. Visual, pose and "
                "VRChat runtime evidence are mandatory."
            ),
        },
    )
    return 0 if technical_pass else 2


def parse_args() -> argparse.Namespace:
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("blender-structure",), required=True)
    parser.add_argument("--job", required=True)
    return parser.parse_args(args)


def main() -> int:
    options = parse_args()
    try:
        return run_blender_structure_gate(Path(options.job).resolve())
    except Exception as exc:
        print(f"image2outfit technical candidate: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
