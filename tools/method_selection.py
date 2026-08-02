#!/usr/bin/env python3
"""Select one construction profile and enforce its commercial evidence contract."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import audit_research_baseline

ROOT = Path(__file__).resolve().parents[1]
UNSTABLE_ENTRYPOINT = re.compile(
    r"(?:^|_)(?:v\d+|entry|refit|legacy)(?:_|$)",
    re.IGNORECASE,
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_job(product_id: str, root: Path = ROOT) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", product_id):
        raise ValueError(f"invalid product id: {product_id!r}")
    path = root / "config" / "products" / product_id / "job.json"
    if not path.is_file():
        raise FileNotFoundError(f"product job not found: {path}")
    return path


def _commercial_policy(root: Path) -> dict[str, Any]:
    release_policy = read_json(root / "config" / "release-policy.json")
    policy = release_policy.get("commercialMethodPolicy")
    if not isinstance(policy, dict):
        raise ValueError("release-policy.json is missing commercialMethodPolicy")
    return policy


def _construction_path(product_id: str, root: Path) -> Path:
    return root / "config" / "products" / product_id / "construction.json"


def _read_construction(product_id: str, root: Path) -> tuple[str | None, list[str]]:
    path = _construction_path(product_id, root)
    errors: list[str] = []
    try:
        value = read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"construction config unreadable: {exc}"]
    if value.get("schemaVersion") != 1:
        errors.append("construction.schemaVersion must be 1")
    profile = value.get("profile")
    if not isinstance(profile, str) or not profile:
        errors.append("construction.profile is required")
        return None, errors
    return profile, errors


def select(job: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    errors: list[str] = []
    product_id = job.get("id")
    if not isinstance(product_id, str) or not product_id:
        product_id = ""
        errors.append("job.id is required")

    try:
        policy = _commercial_policy(root)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        policy = {}
        errors.append(f"commercial policy unreadable: {exc}")

    profile_name, construction_errors = _read_construction(product_id, root)
    errors.extend(construction_errors)
    profiles = policy.get("profiles", {})
    profile = profiles.get(profile_name) if isinstance(profiles, dict) else None
    if profile_name and not isinstance(profile, dict):
        errors.append(f"unknown construction profile: {profile_name}")
        profile = {}
    elif not isinstance(profile, dict):
        profile = {}

    product_root = job.get("productRoot")
    if product_root != f"Assets/GenWorks/{product_id}":
        errors.append("productRoot must match Assets/GenWorks/<product-id>")

    build_script = job.get("buildScript")
    if not isinstance(build_script, str) or not build_script.startswith("tools/"):
        errors.append("buildScript must be a tracked tools/*.py path")
    else:
        script_path = root / build_script
        if not script_path.is_file():
            errors.append(f"buildScript does not exist: {build_script}")
        if UNSTABLE_ENTRYPOINT.search(Path(build_script).stem):
            errors.append(
                "buildScript must be a stable product entrypoint without version, entry, refit, or legacy naming"
            )

    pose_script = job.get("hostedPoseScript")
    if pose_script:
        if not isinstance(pose_script, str) or not pose_script.startswith("tools/"):
            errors.append("hostedPoseScript must be a tracked tools/*.py path")
        elif not (root / pose_script).is_file():
            errors.append(f"hostedPoseScript does not exist: {pose_script}")

    research = audit_research_baseline.audit(root)
    if research.get("passed") is not True:
        errors.extend(
            f"research baseline: {value}" for value in research.get("errors", [])
        )
    required_capabilities = list(profile.get("requiredCapabilities", []))
    production_coverage = set(research.get("productionCoverage", []))
    missing_capabilities = sorted(set(required_capabilities) - production_coverage)
    if missing_capabilities:
        errors.append(
            "research baseline does not cover selected profile: "
            + ", ".join(missing_capabilities)
        )

    required_evidence = list(profile.get("requiredEvidence", []))
    return {
        "schemaVersion": 1,
        "passed": not errors,
        "productId": product_id,
        "commercialProfile": policy.get("profileId"),
        "constructionProfile": profile_name,
        "constructionPath": _construction_path(product_id, root)
        .relative_to(root)
        .as_posix(),
        "description": profile.get("description"),
        "buildScript": build_script,
        "hostedPoseScript": pose_script,
        "requiredCapabilities": required_capabilities,
        "requiredCommercialEvidence": required_evidence,
        "evidenceRoot": f"Assets/GenWorks/{product_id}/Evidence/Commercial",
        "researchBaselineId": research.get("baselineId"),
        "researchProductionCoverage": sorted(production_coverage),
        "errors": errors,
    }


def _iso_datetime(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _metric_errors(
    kind: str,
    metrics: dict[str, Any],
    rules: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    for name, threshold in rules.get("minimum", {}).items():
        value = metrics.get(name)
        if not isinstance(value, (int, float)) or value < threshold:
            errors.append(f"{kind}.metrics.{name} must be >= {threshold}")
    for name, threshold in rules.get("maximum", {}).items():
        value = metrics.get(name)
        if not isinstance(value, (int, float)) or value > threshold:
            errors.append(f"{kind}.metrics.{name} must be <= {threshold}")
    for name in rules.get("requiredTrue", []):
        if metrics.get(name) is not True:
            errors.append(f"{kind}.metrics.{name} must be true")
    return errors


def validate_commercial_evidence(
    job: dict[str, Any],
    candidate_manifest_path: Path,
    root: Path = ROOT,
) -> dict[str, Any]:
    root = root.resolve()
    selection = select(job, root)
    errors = list(selection["errors"])
    evidence_results: dict[str, Any] = {}
    if not candidate_manifest_path.is_file():
        errors.append(f"candidate manifest missing: {candidate_manifest_path}")
        candidate_hash = ""
    else:
        candidate_hash = digest(candidate_manifest_path)

    try:
        policy = _commercial_policy(root)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        policy = {}
        errors.append(f"commercial policy unreadable: {exc}")
    contract = policy.get("evidenceContract", {})
    required_fields = contract.get("requiredFields", [])
    rules = contract.get("metricRules", {})
    product_id = str(job.get("id", ""))
    profile_name = selection.get("constructionProfile")
    evidence_root = root / str(job.get("productRoot")) / "Evidence" / "Commercial"

    for kind in selection.get("requiredCommercialEvidence", []):
        path = evidence_root / f"{kind}.json"
        item_errors: list[str] = []
        try:
            evidence = read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            evidence = {}
            item_errors.append(f"evidence unreadable: {exc}")

        for field in required_fields:
            if field not in evidence:
                item_errors.append(f"missing field: {field}")
        if evidence.get("schemaVersion") != contract.get("schemaVersion"):
            item_errors.append("schemaVersion mismatch")
        if evidence.get("kind") != kind:
            item_errors.append("kind mismatch")
        if evidence.get("productId") != product_id:
            item_errors.append("productId mismatch")
        if evidence.get("constructionProfile") != profile_name:
            item_errors.append("constructionProfile mismatch")
        if evidence.get("candidateManifestSha256") != candidate_hash:
            item_errors.append("candidateManifestSha256 mismatch")
        if evidence.get("status") != contract.get("passStatus"):
            item_errors.append("status must be PASS")
        if not _iso_datetime(evidence.get("checkedAt")):
            item_errors.append("checkedAt must be timezone-aware ISO-8601")
        if not isinstance(evidence.get("tool"), str) or not evidence.get("tool"):
            item_errors.append("tool is required")
        if not isinstance(evidence.get("notes"), str) or not evidence.get("notes").strip():
            item_errors.append("notes are required")

        source_artifacts = evidence.get("sourceArtifacts")
        if not isinstance(source_artifacts, list) or not source_artifacts:
            item_errors.append("sourceArtifacts must be a non-empty list")
        else:
            for artifact in source_artifacts:
                if not isinstance(artifact, str) or not artifact:
                    item_errors.append("sourceArtifacts entries must be strings")
                    continue
                artifact_path = (root / artifact).resolve()
                if root not in artifact_path.parents:
                    item_errors.append(f"source artifact escapes repository: {artifact}")
                elif not artifact_path.is_file():
                    item_errors.append(f"source artifact missing: {artifact}")

        metrics = evidence.get("metrics")
        if not isinstance(metrics, dict) or not metrics:
            item_errors.append("metrics must be a non-empty object")
        else:
            item_errors.extend(_metric_errors(kind, metrics, rules.get(kind, {})))

        evidence_results[kind] = {
            "path": path.relative_to(root).as_posix(),
            "passed": not item_errors,
            "errors": item_errors,
        }
        errors.extend(f"{kind}: {value}" for value in item_errors)

    return {
        "schemaVersion": 1,
        "passed": not errors,
        "productId": product_id,
        "commercialProfile": selection.get("commercialProfile"),
        "constructionProfile": profile_name,
        "candidateManifestSha256": candidate_hash or None,
        "selection": selection,
        "evidence": evidence_results,
        "errors": errors,
    }


def audit_all(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    products: list[dict[str, Any]] = []
    job_paths = sorted((root / "config" / "products").glob("*/job.json"))
    for path in job_paths:
        job = read_json(path)
        report = select(job, root)
        report["jobPath"] = path.relative_to(root).as_posix()
        products.append(report)

    job_products = {path.parent.name for path in job_paths}
    construction_products = {
        path.parent.name
        for path in (root / "config" / "products").glob("*/construction.json")
    }
    errors = [
        f"construction config has no job: {product_id}"
        for product_id in sorted(construction_products - job_products)
    ]
    errors.extend(
        f"{item['productId']}: {error}"
        for item in products
        for error in item.get("errors", [])
    )
    return {
        "schemaVersion": 1,
        "passed": not errors,
        "productCount": len(products),
        "products": products,
        "errors": errors,
    }
