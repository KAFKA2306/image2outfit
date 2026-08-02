#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = (
    ROOT
    / "Assets"
    / "GenWorks"
    / "Shared"
    / "Research"
    / "2026-garment-methods.json"
)


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def audit(root: Path = ROOT, *, now: datetime | None = None) -> dict[str, Any]:
    root = root.resolve()
    path = (
        root
        / "Assets"
        / "GenWorks"
        / "Shared"
        / "Research"
        / "2026-garment-methods.json"
    )
    errors: list[str] = []
    warnings: list[str] = []
    try:
        baseline = _read(path)
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "schemaVersion": 1,
            "passed": False,
            "path": path.relative_to(root).as_posix(),
            "errors": [f"research baseline unreadable: {exc}"],
            "warnings": [],
        }

    if baseline.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")
    if baseline.get("surveyYear") != 2026:
        errors.append("surveyYear must be 2026")
    if not isinstance(baseline.get("baselineId"), str) or not baseline["baselineId"]:
        errors.append("baselineId is required")

    checked_at = _utc(baseline.get("reviewedAt"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    freshness_days = baseline.get("freshnessDays")
    if checked_at is None:
        errors.append("reviewedAt must be an ISO-8601 timestamp with timezone")
    elif checked_at > current:
        errors.append("reviewedAt cannot be in the future")
    if not isinstance(freshness_days, int) or freshness_days <= 0:
        errors.append("freshnessDays must be a positive integer")
    elif checked_at is not None and (current - checked_at).days > freshness_days:
        errors.append(
            f"research survey is stale: {(current - checked_at).days} days old, limit {freshness_days}"
        )

    hosts = baseline.get("officialSourceHosts")
    if not isinstance(hosts, list) or not hosts or not all(
        isinstance(value, str) and value for value in hosts
    ):
        errors.append("officialSourceHosts must be a non-empty string list")
        allowed_hosts: set[str] = set()
    else:
        allowed_hosts = set(hosts)

    required = baseline.get("requiredCapabilities")
    if not isinstance(required, list) or not required or not all(
        isinstance(value, str) and value for value in required
    ):
        errors.append("requiredCapabilities must be a non-empty string list")
        required_capabilities: set[str] = set()
    else:
        required_capabilities = set(required)
        if len(required_capabilities) != len(required):
            errors.append("requiredCapabilities contains duplicates")

    methods = baseline.get("methods")
    if not isinstance(methods, list) or not methods:
        errors.append("methods must be a non-empty list")
        methods = []

    ids: set[str] = set()
    covered: set[str] = set()
    production_tracks = {"ADOPT_PRINCIPLE", "PROTOTYPE", "BENCHMARK"}
    valid_tracks = production_tracks | {"WATCH"}
    valid_statuses = {"PEER_REVIEWED", "PREPRINT"}

    for index, method in enumerate(methods):
        prefix = f"methods[{index}]"
        if not isinstance(method, dict):
            errors.append(prefix)
            continue
        method_id = method.get("id")
        if not isinstance(method_id, str) or not method_id:
            errors.append(f"{prefix}.id")
        elif method_id in ids:
            errors.append(f"duplicate method id: {method_id}")
        else:
            ids.add(method_id)
        for field in ("title", "venue", "evidence"):
            if not isinstance(method.get(field), str) or not method[field].strip():
                errors.append(f"{prefix}.{field}")
        if method.get("year") != 2026:
            errors.append(f"{prefix}.year must be 2026")
        if method.get("publicationStatus") not in valid_statuses:
            errors.append(f"{prefix}.publicationStatus")
        track = method.get("implementationTrack")
        if track not in valid_tracks:
            errors.append(f"{prefix}.implementationTrack")

        url = method.get("officialUrl")
        if not isinstance(url, str):
            errors.append(f"{prefix}.officialUrl")
        else:
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
                errors.append(f"{prefix}.officialUrl must use an approved primary-source host")

        capabilities = method.get("capabilities")
        if not isinstance(capabilities, list) or not capabilities:
            errors.append(f"{prefix}.capabilities")
        else:
            unknown = set(capabilities) - required_capabilities
            if unknown:
                errors.append(f"{prefix}.unknownCapabilities: {sorted(unknown)}")
            if track in production_tracks:
                covered.update(capabilities)

        for field in ("implementationImplications", "rejectionCriteria"):
            values = method.get(field)
            if not isinstance(values, list) or not values or not all(
                isinstance(value, str) and value.strip() for value in values
            ):
                errors.append(f"{prefix}.{field}")

        code_reuse = method.get("codeReuseAllowed")
        code_license = method.get("codeLicense")
        if code_reuse is True:
            if not isinstance(code_license, str) or code_license in {"", "UNVERIFIED"}:
                errors.append(f"{prefix}.codeLicense must be verified before reuse")
            if not isinstance(method.get("codeUrl"), str):
                errors.append(f"{prefix}.codeUrl is required when code reuse is allowed")
        elif code_reuse is not False:
            errors.append(f"{prefix}.codeReuseAllowed must be boolean")
        elif code_license != "UNVERIFIED":
            warnings.append(
                f"{prefix}: code reuse is disabled despite a non-default license value"
            )

    missing_coverage = required_capabilities - covered
    if missing_coverage:
        errors.append(
            "required capabilities lack an implementation or mandatory benchmark track: "
            + ", ".join(sorted(missing_coverage))
        )

    requirements = baseline.get("productionRequirements")
    if not isinstance(requirements, dict):
        errors.append("productionRequirements must be an object")
    else:
        if set(requirements) != required_capabilities:
            errors.append(
                "productionRequirements keys must exactly match requiredCapabilities"
            )
        for capability, rules in requirements.items():
            if not isinstance(rules, list) or not rules or not all(
                isinstance(rule, str) and rule.strip() for rule in rules
            ):
                errors.append(f"productionRequirements.{capability}")

    reuse = baseline.get("reusePolicy")
    if not isinstance(reuse, dict):
        errors.append("reusePolicy must be an object")
    else:
        if reuse.get("paperIdeasMayBeReimplemented") is not True:
            errors.append("reusePolicy.paperIdeasMayBeReimplemented must be true")
        if reuse.get("paperCodeOrModelsMayBeCopiedWithoutVerifiedLicense") is not False:
            errors.append(
                "reusePolicy.paperCodeOrModelsMayBeCopiedWithoutVerifiedLicense must be false"
            )
        if reuse.get("commercialReleaseRequiresIndependentLicenseReview") is not True:
            errors.append(
                "reusePolicy.commercialReleaseRequiresIndependentLicenseReview must be true"
            )

    return {
        "schemaVersion": 1,
        "passed": not errors,
        "path": path.relative_to(root).as_posix(),
        "baselineId": baseline.get("baselineId"),
        "surveyYear": baseline.get("surveyYear"),
        "reviewedAt": baseline.get("reviewedAt"),
        "methodCount": len(methods),
        "requiredCapabilities": sorted(required_capabilities),
        "productionCoverage": sorted(covered),
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    result = audit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
