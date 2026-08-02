#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GLOBAL_CONFIG_FILES = {
    "genworks-handoff-policy.json",
    "genworks-layout.json",
    "job.schema.v2.json",
    "release-policy.json",
    "toolchain-lock.json",
}
FORBIDDEN_STATE_DIRS = (".github/run", ".github/status")
CHECKPOINT_PATH_FIELDS = (
    "productManifestPath",
    "blendPath",
    "fbxAssetPath",
    "prefabAssetPath",
    "integratedPrefabAssetPath",
)
REQUIRED_PREVIEW_VIEWS = {"front", "back", "left", "right", "three-quarter"}


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
            files = sorted(item for item in path.rglob("*") if item.is_file())
            if files:
                for file in files:
                    add(
                        findings,
                        "committed-runtime-state",
                        file,
                        root,
                        "workflow runtime state belongs in GitHub Actions",
                    )
            else:
                add(
                    findings,
                    "committed-runtime-state",
                    path,
                    root,
                    "workflow runtime state directory must not be tracked",
                )

    config_root = root / "config"
    handoff_policy_path = config_root / "genworks-handoff-policy.json"
    handoff_policy: dict[str, Any] = {}
    if not handoff_policy_path.is_file():
        add(
            findings,
            "missing-handoff-policy",
            handoff_policy_path,
            root,
            "the resumable GenWorks handoff policy is required",
        )
    else:
        try:
            handoff_policy = read_json(handoff_policy_path)
        except (OSError, json.JSONDecodeError) as exc:
            add(findings, "invalid-handoff-policy", handoff_policy_path, root, str(exc))

    if config_root.is_dir():
        for path in sorted(config_root.iterdir()):
            if path.is_file() and path.name not in GLOBAL_CONFIG_FILES:
                add(
                    findings,
                    "global-config-residue",
                    path,
                    root,
                    "product configuration must live under config/products/<product-id>/",
                )

    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        add(
            findings,
            "missing-python-project",
            pyproject,
            root,
            "Python dependencies and environment groups must be declared in pyproject.toml",
        )
    if config_root.is_dir():
        for requirements_file in sorted(config_root.glob("*requirements*.txt")):
            add(
                findings,
                "environment-config-residue",
                requirements_file,
                root,
                "Python environment declarations belong in pyproject.toml",
            )

    allowed_statuses = set(handoff_policy.get("statuses", []))
    automated_gates = tuple(
        handoff_policy.get("requiredAutomatedTechnicalGatesBeforeHumanReview", [])
    )
    human_gates = tuple(handoff_policy.get("requiredHumanReleaseGates", []))

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
                    add(
                        findings,
                        "missing-product-config",
                        required,
                        root,
                        "required product config is missing",
                    )
            if not job_path.is_file():
                continue
            try:
                job = read_json(job_path)
            except (OSError, json.JSONDecodeError) as exc:
                add(findings, "invalid-product-job", job_path, root, str(exc))
                continue

            expected_root = f"Assets/GenWorks/{product_id}"
            expected = {
                "id": product_id,
                "productRoot": expected_root,
                "productManifestPath": f"{expected_root}/ProductManifest.json",
                "licenseEvidence": f"config/products/{product_id}/license.json",
            }
            for field, expected_value in expected.items():
                if job.get(field) != expected_value:
                    add(
                        findings,
                        "product-config-boundary",
                        job_path,
                        root,
                        f"{field} must be {expected_value!r}",
                    )

            for field in ("buildScript", "hostedPoseScript", "productBuildScript"):
                value = job.get(field)
                if value and not (root / value).is_file():
                    add(
                        findings,
                        "missing-product-script",
                        root / value,
                        root,
                        f"{field} does not exist",
                    )

            delivery_assets = job.get("deliveryAssets")
            if not isinstance(delivery_assets, list):
                add(
                    findings,
                    "missing-delivery-contract",
                    job_path,
                    root,
                    "deliveryAssets must list the tracked handoff checkpoint",
                )
                delivery_set: set[str] = set()
            else:
                delivery_set = {str(value) for value in delivery_assets}

            for field in CHECKPOINT_PATH_FIELDS:
                value = job.get(field)
                if not isinstance(value, str) or not value:
                    add(
                        findings,
                        "missing-checkpoint-path",
                        job_path,
                        root,
                        f"{field} is required for resumable work",
                    )
                    continue
                if not value.startswith(expected_root + "/"):
                    add(
                        findings,
                        "checkpoint-outside-product",
                        job_path,
                        root,
                        f"{field} must stay under {expected_root}",
                    )
                if value not in delivery_set:
                    add(
                        findings,
                        "checkpoint-not-delivered",
                        job_path,
                        root,
                        f"{field} must be present in deliveryAssets",
                    )

            previews = job.get("previewPaths")
            if not isinstance(previews, dict) or set(previews) != REQUIRED_PREVIEW_VIEWS:
                add(
                    findings,
                    "invalid-preview-contract",
                    job_path,
                    root,
                    "previewPaths must contain front, back, left, right, and three-quarter",
                )
            else:
                for name, value in previews.items():
                    if not isinstance(value, str) or not value.startswith(expected_root + "/"):
                        add(
                            findings,
                            "preview-outside-product",
                            job_path,
                            root,
                            f"preview {name} must stay under {expected_root}",
                        )
                    elif value not in delivery_set:
                        add(
                            findings,
                            "preview-not-delivered",
                            job_path,
                            root,
                            f"preview {name} must be present in deliveryAssets",
                        )

            manifest_path = root / str(job.get("productManifestPath", ""))
            if not manifest_path.is_file():
                add(
                    findings,
                    "missing-working-manifest",
                    manifest_path,
                    root,
                    "each product must persist a tracked resumable manifest",
                )
                continue
            try:
                manifest = read_json(manifest_path)
            except (OSError, json.JSONDecodeError) as exc:
                add(findings, "invalid-working-manifest", manifest_path, root, str(exc))
                continue

            if manifest.get("productId") != product_id:
                add(
                    findings,
                    "manifest-product-id",
                    manifest_path,
                    root,
                    f"productId must be {product_id!r}",
                )
            if manifest.get("productRoot") != expected_root:
                add(
                    findings,
                    "manifest-product-root",
                    manifest_path,
                    root,
                    f"productRoot must be {expected_root!r}",
                )

            status = manifest.get("status")
            if status not in allowed_statuses:
                add(
                    findings,
                    "invalid-working-status",
                    manifest_path,
                    root,
                    f"status must be one of {sorted(allowed_statuses)}",
                )

            handoff = manifest.get("handoff")
            if not isinstance(handoff, dict):
                add(
                    findings,
                    "missing-handoff-state",
                    manifest_path,
                    root,
                    "handoff metadata is required",
                )
            else:
                if handoff.get("resumable") is not True:
                    add(
                        findings,
                        "non-resumable-product",
                        manifest_path,
                        root,
                        "handoff.resumable must be true",
                    )
                if handoff.get("canonicalWorkspace") != expected_root:
                    add(
                        findings,
                        "handoff-root-mismatch",
                        manifest_path,
                        root,
                        f"handoff.canonicalWorkspace must be {expected_root!r}",
                    )
                if handoff.get("doNotRebuildFromZero") is not True:
                    add(
                        findings,
                        "zero-rebuild-not-blocked",
                        manifest_path,
                        root,
                        "handoff.doNotRebuildFromZero must be true",
                    )

            gates = manifest.get("technicalGates")
            if not isinstance(gates, dict):
                add(
                    findings,
                    "missing-technical-gates",
                    manifest_path,
                    root,
                    "technicalGates are required",
                )
                continue

            if status in {"TECHNICAL_READY", "HUMAN_REVIEW_PENDING", "RELEASED"}:
                for gate in automated_gates:
                    if gates.get(gate) != "PASS":
                        add(
                            findings,
                            "premature-technical-ready",
                            manifest_path,
                            root,
                            f"{gate} must PASS before {status}",
                        )
            if status == "RELEASED":
                for gate in human_gates:
                    if gates.get(gate) != "PASS":
                        add(
                            findings,
                            "premature-release",
                            manifest_path,
                            root,
                            f"{gate} must PASS before RELEASED",
                        )

    product_tokens = {
        product_id.replace("-", "_").replace(".", "_") for product_id in product_ids
    }
    for root_script in sorted(root.glob("*.py")):
        if any(token and token in root_script.stem.lower() for token in product_tokens):
            add(
                findings,
                "product-script-at-repository-root",
                root_script,
                root,
                "product-specific Python scripts must live under tools/ or the product workspace",
            )

    workflow_root = root / ".github" / "workflows"
    if workflow_root.is_dir():
        for workflow in sorted(workflow_root.glob("*.y*ml")):
            lowered = workflow.read_text(encoding="utf-8").lower()
            if "contents: write" in lowered or re.search(r"\bgit\s+push\b", lowered):
                add(
                    findings,
                    "self-mutating-workflow",
                    workflow,
                    root,
                    "CI must upload artifacts, not push directly to main",
                )
            if any(value in lowered for value in (".github/run/", ".github/status/")):
                add(
                    findings,
                    "workflow-runtime-state",
                    workflow,
                    root,
                    "workflow runtime state must not enter git",
                )
            for product_id in product_ids:
                if product_id.lower() in lowered:
                    add(
                        findings,
                        "product-specific-workflow",
                        workflow,
                        root,
                        f"workflow hard-codes {product_id}",
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
                    f"Taskfile hard-codes {product_id}",
                )
        if re.search(r"^\s{2}(audit|package):haolan:", lowered, flags=re.MULTILINE):
            add(
                findings,
                "legacy-specific-task",
                taskfile,
                root,
                "snapshot maintenance must accept arbitrary paths",
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
