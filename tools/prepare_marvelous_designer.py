#!/usr/bin/env python3
"""Prepare a replayable Marvelous Designer request from canonical product files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from image2outfit.marvelous_designer import (  # noqa: E402
    MarvelousDesignerContractError,
    build_request,
    canonical_json,
    sha256_file,
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _repo_path(relative: str) -> Path:
    path = (ROOT / relative).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise MarvelousDesignerContractError(f"path escapes repository: {relative}") from exc
    return path


def _load_optional(path: Path) -> dict[str, Any] | None:
    return _read_json(path) if path.is_file() else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True, help="Repository-relative canonical job.json")
    parser.add_argument("--output", help="Repository-relative request manifest output")
    parser.add_argument("--initialization", help="Optional Stage 06 result containing placements")
    parser.add_argument("--simulation-steps", type=int, default=120)
    args = parser.parse_args()

    job_path = _repo_path(args.job)
    job = _read_json(job_path)
    pipeline = job.get("garmentPipeline")
    if not isinstance(pipeline, dict):
        raise MarvelousDesignerContractError("job.garmentPipeline is required")

    bound_paths: dict[str, Path] = {"job": job_path}
    for key, label in (
        ("patternContractPath", "pattern"),
        ("stitchGraphPath", "stitchGraph"),
        ("materialRecipePath", "materialRecipe"),
    ):
        value = pipeline.get(key)
        if not isinstance(value, str) or not value:
            raise MarvelousDesignerContractError(f"job.garmentPipeline.{key} is required")
        bound_paths[label] = _repo_path(value)

    initialization = None
    if args.initialization:
        initialization_path = _repo_path(args.initialization)
        initialization = _load_optional(initialization_path)
        bound_paths["initialization"] = initialization_path

    source_bindings = {
        label: sha256_file(path)
        for label, path in bound_paths.items()
        if path.is_file()
    }
    request = build_request(
        job=job,
        pattern=_read_json(bound_paths["pattern"]),
        stitch_graph=_read_json(bound_paths["stitchGraph"]),
        material_recipe=_read_json(bound_paths["materialRecipe"]),
        initialization=initialization,
        source_bindings=source_bindings,
        simulation_steps=args.simulation_steps,
    )
    product_id = str(job["id"])
    output = (
        _repo_path(args.output)
        if args.output
        else ROOT
        / ".image2outfit"
        / "products"
        / product_id
        / "marvelous-designer"
        / "request.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(canonical_json(request), encoding="utf-8")

    blockers = []
    if request["arrangement"]["status"] != "BOUND":
        blockers.append("canonical initialize-3d placement is not bound")
    if request["materials"]["unassignedPatterns"]:
        blockers.append("some patterns have no canonical material assignment")
    print(
        json.dumps(
            {
                "status": "PREPARED",
                "executionStatus": "UNVERIFIED",
                "productId": product_id,
                "request": str(output.relative_to(ROOT)),
                "requestSha256": request["requestSha256"],
                "blockers": blockers,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
