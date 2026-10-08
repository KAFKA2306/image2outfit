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

# Blender executes this file as a standalone script and does not guarantee
# that its sibling tools directory is on sys.path.
TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import audit_toolchain
import blender_python_env
import candidate_manifest as candidate_contract
from contract_io import required_pose_paths

ROOT = candidate_contract.ROOT


def find_executable(
    env_name: str,
    names: tuple[str, ...],
    candidates: tuple[str, ...],
) -> str:
    configured = os.environ.get(env_name)
    if configured and Path(configured).is_file():
        return configured
    for candidate in candidates:
        expanded = Path(os.path.expandvars(candidate))
        if expanded.is_file():
            return str(expanded)
    for name in names:
        found = shutil.which(name)
        if found:
            return found
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


def run_hosted_pose_render(
    job_path: Path,
    job: dict[str, Any],
    policy: dict[str, Any],
    prepared: blender_python_env.PreparedEnvironment,
    artifact: Path,
) -> dict[str, Any]:
    pose_script = job.get("hostedPoseScript")
    if not pose_script:
        return {"passed": True, "status": "NOT_REQUESTED"}
    if not isinstance(pose_script, str):
        return {
            "passed": False,
            "status": "INVALID",
            "error": "hostedPoseScript must be a string",
        }

    script_path = candidate_contract.path(pose_script)
    blend_path = candidate_contract.path(job["blendPath"])
    if not script_path.is_file():
        return {
            "passed": False,
            "status": "MISSING_SCRIPT",
            "error": f"hosted pose script missing: {pose_script}",
        }

    exit_code = run_command(
        [
            *prepared.command_prefix,
            "--background",
            str(blend_path),
            "--python-exit-code",
            "1",
            "--python",
            str(script_path),
            "--",
            "--job",
            str(job_path),
        ],
        artifact / "blender-poses.log",
        prepared.environment,
    )
    pose_paths = required_pose_paths(job, policy)
    missing = [
        value
        for value in pose_paths.values()
        if not candidate_contract.path(value).is_file()
    ]
    return {
        "passed": exit_code == 0 and not missing,
        "status": "PASS" if exit_code == 0 and not missing else "FAIL",
        "script": pose_script,
        "exitCode": exit_code,
        "requiredPoses": list(pose_paths),
        "missingPoses": missing,
    }


def record_unity_ready_product_state(
    job: dict[str, Any],
    report: dict[str, Any],
    artifact: Path,
) -> Path:
    if report.get("unityReadyStatus") != "VERIFIED":
        raise ValueError("cannot record Unity-ready state from an unverified report")

    product_root = candidate_contract.path(job["productRoot"])
    evidence = product_root / "Evidence" / "Unity" / "unity-ready.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(artifact / "unity-ready.json", evidence)

    manifest_path = candidate_contract.path(job["productManifestPath"])
    manifest = candidate_contract.read(manifest_path)
    if not manifest_path.is_file() or not manifest:
        raise FileNotFoundError(
            "ProductManifest.json is missing after Unity-ready validation"
        )

    technical = manifest.setdefault("technicalGates", {})
    if not isinstance(technical, dict):
        raise ValueError("ProductManifest technicalGates must be an object")
    technical.update(
        {
            "unityImport": "PASS",
            "prefabSerialized": "PASS",
            "prefabReload": "PASS",
            "modularAvatar": "PASS",
            "ndmf": "PASS",
        }
    )
    release_readiness = manifest.setdefault("releaseReadiness", {})
    if not isinstance(release_readiness, dict):
        raise ValueError("ProductManifest releaseReadiness must be an object")
    declared_roles = job["unityReady"].get("materialRoles")
    if isinstance(declared_roles, list):
        material_roles = {}
        for item in declared_roles:
            if not isinstance(item, dict):
                raise ValueError("unity-ready materialRoles contains a non-object")
            material = item.get("material")
            role = item.get("role")
            if not isinstance(material, str) or not material:
                raise ValueError(
                    "unity-ready materialRoles contains an invalid material"
                )
            if not isinstance(role, str) or not role:
                raise ValueError("unity-ready materialRoles contains an invalid role")
            if material in material_roles:
                raise ValueError(
                    f"unity-ready materialRoles contains duplicate material: {material}"
                )
            material_roles[material] = role
    elif isinstance(declared_roles, dict):
        material_roles = dict(declared_roles)
    else:
        raise ValueError("unity-ready materialRoles must be a list or object")

    release_readiness["unityReady"] = {
        "status": "VERIFIED",
        "multiMaterialSetup": "VERIFIED",
        "modularAvatarSetup": "VERIFIED",
        "ndmfBake": "VERIFIED",
        "reimport": "VERIFIED",
        "targetAvatarAssetPath": job["targetAvatarAssetPath"],
        "materialRoles": material_roles,
        "evidencePath": candidate_contract.rel(evidence),
        "evidenceSha256": candidate_contract.digest(evidence),
    }
    candidate_contract.write(manifest_path, manifest)
    return evidence


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
        (
            str(ROOT / ".image2outfit" / "blender-4.4.3" / "blender.exe"),
            str(ROOT / ".image2outfit" / "blender" / "blender.exe"),
            r"%ProgramFiles%\Blender Foundation\Blender 4.4\blender.exe",
        ),
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
        stages["hostedPose"] = run_hosted_pose_render(
            job_path,
            job,
            policy,
            prepared,
            artifact,
        )
    else:
        stages["hostedPose"] = {"passed": False, "error": "not run"}

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

    unity_ready_report: dict[str, Any] = {}
    if stages["unityStatic"]["passed"] and isinstance(job.get("unityReady"), dict):
        immutable_before = {
            "fbx": candidate_contract.digest(
                candidate_contract.path(job["fbxAssetPath"])
            ),
            "targetAvatar": candidate_contract.digest(
                candidate_contract.path(job["targetAvatarAssetPath"])
            ),
        }
        material_exit = run_command(
            [
                unity,
                "-batchmode",
                "-projectPath",
                str(ROOT),
                "-executeMethod",
                "GenWorks.Editor.GenWorksMaterialExtractor.RunFromCommandLine",
                "-image2outfitJob",
                str(job_path),
                "-image2outfitArtifactDir",
                str(artifact),
                "-logFile",
                str(artifact / "unity-materials.log"),
            ],
            artifact / "unity-materials-process.log",
        )
        material_report = candidate_contract.read(artifact / "materials.json")
        minimum_materials = int(job["unityReady"].get("minimumDistinctMaterials", 1))
        material_assets = material_report.get("materialAssets", [])
        stages["unityMaterials"] = {
            "passed": (
                material_exit == 0
                and material_report.get("passed") is True
                and isinstance(material_assets, list)
                and len(material_assets) >= minimum_materials
            ),
            "exitCode": material_exit,
            "materialAssets": material_assets
            if isinstance(material_assets, list)
            else [],
            "errors": material_report.get("errors", []),
        }

        if stages["unityMaterials"]["passed"]:
            ready_exit = run_command(
                [
                    unity,
                    "-batchmode",
                    "-projectPath",
                    str(ROOT),
                    "-executeMethod",
                    "Image2Outfit.Editor.Pipeline.RunUnityReady",
                    "-image2outfitJob",
                    str(job_path),
                    "-logFile",
                    str(artifact / "unity-ready.log"),
                ],
                artifact / "unity-ready-process.log",
            )
            unity_ready_report = candidate_contract.read(artifact / "unity-ready.json")
            stages["unityReady"] = {
                "passed": (
                    ready_exit == 0
                    and unity_ready_report.get("passed") is True
                    and unity_ready_report.get("unityReadyStatus") == "VERIFIED"
                    and unity_ready_report.get("multiMaterialValidated") is True
                    and unity_ready_report.get("modularAvatarValidated") is True
                    and unity_ready_report.get("reimportValidated") is True
                ),
                "exitCode": ready_exit,
                "status": unity_ready_report.get("unityReadyStatus"),
                "multiMaterialValidated": unity_ready_report.get(
                    "multiMaterialValidated"
                )
                is True,
                "modularAvatarValidated": unity_ready_report.get(
                    "modularAvatarValidated"
                )
                is True,
                "reimportValidated": unity_ready_report.get("reimportValidated")
                is True,
                "metrics": unity_ready_report.get("metrics", {}),
                "errors": unity_ready_report.get("errors", []),
            }
        else:
            stages["unityReady"] = {"passed": False, "error": "material setup failed"}

        immutable_after = {
            "fbx": candidate_contract.digest(
                candidate_contract.path(job["fbxAssetPath"])
            ),
            "targetAvatar": candidate_contract.digest(
                candidate_contract.path(job["targetAvatarAssetPath"])
            ),
        }
        stages["unitySourceImmutability"] = {
            "passed": immutable_before == immutable_after,
            "before": immutable_before,
            "after": immutable_after,
        }
        if (
            stages["unityReady"]["passed"]
            and stages["unitySourceImmutability"]["passed"]
        ):
            try:
                evidence_path = record_unity_ready_product_state(
                    job, unity_ready_report, artifact
                )
                stages["unityReadyProductState"] = {
                    "passed": True,
                    "evidencePath": candidate_contract.rel(evidence_path),
                    "evidenceSha256": candidate_contract.digest(evidence_path),
                }
            except (OSError, ValueError, KeyError) as exc:
                stages["unityReadyProductState"] = {
                    "passed": False,
                    "error": str(exc),
                }
        else:
            stages["unityReadyProductState"] = {
                "passed": False,
                "error": "Unity-ready verification did not pass",
            }

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
        if isinstance(job.get("unityReady"), dict):
            for report_name in ("materials.json", "unity-ready.json"):
                source = artifact / report_name
                if not source.is_file():
                    raise FileNotFoundError(
                        f"Unity-ready evidence missing after successful gate: {report_name}"
                    )
                destination = candidate / "Evidence" / report_name
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
                "unityReady": (
                    {
                        "status": unity_ready_report.get("unityReadyStatus"),
                        "multiMaterialSetup": (
                            "VERIFIED"
                            if unity_ready_report.get("multiMaterialValidated") is True
                            else "UNVERIFIED"
                        ),
                        "modularAvatarSetup": (
                            "VERIFIED"
                            if unity_ready_report.get("modularAvatarValidated") is True
                            else "UNVERIFIED"
                        ),
                        "ndmfBake": (
                            "VERIFIED"
                            if unity_ready_report.get("modularAvatarValidated") is True
                            else "UNVERIFIED"
                        ),
                        "reimport": (
                            "VERIFIED"
                            if unity_ready_report.get("reimportValidated") is True
                            else "UNVERIFIED"
                        ),
                        "targetAvatarAssetPath": job["targetAvatarAssetPath"],
                        "evidencePath": (
                            candidate_contract.rel(
                                candidate_contract.path(job["productRoot"])
                                / "Evidence"
                                / "Unity"
                                / "unity-ready.json"
                            )
                        ),
                        "metrics": unity_ready_report.get("metrics", {}),
                    }
                    if isinstance(job.get("unityReady"), dict)
                    else {"status": "NOT_REQUESTED"}
                ),
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
