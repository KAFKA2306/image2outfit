#!/usr/bin/env python3
"""Run or plan the canonical step-by-step garment reconstruction pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from image2outfit.audit import write_audit_bundle
from image2outfit.pipeline import (
    PIPELINE_STAGES,
    ExecutionMode,
    new_pipeline_state,
    run_langchain,
    run_langgraph,
    run_pipeline,
)
from pipeline_stage_adapters import build_registry, load_profile


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument(
        "--profile",
        type=Path,
        default=ROOT / "config/pipeline-profiles/garment-reconstruction-v1.json",
    )
    parser.add_argument(
        "--engine",
        choices=("deterministic", "langchain", "langgraph"),
        default="deterministic",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--audit-root",
        type=Path,
        default=Path(".image2outfit/audit"),
        help="Repository-relative root for immutable per-run audit bundles.",
    )
    return parser.parse_args()


def _mapping(value: object, label: str) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"request.{label} must be an object")
    return value


def main() -> int:
    args = parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    profile = load_profile(args.profile)
    product_id = request["productId"]
    target_avatar = request["targetAvatar"]
    source_reference = request["sourceReference"]
    run_id = request.get("runId")
    if run_id is not None and (not isinstance(run_id, str) or not run_id):
        raise ValueError("request.runId must be a non-empty string when provided")
    variables = {
        "productId": str(product_id),
        "targetAvatar": str(target_avatar),
        "sourceReference": str(source_reference),
        **{
            str(key): str(value)
            for key, value in _mapping(request.get("variables"), "variables").items()
        },
    }
    mode = ExecutionMode.EXECUTE if args.execute else ExecutionMode.PLAN
    state = new_pipeline_state(
        product_id=product_id,
        target_avatar=target_avatar,
        source_reference=source_reference,
        profile_id=profile["profileId"],
        execution_mode=mode,
        run_id=run_id,
    )
    registry = build_registry(
        profile,
        execute=args.execute,
        bindings=_mapping(request.get("stageBindings"), "stageBindings"),
        variables=variables,
    )
    if args.engine == "langgraph":
        result = run_langgraph(state, registry)
    elif args.engine == "langchain":
        result = run_langchain(state, registry)
    else:
        result = run_pipeline(state, registry)

    audit_root = args.audit_root if args.audit_root.is_absolute() else ROOT / args.audit_root
    result["audit"] = write_audit_bundle(
        result,
        audit_root=audit_root,
        canonical_stages=[stage.value for stage in PIPELINE_STAGES],
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    expected = "EXECUTED" if args.execute else "PLANNED"
    return 0 if result.get("status") == expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
