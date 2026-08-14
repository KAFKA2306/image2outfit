#!/usr/bin/env python3
"""Hosted Wide Cargo entrypoint using canonical runtime paths and render evidence."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import render_evidence_bootstrap  # noqa: F401,E402
import runtime_paths  # noqa: E402
import siroino_strappy_knit_build as common  # noqa: E402
import siroino_wide_cargo_product as product  # noqa: E402

_ORIGINAL_LOAD_JOB = common.load_job


def _load_job_with_runtime_reports():
    path, job = _ORIGINAL_LOAD_JOB()
    adapted = dict(job)
    adapted["artifactDir"] = runtime_paths.relative(
        ROOT,
        runtime_paths.for_job(ROOT, job).reports,
    )
    return path, adapted


def main() -> int:
    # The v2 schema intentionally removed per-product runtime directories in #100.
    # This legacy generator still consumes artifactDir internally, so derive it
    # from the canonical runtime layout instead of putting the legacy field back
    # into tracked job.json.
    common.load_job = _load_job_with_runtime_reports
    return product.main()


if __name__ == "__main__":
    raise SystemExit(main())
