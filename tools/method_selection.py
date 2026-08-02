#!/usr/bin/env python3
"""Deterministic construction-profile selection and commercial evidence validation."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
UNSTABLE_ENTRYPOINT = re.compile(
    r"(?:^|_)(?:v\d+|entry|refit|legacy)(?:_|\.|$)",
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


def _profile_config(root: Path) -> dict[str, Any]:
    return read_json(root / "config" / "construction-profiles.json")


def _research(root: Path) -> dict[str, Any]:
    return read_json(
        root
        / "Assets"
        / "GenWorks"
        / "Shared"
        / "Research"
        / "2026-garment-methods.json"
    )


def select(job: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    config = _profile_config(root)
    product_id = job.get("id")
    profile_name = config.get("productAssignments", {}).get(product_id)
    profile = config.get("profiles", {}).get(profile_name)
    errors: list[str] = []

    if not isinstance(product_id, str) or not product_id:
        errors.append("job.id is required")
    if not isinstance(profile_name, str) or not profile_name:
        errors.append(f"product has no construction profile assignment: {product_id}")
    elif not isinstance(profile, dict):
        errors.append(f"unknown construction profile assignment: {profile_name}")
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

    required_capabilities = list(profile.get("requiredCapabilities", []))
    required_evidence = list(profile.get("requiredCommercialEvidence", []))
    research = _research(root)
    covered = {
        capability
        for method in research.get("methods", [])
        if method.get("implementationTrack")
        in {"ADOPT_PRINCIPLE", "PROTOTYPE", "BENCHMARK"}
        for capability in method.get("capabilities", [])
    }
    missing_capabilities = sorted(set(required_capabilities) - covered)
    if missing_capabilities:
        errors.append(
            "research baseline does not cover selected profile: "
            + ", ".join(missing_capabilities)
        )

    return {
        "schemaVersion": 1,
        "passed": not errors,
        "productId": product_id,
        "commercialProfile": config.get("defaultCommercialProfile"),
        "constructionProfile": profile_name,
        "description": profile.get("description"),
        "buildScript": build_script,
        "hostedPoseScript": pose_script,
        "requiredCapabilities": required_capabilities,
        "requiredCommercialEvidence": required_evidence,
        "evidenceRoot": f"Assets/GenWorks/{product_id}/Evidence/Commercial",
        "researchBaselineId": research.get("baselineId"),
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
    selection = select(job, root)
    errors = list(selection["errors"])
    evidence_results: dict[str, Any] = {}
    if not candidate_manifest_path.is_file():
        errors.append(f"candidate manifest missing: {candidate_manifest_path}")
        candidate_hash = ""
    else:
        candidate_hash = digest(candidate_manifest_path)

    config = _profile_config(root)
    contract = config.get("evidenceContract", {})
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
        if evidence.get("status") != contract.get("status"):
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
                if root.resolve() not in artifact_path.parents:
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
    products: list[dict[str, Any]] = []
    for path in sorted((root / "config" / "products").glob("*/job.json")):
        job = read_json(path)
        report = select(job, root)
        report["jobPath"] = path.relative_to(root).as_posix()
        products.append(report)

    config = _profile_config(root)
    known_products = {item.get("productId") for item in products}
    assigned_products = set(config.get("productAssignments", {}))
    assignment_errors = [
        f"profile assignment has no job: {product_id}"
        for product_id in sorted(assigned_products - known_products)
    ]
    errors = assignment_errors + [
        f"{item['productId']}: {error}"
        for item in products
        for error in item.get("errors", [])
    ]
    return {
        "schemaVersion": 1,
        "passed": not errors,
        "productCount": len(products),
        "products": products,
        "errors": errors,
    }
