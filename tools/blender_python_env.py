"""Restore and validate the Python environment embedded in pinned Blender."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROBE_MARKER = "IMAGE2OUTFIT_BLENDER_RUNTIME="
VERIFY_MARKER = "IMAGE2OUTFIT_BLENDER_PACKAGES="


@dataclass(frozen=True)
class PreparedEnvironment:
    command_prefix: list[str]
    environment: dict[str, str]
    report: dict[str, Any]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run(command: list[str], environment: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed with exit code {completed.returncode}: {' '.join(command)}\n{output}"
        )
    return output


def _marked_json(output: str, marker: str) -> dict[str, Any]:
    for line in output.splitlines():
        if marker in line:
            return json.loads(line.split(marker, 1)[1])
    raise RuntimeError(f"Blender output did not contain {marker}")


def probe_runtime(blender: str) -> dict[str, str]:
    expression = (
        "import bpy,json,platform,sys;"
        f"print('{PROBE_MARKER}'+json.dumps({{"
        "'blenderVersion':bpy.app.version_string.split()[0],"
        "'pythonVersion':platform.python_version(),"
        "'pythonPrefix':sys.prefix}}))"
    )
    output = _run(
        [
            blender,
            "--background",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python-expr",
            expression,
        ]
    )
    return _marked_json(output, PROBE_MARKER)


def bundled_python(prefix: str, python_version: str) -> Path:
    major_minor = ".".join(python_version.split(".")[:2])
    root = Path(prefix)
    candidates = (
        root / "bin" / "python.exe",
        root / "bin" / f"python{major_minor}.exe",
        root / "bin" / f"python{major_minor}",
        root / "bin" / "python3",
        root / "bin" / "python",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Blender bundled Python was not found under {prefix}")


def dependency_environment(target: Path) -> dict[str, str]:
    environment = os.environ.copy()
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(target) if not existing else str(target) + os.pathsep + existing
    )
    return environment


def blender_command(blender: str, arguments: list[str]) -> list[str]:
    return [blender, "--python-use-system-env", *arguments]


def _project_dependencies(root: Path, group: str) -> list[str]:
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        raise FileNotFoundError(f"Python project configuration missing: {pyproject}")
    with pyproject.open("rb") as stream:
        configuration = tomllib.load(stream)
    project = configuration.get("project", {})
    if group == "project":
        requirements = project.get("dependencies", [])
    else:
        requirements = project.get("optional-dependencies", {}).get(group)
    if not isinstance(requirements, list) or not requirements:
        raise ValueError(f"pyproject dependency group is empty or missing: {group}")
    if not all(isinstance(value, str) and value for value in requirements):
        raise ValueError(f"pyproject dependency group contains invalid entries: {group}")
    return requirements


def _expected_packages(lock: dict[str, Any]) -> dict[str, dict[str, str]]:
    packages = lock.get("blender", {}).get("python", {}).get("packages", {})
    if not isinstance(packages, dict) or not packages:
        raise ValueError("Blender Python packages are not locked")
    return packages


def _verify_packages(
    blender: str,
    target: Path,
    packages: dict[str, dict[str, str]],
) -> dict[str, str]:
    imports = [value["importName"] for value in packages.values()]
    distributions = list(packages)
    expression = (
        "import importlib,importlib.metadata,json;"
        + ";".join(f"importlib.import_module({name!r})" for name in imports)
        + f";print('{VERIFY_MARKER}'+json.dumps({{name:importlib.metadata.version(name) "
        + f"for name in {distributions!r}}}))"
    )
    output = _run(
        blender_command(
            blender,
            [
                "--background",
                "--factory-startup",
                "--python-exit-code",
                "1",
                "--python-expr",
                expression,
            ],
        ),
        dependency_environment(target),
    )
    return _marked_json(output, VERIFY_MARKER)


def prepare(
    blender: str,
    *,
    root: Path = ROOT,
    target: Path | None = None,
) -> PreparedEnvironment:
    lock = read_json(root / "config" / "toolchain-lock.json")
    blender_lock = lock.get("blender", {})
    python_lock = blender_lock.get("python", {})
    expected_blender = str(blender_lock.get("version", ""))
    expected_python = str(python_lock.get("version", ""))
    dependency_group = str(python_lock.get("dependencyGroup", ""))
    requirements = _project_dependencies(root, dependency_group)
    packages = _expected_packages(lock)
    runtime = probe_runtime(blender)
    if runtime.get("blenderVersion") != expected_blender:
        raise RuntimeError(
            f"Blender version mismatch: expected {expected_blender}, "
            f"found {runtime.get('blenderVersion') or 'missing'}"
        )
    if runtime.get("pythonVersion") != expected_python:
        raise RuntimeError(
            f"Blender Python version mismatch: expected {expected_python}, "
            f"found {runtime.get('pythonVersion') or 'missing'}"
        )
    dependency_target = target or root / ".image2outfit" / "blender-python"
    stamp_path = dependency_target / "image2outfit-environment.json"
    requirements_sha = hashlib.sha256(
        json.dumps(requirements, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    expected_stamp = {
        "schemaVersion": 1,
        "blenderVersion": expected_blender,
        "pythonVersion": expected_python,
        "requirementsSha256": requirements_sha,
    }
    try:
        stamp = read_json(stamp_path)
    except (OSError, json.JSONDecodeError):
        stamp = {}

    if stamp != expected_stamp:
        if dependency_target.exists():
            shutil.rmtree(dependency_target)
        dependency_target.mkdir(parents=True)
        uv = shutil.which("uv")
        if not uv:
            raise FileNotFoundError("uv is required to restore Blender Python packages")
        python_executable = bundled_python(runtime["pythonPrefix"], expected_python)
        _run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(python_executable),
                "--target",
                str(dependency_target),
                "--only-binary",
                ":all:",
                "--no-deps",
                *requirements,
            ]
        )

    actual_packages = _verify_packages(blender, dependency_target, packages)
    expected_versions = {
        name: str(value.get("version", "")) for name, value in packages.items()
    }
    if actual_packages != expected_versions:
        raise RuntimeError(
            f"Blender Python package mismatch: expected {expected_versions}, "
            f"found {actual_packages}"
        )
    stamp_path.write_text(
        json.dumps(expected_stamp, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = {
        "passed": True,
        **runtime,
        "dependencySource": "pyproject.toml",
        "dependencyGroup": dependency_group,
        "dependencySetSha256": requirements_sha,
        "packages": actual_packages,
    }
    return PreparedEnvironment(
        command_prefix=[blender, "--python-use-system-env"],
        environment=dependency_environment(dependency_target),
        report=report,
    )
