#!/usr/bin/env python3
"""Delegate one product-specific stage script inside Blender."""

from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
ROOT = TOOLS_DIR.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


def parse_args() -> tuple[argparse.Namespace, list[str]]:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", required=True)
    parser.add_argument("--job", required=True)
    return parser.parse_known_args(raw)


def repo_path(value: str) -> Path:
    path = (ROOT / value).resolve()
    if path != ROOT and ROOT not in path.parents:
        raise ValueError(f"path escapes repository: {value}")
    return path


def main() -> int:
    args, forwarded = parse_args()
    job_path = Path(args.job).resolve()
    if not job_path.is_file():
        raise FileNotFoundError(f"job not found: {job_path}")
    script = repo_path(args.script)
    if script == Path(__file__).resolve():
        raise RuntimeError("stage script cannot point to the launcher")
    if not script.is_file() or script.suffix != ".py":
        raise FileNotFoundError(f"stage script not found: {args.script}")

    from visual_quality import install_render_quality_guard

    install_render_quality_guard()
    sys.argv = [str(script), "--", "--job", str(job_path), *forwarded]
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
