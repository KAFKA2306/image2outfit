#!/usr/bin/env python3
"""Resolve one product construction profile and validate commercial evidence."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import audit_research_baseline

ROOT = Path(__file__).resolve().parents[1]
UNSTABLE_BUILD_NAME = re.compile(
    r"(?:^|_)(?:v\d+|entry|refit|legacy)(?:_|$)", re.IGNORECASE
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
    policy = read_json(root / "config" / "release-policy.json").get(
        "commercialMethodPolicy"
    )
    if not isinstance(policy, dict):
        raise ValueError("release-policy.json is missing commercialMethodPolicy")
    return policy


def _construction_path(root: Path, product_id: str) -> Path:
    return root / "config" / "products" / product_id / "construction.json"


def _construction_profile(root: Path, product_id: str) -> tuple[str | None, list[str]]:
    path = _construction_path(root, product_id)
    try:
        value = read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"construction config unreadable: {exc}"]
    errors: list[str] = []
    if value.get("schemaVersion") != 1:
        errors.append("construction.schemaVersion must be 1")
    profile = value.get("profile")
    if not isinstance(profile, str) or not profile:
        errors.append("construction.profile is required")
        return None, errors
    return profile, errors


def select(job: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    product_id = job.get("id") if isinstance(job.get("id"), str) else ""
    errors = [] if product_id else ["job.id is required"]

    try:
        commercial = _commercial_policy(root)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        commercial = {}
        errors.append(f"commercial policy unreadable: {exc}")

    profile_name, profile_errors = _construction_profile(root, product_id)
    errors.extend(profile_errors)
    profiles = commercial.get("profiles", {})
    profile = profiles.get(profile_name) if isinstance(profiles, dict) else None
    if not isinstance(profile, dict):
        if profile_name:
            errors.append(f"unknown construction profile: {profile_name}")
        profile = {}

    if job.get("productRoot") != f"Assets/GenWorks/{product_id}":
        errors.append("productRoot must match Assets/GenWorks/<product-id>")

    build_script = job.get("buildScript")
    if not isinstance(build_script, str) or not build_script.startswith("tools/"):
        errors.append("buildScript must be a tracked tools/*.py path")
    else:
        if not (root / build_script).is_file():
            errors.append(f"buildScript does not exist: {build_script}")
        if UNSTABLE_BUILD_NAME.search(Path(build_script).stem):
            errors.append(
                "buildScript must use a stable product entrypoint without version, entry, refit, or legacy naming"
            )

    pose_script = job.get("hostedPoseScript")
    if pose_script and (
        not isinstance(pose_script, str)
        or not pose_script.startswith("tools/")
        or not (root / pose_script).is_file()
    ):
        errors.append(f"invalid hostedPoseScript: {pose_script!r}")

    research = audit_research_baseline.audit(root)
    if research.get("passed") is not True:
        errors.extend(
            f"research baseline: {message}"
            for message in research.get("errors", [])
        )
    required_capabilities = list(profile.get("requiredCapabilities", []))
    coverage = set(research.get("productionCoverage", []))
    missing = sorted(set(required_capabilities) - coverage)
    if missing:
        errors.append(
            "research baseline does not cover selected profile: " + ", ".join(missing)
        )

    construction_path = _construction_path(root, product_id)
    return {
        "schemaVersion": 1,
        "passed": not errors,
        "productId": product_id,
        "commercialProfile": commercial.get("profileId"),
        "constructionProfile": profile_name,
        "constructionPath": construction_path.relative_to(root).as_posix(),
        "description": profile.get("description"),
        "buildScript": build_script,
        "hostedPoseScript": pose_script,
        "requiredCapabilities": required_capabilities,
        "requiredCommercialEvidence": list(profile.get("requiredEvidence", [])),
        "evidenceRoot": f"Assets/GenWorks/{product_id}/Evidence/Commercial",
        "researchBaselineId": research.get("baselineId"),
        "researchProductionCoverage": sorted(coverage),
        "errors": errors,
    }


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _metric_errors(kind: str, metrics: dict[str, Any], rule: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for name, threshold in rule.get("minimum", {}).items():
        value = metrics.get(name)
        if not isinstance(value, (int, float)) or value < threshold:
            errors.append(f"{kind}.metrics.{name} must be >= {threshold}")
    for name, threshold in rule.get("maximum", {}).items():
        value = metrics.get(name)
        if not isinstance(value, (int, float)) or value > threshold:
            errors.append(f"{kind}.metrics.{name} must be <= {threshold}")
    for name in rule.get("requiredTrue", []):
        if metrics.get(name) is not True:
            errors.append(f"{kind}.metrics.{name} must be true")
    return errors


def validate_commercial_evidence(
    job: dict[str, Any], candidate_manifest_path: Path, root: Path = ROOT
) -> dict[str, Any]:
    root = root.resolve()
    selection = select(job, root)
    errors = list(selection["errors"])
    candidate_hash = digest(candidate_manifest_path) if candidate_manifest_path.is_file() else ""
    if not candidate_hash:
        errors.append(f"candidate manifest missing: {candidate_manifest_path}")

    try:
        policy = _commercial_policy(root)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        policy = {}
        errors.append(f"commercial policy unreadable: {exc}")
    contract = policy.get("evidenceContract", {})
    required_fields = contract.get("requiredFields", [])
    metric_rules = contract.get("metricRules", {})
    product_id = str(job.get("id", ""))
    profile_name = selection.get("constructionProfile")
    evidence_root = root / str(job.get("productRoot")) / "Evidence" / "Commercial"
    evidence_results: dict[str, Any] = {}

    for kind in selection.get("requiredCommercialEvidence", []):
        path = evidence_root / f"{kind}.json"
        item_errors: list[str] = []
        try:
            evidence = read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            evidence = {}
            item_errors.append(f"evidence unreadable: {exc}")

        item_errors.extend(
            f"missing field: {field}" for field in required_fields if field not in evidence
        )
        expected = {
            "schemaVersion": contract.get("schemaVersion"),
            "kind": kind,
            "productId": product_id,
            "constructionProfile": profile_name,
            "candidateManifestSha256": candidate_hash,
            "status": contract.get("passStatus"),
        }
        item_errors.extend(
            f"{field} mismatch" for field, value in expected.items() if evidence.get(field) != value
        )
        if not _valid_timestamp(evidence.get("checkedAt")):
            item_errors.append("checkedAt must be timezone-aware ISO-8601")
        if not isinstance(evidence.get("tool"), str) or not evidence.get("tool"):
            item_errors.append("tool is required")
        if not isinstance(evidence.get("notes"), str) or not evidence.get("notes").strip():
            item_errors.append("notes are required")

        sources = evidence.get("sourceArtifacts")
        if not isinstance(sources, list) or not sources:
            item_errors.append("sourceArtifacts must be a non-empty list")
        else:
            for value in sources:
                if not isinstance(value, str) or not value:
                    item_errors.append("sourceArtifacts entries must be strings")
                    continue
                source = (root / value).resolve()
                if root not in source.parents or not source.is_file():
                    item_errors.append(f"source artifact missing or invalid: {value}")

        metrics = evidence.get("metrics")
        if not isinstance(metrics, dict) or not metrics:
            item_errors.append("metrics must be a non-empty object")
        else:
            item_errors.extend(_metric_errors(kind, metrics, metric_rules.get(kind, {})))

        evidence_results[kind] = {
            "path": path.relative_to(root).as_posix(),
            "passed": not item_errors,
            "errors": item_errors,
        }
        errors.extend(f"{kind}: {message}" for message in item_errors)

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
    job_paths = sorted((root / "config" / "products").glob("*/job.json"))
    products = []
    for path in job_paths:
        report = select(read_json(path), root)
        report["jobPath"] = path.relative_to(root).as_posix()
        products.append(report)

    job_ids = {path.parent.name for path in job_paths}
    construction_ids = {
        path.parent.name
        for path in (root / "config" / "products").glob("*/construction.json")
    }
    errors = [
        f"construction config has no job: {product_id}"
        for product_id in sorted(construction_ids - job_ids)
    ]
    errors.extend(
        f"{product['productId']}: {error}"
        for product in products
        for error in product.get("errors", [])
    )
    return {
        "schemaVersion": 1,
        "passed": not errors,
        "productCount": len(products),
        "products": products,
        "errors": errors,
    }
