#!/usr/bin/env python3
"""Single operator entrypoint for production, improvement, and repository audits."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(TOOLS))

from image2outfit import improvement  # noqa: E402
import improvement_loop  # noqa: E402
import method_selection  # noqa: E402
import runtime_paths  # noqa: E402
import avatar_workflow  # noqa: E402

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


def _avatar_cloth(outfits: list[str] | None, force: bool = False) -> int:
    configured = os.environ.get("IMAGE2OUTFIT_BLENDER", "").strip()
    candidates = [
        configured,
        str(ROOT / ".image2outfit" / "blender-4.4.3" / "blender.exe"),
        str(ROOT / ".image2outfit" / "blender" / "blender.exe"),
    ]
    blender = next((item for item in candidates if item and Path(item).is_file()), None)
    if blender is None:
        print(
            "image2outfit avatar cloth: pinned Blender 4.4.3 was not found",
            file=sys.stderr,
        )
        return 1
    ids = outfits or [
        "siroino-cyber-kawaii-large",
        "siroino-heather-hooded-bodysuit",
        "siroino-lace-halter-large",
        "siroino-military-sheer-romper-large",
        "siroino-nocturne-angel-set",
        "siroino-wide-cargo",
    ]
    script = TOOLS / "blender_cloth_simulation.py"
    failed = False
    for product_id in ids:
        job = ROOT / "config" / "products" / product_id / "job.json"
        if not job.is_file():
            print(
                f"image2outfit avatar cloth: missing job: {product_id}",
                file=sys.stderr,
            )
            failed = True
            continue
        command = [
            blender,
            "--python-use-system-env",
            "--background",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python",
            str(script),
            "--",
            "--job",
            str(job),
        ]
        if force:
            command.append("--force")
        result = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
        )
        failed = failed or result.returncode != 0
    return 1 if failed else 0


def _load_manifest(path_text: str) -> dict[str, Any]:
    path = (ROOT / path_text).resolve()
    if ROOT.resolve() not in path.parents and path != ROOT.resolve():
        raise improvement.ImprovementError("manifest must stay inside repository")
    return improvement.read_json(path)


def _improve(product_id: str, max_steps: int) -> int:
    trace: list[dict[str, Any]] = []
    try:
        for _ in range(max_steps):
            result = improvement_loop.advance(
                ROOT,
                product_id,
                regenerate=lambda: _product("candidate", product_id),
            )
            trace.append(result)
            status = str(result.get("status") or "UNKNOWN")
            if status in {"ITERATION_RECORDED", "REEVALUATED"}:
                continue
            output = {**result, "trace": trace}
            print(json.dumps(output, ensure_ascii=False, indent=2))
            if status == "NO_DEFECT":
                return 0
            if status in improvement_loop.WAITING:
                return 2
            return 0 if status == "ADOPTED" else 1
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        improvement.ImprovementError,
        improvement_loop.LoopError,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": "ERROR",
                    "productId": product_id,
                    "error": str(exc),
                    "trace": trace,
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "status": "MAX_STEPS_REACHED",
                "productId": product_id,
                "maxSteps": max_steps,
                "trace": trace,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 2


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
                "runner": str(
                    by_id.get(method_id, {}).get("runner") or "ubuntu-latest"
                ),
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
    improve.add_argument("--max-steps", type=int, default=8)

    matrix = commands.add_parser("experiment-matrix")
    matrix.add_argument("--manifest", required=True)

    experiment = commands.add_parser("experiment-method")
    experiment.add_argument("--manifest", required=True)
    experiment.add_argument("--method", required=True)

    aggregate = commands.add_parser("experiment-aggregate")
    aggregate.add_argument("--manifest", required=True)
    aggregate.add_argument("--results-dir")
    aggregate.add_argument("--output")

    avatar = commands.add_parser(
        "avatar",
        help="Run the generated avatar preflight, visual, ledger, and CAU handoff tools.",
    )
    avatar_commands = avatar.add_subparsers(dest="avatar_command", required=True)

    preflight = avatar_commands.add_parser("preflight")
    preflight.add_argument("--outfit", action="append")
    preflight.add_argument("--output")

    visual = avatar_commands.add_parser("visual")
    visual.add_argument("--outfit", action="append")
    visual.add_argument("--record-baseline", action="store_true")
    visual.add_argument("--output")

    ledger = avatar_commands.add_parser("ledger")
    ledger.add_argument("ledger_action", choices=("init", "record"))
    ledger.add_argument("--outfit-id")
    ledger.add_argument(
        "--status",
        choices=("PENDING", "READY", "UPLOADING", "SUCCEEDED", "FAILED", "SKIPPED"),
    )
    ledger.add_argument("--blueprint-id")
    ledger.add_argument("--upload-id")
    ledger.add_argument("--error")
    ledger.add_argument("--output")

    plan = avatar_commands.add_parser("plan")
    plan.add_argument("--output")

    run = avatar_commands.add_parser("run")
    run.add_argument("--record-baseline", action="store_true")
    run.add_argument("--output")

    cloth = avatar_commands.add_parser(
        "cloth",
        help="Bake native Blender Cloth and settled FBX evidence for the outfit set.",
    )
    cloth.add_argument("--outfit", action="append")
    cloth.add_argument("--force", action="store_true")

    audit = commands.add_parser("audit")
    audit.add_argument("target", choices=(*AUDIT_TARGETS, "all"))
    return parser


def main() -> int:
    options = build_parser().parse_args()
    if options.command in {"candidate", "release", "explain"}:
        return _product(options.command, options.product)
    if options.command == "improve":
        if options.max_steps < 1:
            print("--max-steps must be >= 1", file=sys.stderr)
            return 2
        return _improve(options.product, options.max_steps)
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
    if options.command == "avatar":
        if options.avatar_command == "cloth":
            return _avatar_cloth(options.outfit, options.force)
        if options.avatar_command == "ledger" and options.ledger_action == "record":
            if not options.outfit_id or not options.status:
                print(
                    "avatar ledger record requires --outfit-id and --status",
                    file=sys.stderr,
                )
                return 2
        return avatar_workflow.dispatch(ROOT, options)
    if options.command == "audit":
        return _audit_all() if options.target == "all" else _audit(options.target)
    raise AssertionError(options.command)


if __name__ == "__main__":
    raise SystemExit(main())
