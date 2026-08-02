#!/usr/bin/env python3
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
    command = [sys.executable, str(TOOLS / script), *arguments]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_product(product_id: str) -> tuple[Path, dict[str, Any], Path]:
    job_path = method_selection.resolve_job(product_id, ROOT)
    job = method_selection.read_json(job_path)
    artifact = ROOT / str(job["artifactDir"])
    return job_path, job, artifact


def _run_product(command: str, product_id: str) -> int:
    try:
        job_path, job, artifact = _load_product(product_id)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"image2outfit: {exc}", file=sys.stderr)
        return 1

    selection = method_selection.select(job, ROOT)
    _write(artifact / "method-selection.json", selection)
    if command == "explain":
        print(json.dumps(selection, ensure_ascii=False, indent=2))
        return 0 if selection["passed"] else 2
    if not selection["passed"]:
        print(json.dumps(selection, ensure_ascii=False, indent=2))
        return 2

    if command == "release":
        candidate_manifest = ROOT / str(job["candidateDir"]) / "candidate-manifest.json"
        commercial = method_selection.validate_commercial_evidence(
            job,
            candidate_manifest,
            ROOT,
        )
        _write(artifact / "commercial-method-quality.json", commercial)
        if not commercial["passed"]:
            print(json.dumps(commercial, ensure_ascii=False, indent=2))
            return 2

    return _run(
        "production_gate.py",
        "--mode",
        command,
        "--job",
        str(job_path),
    )


def _run_method_audit() -> int:
    report = method_selection.audit_all(ROOT)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


def _run_audit(name: str) -> int:
    if name == "methods":
        return _run_method_audit()
    return _run(AUDITS[name])


def _run_all_audits() -> int:
    failed = []
    for name in AUDIT_TARGETS:
        print(f"\n=== audit:{name} ===", flush=True)
        result = _run_audit(name)
        if result != 0:
            failed.append(name)
    if failed:
        print("\nFailed audits: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Single operator entry point for image2outfit production and maintenance"
    )
    commands = root.add_subparsers(dest="command", required=True)

    for name in ("candidate", "release", "explain"):
        command = commands.add_parser(name)
        command.add_argument(
            "--product",
            required=True,
            help="Product slug under config/products/<slug>",
        )

    audit = commands.add_parser("audit")
    audit.add_argument("target", choices=(*AUDIT_TARGETS, "all"))

    snapshot_audit = commands.add_parser("snapshot-audit")
    snapshot_audit.add_argument("--candidate", required=True)
    snapshot_audit.add_argument("--source", required=True)

    snapshot_package = commands.add_parser("snapshot-package")
    snapshot_package.add_argument("--root", required=True)

    migrate = commands.add_parser("migrate-genworks")
    migrate.add_argument("--apply", action="store_true")
    return root


def main() -> int:
    options = parser().parse_args()
    if options.command in {"candidate", "release", "explain"}:
        return _run_product(options.command, options.product)
    if options.command == "audit":
        if options.target == "all":
            return _run_all_audits()
        return _run_audit(options.target)
    if options.command == "snapshot-audit":
        return _run(
            "audit_snapshot.py",
            "--candidate",
            options.candidate,
            "--source",
            options.source,
        )
    if options.command == "snapshot-package":
        return _run("package_snapshot.py", "--root", options.root)
    if options.command == "migrate-genworks":
        arguments = ["--apply"] if options.apply else []
        return _run("migrate_jobs_to_genworks.py", *arguments)
    raise AssertionError(options.command)


if __name__ == "__main__":
    raise SystemExit(main())
