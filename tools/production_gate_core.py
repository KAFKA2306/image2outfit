#!/usr/bin/env python3
"""Stable facade for candidate and release orchestration."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import candidate_manifest as legacy
from candidate_orchestrator import _augment_audit, _run_candidate
from release_orchestrator import _run_release
from runtime_transaction import DirectoryTransaction

__all__ = [
    "DirectoryTransaction",
    "_augment_audit",
    "_run_candidate",
    "_run_release",
    "legacy",
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Transactional, research-bound customer-quality gate for image2outfit"
        )
    )
    parser.add_argument("--mode", choices=("candidate", "release"), required=True)
    parser.add_argument("--job", required=True)
    options = parser.parse_args()
    try:
        job_path = Path(options.job).resolve()
        job, policy = legacy.load(job_path)
        if options.mode == "release":
            return _run_release(job_path, job, policy)
        return _run_candidate(job_path, job, policy)
    except Exception as exc:
        print(f"image2outfit production gate: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
