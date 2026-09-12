#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GLOBAL_CONFIG_FILES = {
    "candidate-manifest.schema.v2.json",
    "genworks-handoff-policy.json",
    "genworks-layout.json",
    "job.schema.v2.json",
    "pr-merge-policy.json",
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


def add(
    findings: list[Finding], code: str, path: Path, root: Path, message: str
) -> None:
    findings.append(Finding(code, relative(path, root), message))


def is_ref_only_branch_hygiene(workflow: Path, lowered: str) -> bool:
    """Allow only the narrow workflow that deletes obsolete non-main branch refs."""
    required = (
        workflow.name == "branch-hygiene.yml",
        "contents: write" in lowered,
        "actions/github-script" in lowered,
        "github.rest.git.deleteref" in lowered,
        "protectedbranches" in lowered,
        "'main'" in lowered or '"main"' in lowered,
    )
    forbidden = (
        "actions/checkout" in lowered,
        bool(re.search(r"\bgit\s+push\b", lowered)),
        "createorupdatefilecontents" in lowered,
        "github.rest.git.updateref" in lowered,
        "github.rest.git.createref" in lowered,
        "github.rest.repos.createcommitstatus" in lowered,
    )
    return all(required) and not any(forbidden)


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
        for product_dir in sorted(
            path for path in products_root.iterdir() if path.is_dir()
        ):
            product_id = product_dir.name
            product_ids.add(product_id)
            if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", product_id):
                add(
                    findings,
                    "invalid-product-id",
                    product_dir,
                    root,
                    "invalid product directory name",
                )
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
            if (
                not isinstance(previews, dict)
                or set(previews) != REQUIRED_PREVIEW_VIEWS
            ):
                add(
                    findings,
                    "invalid-preview-contract",
                    job_path,
                    root,
                    "previewPaths must contain front, back, left, right, and three-quarter",
                )
            else:
                for name, value in previews.items():
                    if not isinstance(value, str) or not value.startswith(
                        expected_root + "/"
                    ):
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