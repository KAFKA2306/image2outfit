#!/usr/bin/env python3
"""Execute one tracked product request through the canonical garment pipeline.

This wrapper owns no pipeline stages, quality gates, or product-completion state.
It only derives the canonical runtime checkpoint path and delegates execution to
``tools/run_garment_pipeline.py`` so external schedulers can safely queue runs.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import runtime_paths  # noqa: E402

PIPELINE_RUNNER = TOOLS / "run_garment_pipeline.py"
CHECKPOINT_NAME = "pipeline-state.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    return parser.parse_args()


def _repo_path(path: Path) -> Path:
    resolved = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise ValueError(f"request escapes repository: {path}")
    return resolved


def _read_request(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("request must contain a JSON object")
    if value.get("schemaVersion") != 1:
        raise ValueError("request.schemaVersion must be 1")
    product_id = value.get("productId")
    if not isinstance(product_id, str) or not product_id:
        raise ValueError("request.productId is required")
    return value


def execution_paths(request_path: Path) -> tuple[str, Path, Path]:
    request_path = _repo_path(request_path)
    request = _read_request(request_path)
    product_id = str(request["productId"])
    runtime = runtime_paths.for_product(ROOT, product_id)
    checkpoint = runtime.reports / CHECKPOINT_NAME
    return product_id, request_path, checkpoint


def build_pipeline_command(request_path: Path, checkpoint: Path) -> list[str]:
    command = [
        sys.executable,
        str(PIPELINE_RUNNER),
        "--request",
        str(request_path),
        "--execute",
        "--checkpoint-output",
        str(checkpoint),
    ]
    if checkpoint.is_file():
        command.extend(("--resume-state", str(checkpoint)))
    return command


def main() -> int:
    args = parse_args()
    product_id, request_path, checkpoint = execution_paths(args.request)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    command = build_pipeline_command(request_path, checkpoint)
    print(
        json.dumps(
            {
                "schemaVersion": 1,
                "productId": product_id,
                "request": request_path.relative_to(ROOT).as_posix(),
                "checkpoint": checkpoint.relative_to(ROOT).as_posix(),
                "resume": checkpoint.is_file(),
                "schedulerOwnsCompletion": False,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
