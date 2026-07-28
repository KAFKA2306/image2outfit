#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load_job(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = (
        "id",
        "productName",
        "buildScript",
        "blendPath",
        "fbxAssetPath",
        "prefabAssetPath",
        "targetAvatarAssetPath",
        "artifactDir",
        "deliveryDir",
        "licenseEvidence",
        "requiredEvidence",
    )
    missing = [key for key in required if key not in data or data[key] in (None, "")]
    if missing:
        raise ValueError(f"job.json missing: {', '.join(missing)}")
    if not isinstance(data["requiredEvidence"], list) or not data["requiredEvidence"]:
        raise ValueError("requiredEvidence must contain the customer-readiness evidence")
    return data


def repo_path(value: str) -> Path:
    path = (ROOT / value).resolve()
    if ROOT not in path.parents and path != ROOT:
        raise ValueError(f"path escapes repository: {value}")
    return path


def find_executable(env_name: str, names: tuple[str, ...], candidates: tuple[str, ...]) -> str:
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


def run_command(command: list[str], log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        process = subprocess.run(
            command,
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
            text=True,
        )
    return process.returncode


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_audit(
    job: dict[str, Any],
    delivery_dir: Path,
    stages: dict[str, Any],
    blender_report: dict[str, Any],
    unity_report: dict[str, Any],
    missing_evidence: list[str],
    delivery_files: list[Path],
) -> int:
    passed = (
        all(stage.get("passed") for stage in stages.values())
        and bool(blender_report.get("passed"))
        and bool(unity_report.get("passed"))
        and bool(unity_report.get("targetValidated"))
        and not missing_evidence
        and bool(delivery_files)
    )
    audit = {
        "jobId": job.get("id"),
        "productName": job.get("productName"),
        "decision": "GO" if passed else "NO-GO",
        "stages": stages,
        "blender": blender_report,
        "unity": unity_report,
        "missingEvidence": missing_evidence,
        "deliverables": [
            {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in delivery_files
            if path.is_file()
        ],
    }
    delivery_dir.mkdir(parents=True, exist_ok=True)
    (delivery_dir / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0 if passed else 2


def validate_license(path: Path) -> tuple[bool, str]:
    evidence = read_json(path)
    passed = (
        bool(evidence.get("sourceUrl"))
        and bool(evidence.get("checkedAt"))
        and evidence.get("commercialOutfitAllowed") is True
        and evidence.get("avatarFilesRedistributed") is False
    )
    return passed, "" if passed else "license evidence is missing or does not permit delivery"


def validate_required_evidence(path: Path) -> bool:
    evidence = read_json(path)
    return evidence.get("status") == "PASS" and bool(evidence.get("checkedAt"))


def copy_generated_assets(fbx_path: Path, prefab_path: Path, delivery_dir: Path) -> list[Path]:
    if fbx_path.parent != prefab_path.parent:
        raise ValueError("fbxAssetPath and prefabAssetPath must share one generated asset folder")
    source_root = fbx_path.parent
    destination_root = delivery_dir / "UnityAssets"
    if destination_root.exists():
        shutil.rmtree(destination_root)
    shutil.copytree(source_root, destination_root)
    return sorted(path for path in destination_root.rglob("*") if path.is_file())


def normal_mode(job_path: Path) -> int:
    job = load_job(job_path)
    artifact_dir = repo_path(job["artifactDir"])
    delivery_dir = repo_path(job["deliveryDir"])
    build_script = repo_path(job["buildScript"])
    blend_path = repo_path(job["blendPath"])
    fbx_path = repo_path(job["fbxAssetPath"])
    prefab_path = repo_path(job["prefabAssetPath"])
    license_path = repo_path(job["licenseEvidence"])
    required_evidence = [repo_path(value) for value in job["requiredEvidence"]]

    artifact_dir.mkdir(parents=True, exist_ok=True)
    delivery_dir.mkdir(parents=True, exist_ok=True)

    stages: dict[str, Any] = {
        "license": {"passed": False, "error": ""},
        "blenderBuild": {"passed": False, "exitCode": None},
        "blenderGate": {"passed": False, "exitCode": None},
        "unityGate": {"passed": False, "exitCode": None},
        "delivery": {"passed": False, "error": ""},
    }

    license_passed, license_error = validate_license(license_path)
    stages["license"] = {"passed": license_passed, "error": license_error}

    blender_report: dict[str, Any] = {}
    unity_report: dict[str, Any] = {}
    delivery_files: list[Path] = []

    try:
        blender = find_executable(
            "BLENDER_EXE",
            ("blender",),
            (
                r"%ProgramFiles%\Blender Foundation\Blender 4.5\blender.exe",
                r"%ProgramFiles%\Blender Foundation\Blender 4.4\blender.exe",
                r"%ProgramFiles%\Blender Foundation\Blender 4.3\blender.exe",
                r"%ProgramFiles%\Blender Foundation\Blender 4.2\blender.exe",
            ),
        )
        build_exit = run_command(
            [blender, "--background", "--python", str(build_script), "--", "--job", str(job_path)],
            artifact_dir / "blender-build.log",
        )
        stages["blenderBuild"]["exitCode"] = build_exit
        stages["blenderBuild"]["passed"] = (
            build_exit == 0 and blend_path.is_file() and fbx_path.is_file()
        )

        if stages["blenderBuild"]["passed"]:
            gate_exit = run_command(
                [
                    blender,
                    "--background",
                    str(blend_path),
                    "--python",
                    str(Path(__file__).resolve()),
                    "--",
                    "--mode",
                    "blender-gate",
                    "--job",
                    str(job_path),
                ],
                artifact_dir / "blender-gate.log",
            )
            stages["blenderGate"]["exitCode"] = gate_exit
            blender_report = read_json(artifact_dir / "blender.json")
            stages["blenderGate"]["passed"] = gate_exit == 0 and bool(
                blender_report.get("passed")
            )
    except Exception as exc:
        stages["blenderBuild"]["error"] = str(exc)

    if stages["blenderGate"]["passed"]:
        try:
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
                    "Image2Outfit.Editor.Pipeline.Run",
                    "-image2outfitJob",
                    str(job_path),
                    "-logFile",
                    str(artifact_dir / "unity.log"),
                ],
                artifact_dir / "unity-process.log",
            )
            stages["unityGate"]["exitCode"] = unity_exit
            unity_report = read_json(artifact_dir / "unity.json")
            stages["unityGate"]["passed"] = unity_exit == 0 and bool(
                unity_report.get("passed")
            )
        except Exception as exc:
            stages["unityGate"]["error"] = str(exc)

    missing_evidence = [
        str(path.relative_to(ROOT)).replace("\\", "/")
        for path in required_evidence
        if not path.is_file() or not validate_required_evidence(path)
    ]

    if fbx_path.is_file() and prefab_path.is_file():
        try:
            delivery_files = copy_generated_assets(fbx_path, prefab_path, delivery_dir)
            stages["delivery"]["passed"] = True
        except Exception as exc:
            stages["delivery"]["error"] = str(exc)

    return write_audit(
        job,
        delivery_dir,
        stages,
        blender_report,
        unity_report,
        missing_evidence,
        delivery_files,
    )


def blender_gate(job_path: Path) -> int:
    import bpy  # type: ignore
    import bmesh  # type: ignore

    job = load_job(job_path)
    artifact_dir = repo_path(job["artifactDir"])
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
            metrics["maxBoneInfluences"] = max(metrics["maxBoneInfluences"], len(groups))
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
        metrics["nonManifoldEdges"] += sum(1 for edge in bm.edges if not edge.is_manifold)
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

    report = {
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "metrics": metrics,
        "blenderVersion": bpy.app.version_string,
    }
    (artifact_dir / "blender.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0 if not errors else 2


def parse_args() -> argparse.Namespace:
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("run", "blender-gate"), default="run")
    parser.add_argument("--job", required=True)
    return parser.parse_args(args)


def main() -> int:
    options = parse_args()
    job_path = Path(options.job).resolve()
    try:
        if options.mode == "blender-gate":
            return blender_gate(job_path)
        return normal_mode(job_path)
    except Exception as exc:
        print(f"image2outfit: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
