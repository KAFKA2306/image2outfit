#!/usr/bin/env python3
"""Single public CLI for selecting and running an image2outfit product pipeline."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import method_selection

ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_gate(mode: str, job_path: Path) -> int:
    command = [
        sys.executable,
        str(ROOT / "tools" / "production_gate.py"),
        "--mode",
        mode,
        "--job",
        str(job_path),
    ]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def load_product(product_id: str) -> tuple[Path, dict[str, Any], Path]:
    job_path = method_selection.resolve_job(product_id, ROOT)
    job = method_selection.read_json(job_path)
    artifact = ROOT / str(job["artifactDir"])
    return job_path, job, artifact


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Select a product by slug, derive one construction profile, and run only the "
            "quality gates required by that profile."
        )
    )
    parser.add_argument("action", choices=("candidate", "release", "explain", "audit"))
    parser.add_argument("--product", help="Product slug under config/products/<slug>")
    args = parser.parse_args()

    if args.action == "audit":
        report = method_selection.audit_all(ROOT)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1

    if not args.product:
        parser.error("--product is required for candidate, release, and explain")

    try:
        job_path, job, artifact = load_product(args.product)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"image2outfit: {exc}", file=sys.stderr)
        return 1

    selection = method_selection.select(job, ROOT)
    write_json(artifact / "method-selection.json", selection)
    if args.action == "explain":
        print(json.dumps(selection, ensure_ascii=False, indent=2))
        return 0 if selection["passed"] else 2
    if not selection["passed"]:
        print(json.dumps(selection, ensure_ascii=False, indent=2))
        return 2

    if args.action == "release":
        candidate_manifest = ROOT / str(job["candidateDir"]) / "candidate-manifest.json"
        commercial = method_selection.validate_commercial_evidence(
            job,
            candidate_manifest,
            ROOT,
        )
        write_json(artifact / "commercial-method-quality.json", commercial)
        if not commercial["passed"]:
            print(json.dumps(commercial, ensure_ascii=False, indent=2))
            return 2

    return run_gate(args.action, job_path)


if __name__ == "__main__":
    raise SystemExit(main())
