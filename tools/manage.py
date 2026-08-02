#!/usr/bin/env python3
"""Single operator entrypoint for production, explanation, and repository audits."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import method_selection

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
AUDITS = {
    "toolchain": "audit_toolchain.py",
    "repository": "audit_repository_hygiene.py",
    "genworks": "audit_genworks_layout.py",
    "tools": "audit_tool_ownership.py",
    "research": "audit_research_baseline.py",
}
AUDIT_TARGETS = (*AUDITS, "methods")


def _run(script: str, *arguments: str) -> int:
    return subprocess.run(
        [sys.executable, str(TOOLS / script), *arguments],
        cwd=ROOT,
        check=False,
    ).returncode


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _product(command: str, product_id: str) -> int:
    try:
        job_path = method_selection.resolve_job(product_id, ROOT)
        job = method_selection.read_json(job_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"image2outfit: {exc}", file=sys.stderr)
        return 1

    artifact = ROOT / str(job["artifactDir"])
    selection = method_selection.select(job, ROOT)
    _write(artifact / "method-selection.json", selection)
    if command == "explain":
        print(json.dumps(selection, ensure_ascii=False, indent=2))
        return 0 if selection["passed"] else 2
    if not selection["passed"]:
        print(json.dumps(selection, ensure_ascii=False, indent=2))
        return 2

    # Commercial evidence enforcement belongs to production_gate.py itself.
    # Keeping it there prevents direct gate invocation from bypassing the contract.
    return _run(
        "production_gate.py",
        "--mode",
        command,
        "--job",
        str(job_path),
    )


def _audit(name: str) -> int:
    if name == "methods":
        report = method_selection.audit_all(ROOT)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1
    return _run(AUDITS[name])


def _audit_all() -> int:
    failed = []
    for name in AUDIT_TARGETS:
        print(f"\n=== audit:{name} ===", flush=True)
        if _audit(name) != 0:
            failed.append(name)
    if failed:
        print("\nFailed audits: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("candidate", "release", "explain"):
        command = commands.add_parser(name)
        command.add_argument("--product", required=True)
    audit = commands.add_parser("audit")
    audit.add_argument("target", choices=(*AUDIT_TARGETS, "all"))
    migrate = commands.add_parser("migrate-genworks")
    migrate.add_argument("--apply", action="store_true")
    return parser


def main() -> int:
    options = build_parser().parse_args()
    if options.command in {"candidate", "release", "explain"}:
        return _product(options.command, options.product)
    if options.command == "audit":
        return _audit_all() if options.target == "all" else _audit(options.target)
    if options.command == "migrate-genworks":
        arguments = ["--apply"] if options.apply else []
        return _run("migrate_jobs_to_genworks.py", *arguments)
    raise AssertionError(options.command)


if __name__ == "__main__":
    raise SystemExit(main())
