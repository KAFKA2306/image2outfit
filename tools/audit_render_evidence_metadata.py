#!/usr/bin/env python3
"""Fail when migrated Blender render evidence lacks reproducibility metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
KIND = "image2outfit-render-evidence-metadata"


def _numeric_vector(value: object, size: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == size
        and all(
            isinstance(item, (int, float)) and not isinstance(item, bool)
            for item in value
        )
    )


def validate_sidecar(artifact: Path, root: Path) -> list[str]:
    sidecar = artifact.with_name(artifact.name + ".render.json")
    relative_artifact = artifact.relative_to(root).as_posix()
    if not sidecar.is_file():
        return [f"missing render metadata: {relative_artifact}"]
    try:
        payload: Any = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid render metadata JSON for {relative_artifact}: {exc}"]
    if not isinstance(payload, dict):
        return [f"render metadata must be an object: {relative_artifact}"]

    errors: list[str] = []
    if payload.get("schemaVersion") != 1:
        errors.append(f"schemaVersion must be 1: {relative_artifact}")
    if payload.get("kind") != KIND:
        errors.append(f"kind must be {KIND}: {relative_artifact}")
    if payload.get("artifactPath") != relative_artifact:
        errors.append(f"artifactPath mismatch: {relative_artifact}")
    if (
        not isinstance(payload.get("generatorRevision"), str)
        or not payload["generatorRevision"].strip()
    ):
        errors.append(f"generatorRevision is required: {relative_artifact}")

    camera = payload.get("camera")
    if not isinstance(camera, dict):
        errors.append(f"camera object is required: {relative_artifact}")
    else:
        if not isinstance(camera.get("name"), str) or not camera["name"].strip():
            errors.append(f"camera.name is required: {relative_artifact}")
        if camera.get("type") not in {"PERSP", "ORTHO", "PANO"}:
            errors.append(f"camera.type is invalid: {relative_artifact}")
        if not _numeric_vector(camera.get("location"), 3):
            errors.append(
                f"camera.location must contain 3 numbers: {relative_artifact}"
            )
        if not _numeric_vector(camera.get("rotationEulerRadians"), 3):
            errors.append(
                f"camera.rotationEulerRadians must contain 3 numbers: {relative_artifact}"
            )
        for field in ("lensMm", "orthoScale"):
            value = camera.get(field)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                errors.append(f"camera.{field} must be numeric: {relative_artifact}")

    render = payload.get("render")
    if not isinstance(render, dict):
        errors.append(f"render object is required: {relative_artifact}")
    else:
        if not isinstance(render.get("engine"), str) or not render["engine"].strip():
            errors.append(f"render.engine is required: {relative_artifact}")
        for field in ("resolutionX", "resolutionY", "resolutionPercentage"):
            value = render.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                errors.append(
                    f"render.{field} must be a positive integer: {relative_artifact}"
                )
    return errors


def migrated_preview_roots(root: Path) -> list[Path]:
    genworks = root / "Assets" / "GenWorks"
    if not genworks.is_dir():
        return []
    migrated: list[Path] = []
    for preview_root in sorted(genworks.glob("*/Previews")):
        if preview_root.is_dir() and any(preview_root.rglob("*.png.render.json")):
            migrated.append(preview_root)
    return migrated


def audit(root: Path = ROOT) -> list[str]:
    genworks = root / "Assets" / "GenWorks"
    if not genworks.is_dir():
        return ["Assets/GenWorks is missing"]

    errors: list[str] = []
    for preview_root in migrated_preview_roots(root):
        artifacts = sorted(
            path for path in preview_root.rglob("*.png") if path.is_file()
        )
        for artifact in artifacts:
            errors.extend(validate_sidecar(artifact, root))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    options = parser.parse_args()
    errors = audit(options.root.resolve())
    if errors:
        print("render-evidence metadata audit: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("render-evidence metadata audit: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
