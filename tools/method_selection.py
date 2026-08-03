#!/usr/bin/env python3
"""Validate the declared construction contract and its commercial evidence."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import audit_research_baseline
import production_contract as contract

ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict[str, Any]:
    return contract.read_json(path)


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
    value = read_json(root / "config" / "release-policy.json").get(
        "commercialMethodPolicy"
    )
    if not isinstance(value, dict):
        raise ValueError("release-policy.json is missing commercialMethodPolicy")
    return value


def _construction_path(root: Path, product_id: str) -> Path:
    return contract.construction_path(root, product_id)


def select(job: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    product_id = job.get("id") if isinstance(job.get("id"), str) else ""
    errors: list[str] = []
    warnings: list[str] = []

    try:
        policy = read_json(root / "config" / "release-policy.json")
        commercial = _commercial_policy(root)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        policy = {}
        commercial = {}
        errors.append(f"release policy unreadable: {exc}")

    if policy:
        errors.extend(contract.validate_job(job, policy, root))
        construction, construction_errors, construction_warnings = (
            contract.validate_construction(job, policy, root)
        )
        errors.extend(construction_errors)
        warnings.extend(construction_warnings)
    else:
        construction = {}

    profile_name = construction.get("profile")
    profiles = commercial.get("profiles", {})
    profile = profiles.get(profile_name) if isinstance(profiles, dict) else None
    if not isinstance(profile, dict):
        profile = {}

    try:
        research = audit_research_baseline.audit(root)
    except Exception as exc:
        research = {"passed": False, "errors": [str(exc)]}
    if research.get("passed") is not True:
        errors.extend(
            f"research baseline: {message}" for message in research.get("errors", [])
        )
    required_capabilities = list(profile.get("requiredCapabilities", []))
    coverage = set(research.get("productionCoverage", []))
    missing = sorted(set(required_capabilities) - coverage)
    if missing:
        errors.append(
            "research baseline does not cover construction contract: "
            + ", ".join(missing)
        )

    construction_path = _construction_path(root, product_id)
    return {
        "schemaVersion": 2,
        "passed": not errors,
        "selectionMode": "DECLARED_CONSTRUCTION_CONTRACT",
        "productId": product_id,
        "productRoot": job.get("productRoot"),
        "commercialProfile": commercial.get("profileId"),
        "constructionProfile": profile_name,
        "constructionPath": construction_path.relative_to(root).as_posix(),
        "description": profile.get("description"),
        "buildScript": job.get("buildScript"),
        "hostedPoseScript": job.get("hostedPoseScript"),
        "requiredCapabilities": required_capabilities,
        "requiredCommercialEvidence": list(profile.get("requiredEvidence", [])),
        "requiredPoses": list(policy.get("requiredPoses", [])),
        "posePaths": contract.required_pose_paths(job, policy) if policy else {},
        "evidenceRoot": f"{job.get('productRoot')}/Evidence/Commercial",
        "researchBaselineId": research.get("baselineId"),
        "researchProductionCoverage": sorted(coverage),
        "warnings": warnings,
        "errors": list(dict.fromkeys(errors)),
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


def _metric_errors(
    kind: str, metrics: dict[str, Any], rule: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    for name, threshold in rule.get("minimum", {}).items():
        value = metrics.get(name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or value < threshold
        ):
            errors.append(f"{kind}.metrics.{name} must be >= {threshold}")
    for name, threshold in rule.get("maximum", {}).items():
        value = metrics.get(name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or value > threshold
        ):
            errors.append(f"{kind}.metrics.{name} must be <= {threshold}")
    for name in rule.get("requiredTrue", []):
        if metrics.get(name) is not True:
            errors.append(f"{kind}.metrics.{name} must be true")
    return errors


def _candidate_hashes(candidate_manifest: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    files = candidate_manifest.get("files")
    if not isinstance(files, list):
        return result
    for item in files:
        if isinstance(item, dict) and isinstance(item.get("sha256"), str):
            result.add(item["sha256"])
    return result


def validate_commercial_evidence(
    job: dict[str, Any], candidate_manifest_path: Path, root: Path = ROOT
) -> dict[str, Any]:
    root = root.resolve()
    selection = select(job, root)
    errors = list(selection["errors"])
    try:
        candidate_manifest = read_json(candidate_manifest_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        candidate_manifest = {}
        errors.append(f"candidate manifest unreadable: {exc}")
    candidate_hash = (
        digest(candidate_manifest_path) if candidate_manifest_path.is_file() else ""
    )
    candidate_hashes = _candidate_hashes(candidate_manifest)
    if not candidate_hash:
        errors.append(f"candidate manifest missing: {candidate_manifest_path}")

    try:
        policy = _commercial_policy(root)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        policy = {}
        errors.append(f"commercial policy unreadable: {exc}")
    evidence_contract = policy.get("evidenceContract", {})
    required_fields = evidence_contract.get("requiredFields", [])
    metric_rules = evidence_contract.get("metricRules", {})
    product_id = str(job.get("id", ""))
    profile_name = selection.get("constructionProfile")
    evidence_root = root / str(job.get("productRoot")) / "Evidence" / "Commercial"
    evidence_results: dict[str, Any] = {}

    for kind in selection.get("requiredCommercialEvidence", []):
        path = evidence_root / f"{kind}.json"
        item_errors: list[str] = []
        try:
            evidence = read_json(path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            evidence = {}
            item_errors.append(f"evidence unreadable: {exc}")

        item_errors.extend(
            f"missing field: {field}"
            for field in required_fields
            if field not in evidence
        )
        expected = {
            "schemaVersion": evidence_contract.get("schemaVersion"),
            "kind": kind,
            "productId": product_id,
            "constructionProfile": profile_name,
            "candidateManifestSha256": candidate_hash,
            "status": evidence_contract.get("passStatus"),
        }
        item_errors.extend(
            f"{field} mismatch"
            for field, value in expected.items()
            if evidence.get(field) != value
        )
        if not _valid_timestamp(evidence.get("checkedAt")):
            item_errors.append("checkedAt must be timezone-aware ISO-8601")

        tool = evidence.get("tool")
        if not isinstance(tool, dict):
            item_errors.append("tool must be an object")
        else:
            for field in ("id", "version", "command"):
                if not isinstance(tool.get(field), str) or not tool[field].strip():
                    item_errors.append(f"tool.{field} is required")

        artifacts, artifact_errors = contract.validate_hashed_artifacts(
            evidence.get("sourceArtifacts"), root=root
        )
        item_errors.extend(artifact_errors)
        for artifact in artifacts:
            if artifact["sha256"] not in candidate_hashes:
                item_errors.append(
                    "source artifact is not hash-bound into the candidate: "
                    + artifact["path"]
                )

        metrics = evidence.get("metrics")
        if not isinstance(metrics, dict) or not metrics:
            item_errors.append("metrics must be a non-empty object")
        else:
            item_errors.extend(
                _metric_errors(kind, metrics, metric_rules.get(kind, {}))
            )
        if not isinstance(evidence.get("notes"), str) or not evidence["notes"].strip():
            item_errors.append("notes are required")

        unique_errors = list(dict.fromkeys(item_errors))
        evidence_results[kind] = {
            "path": path.relative_to(root).as_posix(),
            "sha256": digest(path) if path.is_file() else None,
            "passed": not unique_errors,
            "errors": unique_errors,
        }
        errors.extend(f"{kind}: {message}" for message in unique_errors)

    return {
        "schemaVersion": 2,
        "passed": not errors,
        "productId": product_id,
        "commercialProfile": selection.get("commercialProfile"),
        "constructionProfile": profile_name,
        "candidateManifestSha256": candidate_hash or None,
        "selection": selection,
        "evidence": evidence_results,
        "errors": list(dict.fromkeys(errors)),
    }


def audit_all(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    job_paths = sorted((root / "config" / "products").glob("*/job.json"))
    products = []
    for path in job_paths:
        try:
            report = select(read_json(path), root)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            report = {
                "passed": False,
                "productId": path.parent.name,
                "errors": [f"job unreadable: {exc}"],
            }
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
        "schemaVersion": 2,
        "passed": not errors,
        "productCount": len(products),
        "products": products,
        "errors": errors,
    }
