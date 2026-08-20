#!/usr/bin/env python3
"""Single operator entrypoint for production, improvement, and repository audits."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(TOOLS))

from image2outfit import improvement  # noqa: E402
import method_selection  # noqa: E402
import runtime_paths  # noqa: E402

AUDITS = {
    "toolchain": "audit_toolchain.py",
    "repository": "audit_repository_hygiene.py",
    "runtime": "audit_runtime_layout.py",
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
        runtime_paths.migrate_legacy_product_outputs(ROOT, product_id)
        runtime = runtime_paths.for_job(ROOT, job)
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"image2outfit: {exc}", file=sys.stderr)
        return 1

    selection = method_selection.select(job, ROOT)
    _write(runtime.reports / "method-selection.json", selection)
    if command == "explain":
        print(json.dumps(selection, ensure_ascii=False, indent=2))
        return 0 if selection["passed"] else 2
    if not selection["passed"]:
        print(json.dumps(selection, ensure_ascii=False, indent=2))
        return 2

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


def _load_manifest(path_text: str) -> dict[str, Any]:
    path = (ROOT / path_text).resolve()
    if ROOT.resolve() not in path.parents and path != ROOT.resolve():
        raise improvement.ImprovementError("manifest must stay inside repository")
    return improvement.read_json(path)


def _improve(product_id: str) -> int:
    try:
        plan = improvement.plan_improvement(ROOT, product_id)
        path = improvement.persist_plan(ROOT, product_id, plan)
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        improvement.ImprovementError,
    ) as exc:
        print(f"image2outfit improve: {exc}", file=sys.stderr)
        return 1
    output = {
        **plan,
        "planPath": path.relative_to(ROOT).as_posix(),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def _experiment_matrix(path_text: str) -> int:
    try:
        manifest = _load_manifest(path_text)
        methods = improvement.experiment_matrix(manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"image2outfit experiment-matrix: {exc}", file=sys.stderr)
        return 1
    by_id = {
        item.get("id"): item
        for item in manifest.get("methods", [])
        if isinstance(item, dict)
    }
    matrix = {
        "include": [
            {
                "method": method_id,
                "runner": str(by_id.get(method_id, {}).get("runner") or "ubuntu-latest"),
            }
            for method_id in methods
        ]
    }
    print(json.dumps(matrix, ensure_ascii=False, separators=(",", ":")))
    return 0


def _experiment_method(path_text: str, method_id: str) -> int:
    try:
        manifest = _load_manifest(path_text)
        result = improvement.run_experiment_method(ROOT, manifest, method_id)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"image2outfit experiment-method: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 2


def _experiment_aggregate(
    path_text: str,
    result_dir_text: str | None,
    output_text: str | None,
) -> int:
    try:
        manifest = _load_manifest(path_text)
        result_dir = (ROOT / result_dir_text).resolve() if result_dir_text else None
        summary = improvement.aggregate_experiment_results(
            ROOT,
            manifest,
            result_dir=result_dir,
        )
        if output_text:
            output = (ROOT / output_text).resolve()
            if ROOT.resolve() not in output.parents:
                raise improvement.ImprovementError(
                    "aggregate output must stay inside repository"
                )
            improvement.write_json(output, summary)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"image2outfit experiment-aggregate: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("allRecorded") else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("candidate", "release", "explain"):
        command = commands.add_parser(name)
        command.add_argument("--product", required=True)

    improve = commands.add_parser("improve")
    improve.add_argument("--product", required=True)

    matrix = commands.add_parser("experiment-matrix")
    matrix.add_argument("--manifest", required=True)

    experiment = commands.add_parser("experiment-method")
    experiment.add_argument("--manifest", required=True)
    experiment.add_argument("--method", required=True)

    aggregate = commands.add_parser("experiment-aggregate")
    aggregate.add_argument("--manifest", required=True)
    aggregate.add_argument("--results-dir")
    aggregate.add_argument("--output")

    audit = commands.add_parser("audit")
    audit.add_argument("target", choices=(*AUDIT_TARGETS, "all"))
    migrate = commands.add_parser("migrate-genworks")
    migrate.add_argument("--apply", action="store_true")
    return parser


def main() -> int:
    options = build_parser().parse_args()
    if options.command in {"candidate", "release", "explain"}:
        return _product(options.command, options.product)
    if options.command == "improve":
        return _improve(options.product)
    if options.command == "experiment-matrix":
        return _experiment_matrix(options.manifest)
    if options.command == "experiment-method":
        return _experiment_method(options.manifest, options.method)
    if options.command == "experiment-aggregate":
        return _experiment_aggregate(
            options.manifest,
            options.results_dir,
            options.output,
        )
    if options.command == "audit":
        return _audit_all() if options.target == "all" else _audit(options.target)
    if options.command == "migrate-genworks":
        arguments = ["--apply"] if options.apply else []
        return _run("migrate_jobs_to_genworks.py", *arguments)
    raise AssertionError(options.command)


if __name__ == "__main__":
    raise SystemExit(main())
