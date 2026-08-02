#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"

AUDITS = {
    "toolchain": "audit_toolchain.py",
    "repository": "audit_repository_hygiene.py",
    "genworks": "audit_genworks_layout.py",
    "tools": "audit_tool_ownership.py",
    "research": "audit_research_baseline.py",
}


def _run(script: str, *arguments: str) -> int:
    command = [sys.executable, str(TOOLS / script), *arguments]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def _run_all_audits() -> int:
    failed = []
    for name, script in AUDITS.items():
        print(f"\n=== audit:{name} ===", flush=True)
        result = _run(script)
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

    for name in ("candidate", "release"):
        command = commands.add_parser(name)
        command.add_argument("--job", required=True)

    audit = commands.add_parser("audit")
    audit.add_argument("target", choices=(*AUDITS, "all"))

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
    if options.command in {"candidate", "release"}:
        return _run(
            "production_gate.py",
            "--mode",
            options.command,
            "--job",
            options.job,
        )
    if options.command == "audit":
        if options.target == "all":
            return _run_all_audits()
        return _run(AUDITS[options.target])
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
