#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

GLOBAL_CONFIG_FILES = {
    "blender-python-requirements.txt",
    "genworks-layout.json",
    "job.schema.v2.json",
    "release-policy.json",
    "toolchain-lock.json",
}
FORBIDDEN_STATE_DIRS = (".github/run", ".github/status")


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    message: str


def relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def add(findings: list[Finding], code: str, path: Path, root: Path, message: str) -> None:
    findings.append(Finding(code, relative(path, root), message))


def audit(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    findings: list[Finding] = []

    for value in FORBIDDEN_STATE_DIRS:
        path = root / value
        if path.exists():
            add(
                findings,
                "committed-runtime-state",
                path,
                root,
                "workflow triggers and run telemetry belong in GitHub Actions, not git",
            )

    config_root = root / "config"
    if config_root.is_dir():
        for path in sorted(config_root.iterdir()):
            if path.is_file() and path.name not in GLOBAL_CONFIG_FILES:
                add(
                    findings,
                    "global-config-residue",
                    path,
                    root,
                    "product-specific configuration must live under config/products/<product-id>/",
                )

    product_ids: set[str] = set()
    products_root = config_root / "products"
    if products_root.is_dir():
        for product_dir in sorted(path for path in products_root.iterdir() if path.is_dir()):
            product_id = product_dir.name
            product_ids.add(product_id)
            if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", product_id):
                add(findings, "invalid-product-id", product_dir, root, "invalid product directory name")
                continue
            job_path = product_dir / "job.json"
            license_path = product_dir / "license.json"
            for required in (job_path, license_path):
                if not required.is_file():
                    add(findings, "missing-product-config", required, root, "required product config is missing")
            if not job_path.is_file():
                continue
            try:
                job = read_json(job_path)
            except (OSError, json.JSONDecodeError) as exc:
                add(findings, "invalid-product-job", job_path, root, str(exc))
                continue
            expected_root = f"Assets/GenWorks/Products/{product_id}"
            expected_license = f"config/products/{product_id}/license.json"
            expected_manifest = f"{expected_root}/ProductManifest.json"
            checks = {
                "id": (job.get("id"), product_id),
                "productRoot": (job.get("productRoot"), expected_root),
                "productManifestPath": (job.get("productManifestPath"), expected_manifest),
                "licenseEvidence": (job.get("licenseEvidence"), expected_license),
            }
            for field, (actual, expected) in checks.items():
                if actual != expected:
                    add(
                        findings,
                        "product-config-boundary",
                        job_path,
                        root,
                        f"{field} must be {expected!r}, got {actual!r}",
                    )
            for field in ("buildScript", "hostedPoseScript"):
                value = job.get(field)
                if value and not (root / value).is_file():
                    add(
                        findings,
                        "missing-product-script",
                        root / value,
                        root,
                        f"{field} referenced by {product_id} does not exist",
                    )

    workflow_root = root / ".github" / "workflows"
    if workflow_root.is_dir():
        for workflow in sorted(workflow_root.glob("*.y*ml")):
            text = workflow.read_text(encoding="utf-8")
            lowered = text.lower()
            if "contents: write" in lowered or re.search(r"\bgit\s+push\b", lowered):
                add(
                    findings,
                    "self-mutating-workflow",
                    workflow,
                    root,
                    "CI must upload artifacts or open reviewed changes, not push directly to main",
                )
            if any(value in lowered for value in (".github/run/", ".github/status/")):
                add(
                    findings,
                    "workflow-runtime-state",
                    workflow,
                    root,
                    "workflow runtime state must not be written into the repository",
                )
            for product_id in product_ids:
                if product_id.lower() in lowered:
                    add(
                        findings,
                        "product-specific-workflow",
                        workflow,
                        root,
                        f"workflow hard-codes product id {product_id}; use job_path input instead",
                    )

    taskfile = root / "Taskfile.yml"
    if taskfile.is_file():
        lowered = taskfile.read_text(encoding="utf-8").lower()
        for product_id in product_ids:
            if product_id.lower() in lowered:
                add(
                    findings,
                    "product-specific-task",
                    taskfile,
                    root,
                    f"Taskfile hard-codes product id {product_id}; require a variable instead",
                )
        if re.search(r"^\s{2}(audit|package):haolan:", lowered, flags=re.MULTILINE):
            add(
                findings,
                "legacy-specific-task",
                taskfile,
                root,
                "snapshot maintenance tasks must accept arbitrary paths",
            )

    gitignore = root / ".gitignore"
    if gitignore.is_file():
        ignored = set(gitignore.read_text(encoding="utf-8").splitlines())
        for value in ("/.github/run/", "/.github/status/"):
            if value not in ignored:
                add(
                    findings,
                    "missing-runtime-ignore",
                    gitignore,
                    root,
                    f"missing ignore rule {value}",
                )

    return {
        "schemaVersion": 1,
        "passed": not findings,
        "findingCount": len(findings),
        "findings": [asdict(item) for item in findings],
    }


def main() -> int:
    result = audit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
