#!/usr/bin/env python3
"""Register a Blender render hook that records reproducible evidence metadata."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import bpy

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1
KIND = "image2outfit-render-evidence-metadata"


def _read_job() -> dict[str, Any]:
    try:
        separator = sys.argv.index("--")
        arguments = sys.argv[separator + 1 :]
        job_index = arguments.index("--job")
        job_path = Path(arguments[job_index + 1]).resolve()
    except (ValueError, IndexError) as exc:
        raise RuntimeError("render metadata bootstrap requires --job <path>") from exc
    return json.loads(job_path.read_text(encoding="utf-8"))


def _source_commit() -> str:
    configured = os.environ.get("GITHUB_SHA", "").strip()
    if configured:
        return configured
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def install() -> None:
    job = _read_job()
    product_root = (ROOT / str(job["productRoot"])).resolve()
    preview_root = product_root / "Previews"
    generator_revision = str(
        job.get("renderLoopRevision") or job.get("buildRevision") or ""
    ).strip()
    if not generator_revision:
        raise RuntimeError(
            "render evidence requires job.renderLoopRevision or job.buildRevision"
        )
    source_commit = _source_commit()

    def record(scene: bpy.types.Scene, _depsgraph: object | None = None) -> None:
        output = Path(bpy.path.abspath(scene.render.filepath)).resolve()
        try:
            output.relative_to(preview_root)
        except ValueError:
            return
        camera = scene.camera
        if camera is None:
            raise RuntimeError(f"render evidence has no active camera: {output}")
        data = camera.data
        metadata = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": KIND,
            "artifactPath": _relative(output),
            "generatorRevision": generator_revision,
            "sourceCommit": source_commit or None,
            "camera": {
                "name": camera.name,
                "type": str(getattr(data, "type", "")),
                "location": [float(value) for value in camera.location],
                "rotationEulerRadians": [
                    float(value) for value in camera.rotation_euler
                ],
                "lensMm": float(getattr(data, "lens", 0.0)),
                "orthoScale": float(getattr(data, "ortho_scale", 0.0)),
            },
            "render": {
                "engine": str(scene.render.engine),
                "resolutionX": int(scene.render.resolution_x),
                "resolutionY": int(scene.render.resolution_y),
                "resolutionPercentage": int(scene.render.resolution_percentage),
            },
        }
        sidecar = output.with_name(output.name + ".render.json")
        sidecar.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    handlers = bpy.app.handlers.render_post
    if not any(
        getattr(handler, "__name__", "") == "record_render_evidence"
        for handler in handlers
    ):
        record.__name__ = "record_render_evidence"
        handlers.append(record)


install()
