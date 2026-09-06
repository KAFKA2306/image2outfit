#!/usr/bin/env python3
"""Resolve one product build from Git changes and emit a canonical CI environment."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from contract_io import canonical_product_root, read_json, validate_schema_file

JOB_PATH = re.compile(r"^config/products/([a-z0-9][a-z0-9._-]*)/job\.json$")
REQUEST_PATH = re.compile(r"^config/pipeline/requests/([a-z0-9][a-z0-9._-]*)\.json$")
PATTERN_PATH = re.compile(
    r"^Assets/GenWorks/([a-z0-9][a-z0-9._-]*)/Source/Patterns/.+$"
)
ZERO_SHA = "0" * 40


@dataclass(frozen=True)
class Resolution:
    selected_job: str | None
    environment: dict[str, str]
    reason: str


def changed_paths(
    *, event_name: str, base: str | None, head: str, root: Path
) -> list[str]:
    if base and base != ZERO_SHA:
        comparison = (
            f"{base}...{head}" if event_name == "pull_request" else f"{base}..{head}"
        )
        command = ["git", "diff", "--name-only", comparison]
    else:
        command = ["git", "show", "--pretty=", "--name-only", head]
    output = subprocess.check_output(command, cwd=root, text=True)
    return [line.strip() for line in output.splitlines() if line.strip()]


def _local_tool_dependencies(root: Path, build_script: str) -> set[str]:
    """Return local tools/*.py files imported by a product build script."""
    discovered = {build_script}
    pending = [build_script]
    while pending:
        relative = pending.pop()
        path = root / relative
        if not path.is_file() or path.suffix != ".py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=relative)
        module_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                module_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                module_names.add(node.module)
        for module_name in module_names:
            candidate = f"tools/{module_name.replace('.', '/')}.py"
            if candidate in discovered or not (root / candidate).is_file():
                continue
            discovered.add(candidate)
            pending.append(candidate)
    return discovered


def _jobs_for_product_scripts(root: Path) -> dict[str, set[str]]:
    """Map executable product scripts and local dependencies to their jobs."""
    owners: dict[str, set[str]] = {}
    for path in sorted((root / "config/products").glob("*/job.json")):
        relative = path.relative_to(root).as_posix()
        job = read_json(path)
        entrypoints = {
            value
            for field in ("buildScript", "hostedPoseScript")
            if isinstance((value := job.get(field)), str) and value
        }
        for entrypoint in entrypoints:
            for dependency in _local_tool_dependencies(root, entrypoint):
                owners.setdefault(dependency, set()).add(relative)
    return owners


def select_job(
    changed: Iterable[str], root: Path, *, include_pipeline_request: bool
) -> tuple[str | None, str]:
    changed_paths = list(changed)
    jobs: set[str] = set()
    script_owners = _jobs_for_product_scripts(root)
    for value in changed_paths:
        job_match = JOB_PATH.fullmatch(value)
        if job_match:
            jobs.add(value)
            continue
        request_match = (
            REQUEST_PATH.fullmatch(value) if include_pipeline_request else None
        )
        if request_match:
            candidate = f"config/products/{request_match.group(1)}/job.json"
            if (root / candidate).is_file():
                jobs.add(candidate)
            continue
        pattern_match = PATTERN_PATH.fullmatch(value)
        if pattern_match:
            candidate = f"config/products/{pattern_match.group(1)}/job.json"
            if (root / candidate).is_file():
                jobs.add(candidate)
            continue
        jobs.update(script_owners.get(value, set()))
    if len(jobs) != 1:
        return None, f"selected-product-jobs-{len(jobs)}"
    return next(iter(jobs)), "selected"


def _validate_namespace(job_path: str, job: dict[str, object]) -> str:
    match = JOB_PATH.fullmatch(job_path)
    if not match:
        raise ValueError("job_path must match config/products/<product-id>/job.json")
    product_id = match.group(1)
    expected_root = canonical_product_root(product_id)
    if job.get("id") != product_id:
        raise ValueError("product job id does not match its namespace")
    if job.get("productRoot") != expected_root:
        raise ValueError("product root does not match its namespace")
    if job.get("productManifestPath") != f"{expected_root}/ProductManifest.json":
        raise ValueError("product manifest does not match its namespace")
    for field in (
        "blendPath",
        "fbxAssetPath",
        "prefabAssetPath",
        "integratedPrefabAssetPath",
    ):
        value = job.get(field)
        if not isinstance(value, str) or not value.startswith(f"{expected_root}/"):
            raise ValueError(f"{field} must stay inside {expected_root}")
    return product_id


def resolve(
    *,
    root: Path,
    explicit_job: str | None,
    changed: Iterable[str],
    materialize_job: bool,
    include_pipeline_request: bool,
) -> Resolution:
    root = root.resolve()
    selected = (explicit_job or "").strip()
    if not selected:
        selected, reason = select_job(
            changed, root, include_pipeline_request=include_pipeline_request
        )
        if selected is None:
            return Resolution(
                selected_job=None,
                environment={
                    "SKIP_PRODUCT_BUILD": "true",
                    "BUILD_SCOPE_REASON": reason,
                },
                reason=reason,
            )
    if JOB_PATH.fullmatch(selected) is None:
        raise ValueError("job_path must match config/products/<product-id>/job.json")
    resolved = (root / selected).resolve()
    if root not in resolved.parents or not resolved.is_file():
        raise ValueError(f"product job not found: {selected}")
    job = read_json(resolved)
    schema_errors = validate_schema_file(
        job, root / "config/job.schema.v2.json", selected
    )
    if schema_errors:
        raise ValueError("invalid product job: " + "; ".join(schema_errors))
    product_id = _validate_namespace(selected, job)

    request = root / "config/pipeline/requests" / f"{product_id}.json"
    pipeline_mode = include_pipeline_request and request.is_file()
    request_path = ""
    if pipeline_mode:
        request_value = read_json(request)
        if request_value.get("productId") != product_id:
            raise ValueError("pipeline request product identity mismatch")
        request_path = request.relative_to(root).as_posix()

    if job.get("automaticBuild") is False and not pipeline_mode:
        reason = f"{product_id}-manual-recovery"
        return Resolution(
            selected_job=selected,
            environment={
                "SKIP_PRODUCT_BUILD": "true",
                "BUILD_SCOPE_REASON": reason,
            },
            reason=reason,
        )

    runtime = f".image2outfit/products/{product_id}"
    runtime_job = (
        f"Assets/_Local/Jobs/{product_id}/job.json" if materialize_job else selected
    )
    lock = read_json(root / "config/toolchain-lock.json")
    blender = lock.get("blender")
    if not isinstance(blender, dict) or not isinstance(blender.get("version"), str):
        raise ValueError("config/toolchain-lock.json is missing blender.version")
    blender_version = blender["version"]

    environment = {
        "SKIP_PRODUCT_BUILD": "false",
        "BUILD_SCOPE_REASON": "selected",
        "PIPELINE_MODE": "true" if pipeline_mode else "false",
        "TRACKED_JOB_PATH": selected,
        "JOB_PATH": runtime_job,
        "JOB_ID": product_id,
        "PRODUCT_ROOT": str(job["productRoot"]),
        "PRODUCT_RUNTIME": runtime,
        "REPORT_DIR": f"{runtime}/reports",
        "CANDIDATE_DIR": f"{runtime}/candidate",
        "RELEASE_DIR": f"{runtime}/release",
        "BUILD_SCRIPT": str(job["buildScript"]),
        "BLEND_PATH": str(job["blendPath"]),
        "HOSTED_POSE_SCRIPT": str(job.get("hostedPoseScript", "")),
        "REQUEST_PATH": request_path,
        "CHECKPOINT_PATH": f"{runtime}/pipeline-state.json",
        "PRODUCT_AUDIT": f".image2outfit/audit/{product_id}",
        "BLENDER_VERSION": blender_version,
        "BLENDER_SERIES": ".".join(blender_version.split(".")[:2]),
    }
    return Resolution(selected_job=selected, environment=environment, reason="selected")


def write_github_env(path: Path, environment: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        for name, value in environment.items():
            if "\n" in value or "\r" in value:
                raise ValueError(f"environment value contains a newline: {name}")
            stream.write(f"{name}={value}\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-path", default="")
    parser.add_argument("--event-name", default="")
    parser.add_argument("--base-sha", default="")
    parser.add_argument("--head-sha", default="HEAD")
    parser.add_argument("--github-env", type=Path)
    parser.add_argument("--materialize-job", action="store_true")
    parser.add_argument("--include-pipeline-request", action="store_true")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    changed = (
        []
        if args.job_path
        else changed_paths(
            event_name=args.event_name,
            base=args.base_sha or None,
            head=args.head_sha,
            root=root,
        )
    )
    result = resolve(
        root=root,
        explicit_job=args.job_path or None,
        changed=changed,
        materialize_job=args.materialize_job,
        include_pipeline_request=args.include_pipeline_request,
    )
    if args.github_env:
        write_github_env(args.github_env, result.environment)
    print(
        json.dumps(
            {
                "selectedJob": result.selected_job,
                "reason": result.reason,
                "environment": result.environment,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())