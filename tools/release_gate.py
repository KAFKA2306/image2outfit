#!/usr/bin/env python3
"""Technical-candidate compatibility facade. Release lives in production_gate."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pipeline as legacy
from candidate_manifest import (
    JOB_SCHEMA_PATH,
    POLICY_PATH,
    ROOT,
    UNITY_PIPELINE_PATH,
    candidate_files,
    digest,
    inputs,
    inside,
    license_gate,
    load,
    manifest,
    now,
    path,
    png_size,
    preview_gate,
    read,
    rel,
    required_job_fields,
    verify_candidate,
    write,
)
from technical_candidate import run_candidate

__all__ = [
    "JOB_SCHEMA_PATH",
    "POLICY_PATH",
    "ROOT",
    "UNITY_PIPELINE_PATH",
    "candidate_files",
    "digest",
    "inputs",
    "inside",
    "license_gate",
    "load",
    "manifest",
    "now",
    "path",
    "png_size",
    "preview_gate",
    "read",
    "rel",
    "required_job_fields",
    "run_candidate",
    "verify_candidate",
    "write",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode", choices=("candidate", "blender-gate", "release"), required=True
    )
    parser.add_argument("--job", required=True)
    options = parser.parse_args()
    if options.mode == "release":
        print(
            "image2outfit: direct release_gate release is disabled; "
            "use tools/production_gate.py",
            file=sys.stderr,
        )
        return 2
    try:
        job_path = Path(options.job).resolve()
        job, policy = load(job_path)
        if options.mode == "blender-gate":
            return legacy.blender_gate(job_path)
        return run_candidate(job_path, job, policy)
    except Exception as exc:
        print(f"image2outfit v2: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
