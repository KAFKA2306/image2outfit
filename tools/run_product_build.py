#!/usr/bin/env python3
"""Run a product-specific Blender build script from a schema-v2 job.

Blender does not consistently add the repository ``tools`` directory to
``sys.path`` when a script is invoked by path. This launcher establishes the
shared module path, validates the delegated script, applies canonical visual
quality defaults, and forwards the original tracked or materialized job without
introducing seed/body substitution.
"""

from __future__ import annotations

import argparse
import json
import runpy
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
ROOT = TOOLS_DIR.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    return parser.parse_args(raw)


def repo_path(value: str) -> Path:
    path = (ROOT / value).resolve()
    if path != ROOT and ROOT not in path.parents:
        raise ValueError(f"path escapes repository: {value}")
    return path


def main() -> int:
    args = parse_args()
    job_path = Path(args.job).resolve()
    if not job_path.is_file():
        raise FileNotFoundError(f"job not found: {job_path}")
    job = json.loads(job_path.read_text(encoding="utf-8-sig"))
    script_value = job.get("productBuildScript")
    if not isinstance(script_value, str) or not script_value:
        raise ValueError("job.productBuildScript is required")
    script = repo_path(script_value)
    if script == Path(__file__).resolve():
        raise RuntimeError("productBuildScript cannot point to the launcher")
    if not script.is_file():
        raise FileNotFoundError(f"product build script not found: {script_value}")

    from visual_quality import install_render_quality_guard

    install_render_quality_guard()
    sys.argv = [str(script), "--", "--job", str(job_path)]
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
