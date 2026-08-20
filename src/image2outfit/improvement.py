"""Evidence-bound self-improvement loop for image2outfit.

The loop composes existing QualitySpec defects, the tracked research registries,
controlled method experiments, measured adoption decisions, and append-only
product history. It does not own product completion state or a second quality
score.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import json
import os
import re
import subprocess

METHODS_PATH = Path("Assets/GenWorks/Shared/Research/2026-garment-methods.json")
OSS_PATH = Path("Assets/GenWorks/Shared/Research/2026-garment-oss.json")
QUALITY_REPORT = ".image2outfit/products/{product}/reports/customer-quality.json"
PLAN_PATH = ".image2outfit/products/{product}/reports/improvement-plan.json"
RESEARCH_REQUEST_PATH = ".image2outfit/products/{product}/reports/research-request.json"
EXPERIMENT_ROOT = Path(".image2outfit/experiments")

ASPECT_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "topology": ("topology-uv",),
    "seam": ("stitch-assembly",),
    "fit": ("structured-patterns", "runtime-deformation"),
    "material-response": ("pbr-texture",),
    "layering": ("layering-collision",),
    "skinning": ("runtime-deformation",),
    "collision": ("layering-collision",),
    "silhouette": ("structured-patterns",),
    "styling-fidelity": ("structured-patterns", "pbr-texture"),
    "evidence-completeness": ("dynamic-evaluation",),
}
TEXT_CAPABILITIES = (
    (("seam", "stitch", "縫"), "stitch-assembly"),
    (("topology", "uv", "normal", "mesh"), "topology-uv"),
    (("collision", "penetration", "intersection", "layer"), "layering-collision"),
    (("material", "roughness", "texture", "color", "pbr"), "pbr-texture"),
    (("skin", "weight", "deform", "pose"), "runtime-deformation"),
    (("dynamic", "temporal", "frame"), "dynamic-evaluation"),
    (("pattern", "silhouette", "fit", "ease", "dart"), "structured-patterns"),
)
OSS_CAPABILITIES = {
    "PARAMETRIC_SEWING_PATTERN": ("structured-patterns", "stitch-assembly"),
    "GARMENT_DRAPE_AND_COLLISION": ("layering-collision", "dynamic-evaluation"),
    "PBR_MATERIAL_AUTHORING": ("pbr-texture",),
    "IMAGE_OR_TEXT_TO_SEWING_PATTERN": ("structured-patterns",),
    "BODY_FIT_AND_ASSET_TRANSFER_REFERENCE": ("runtime-deformation",),
}
DECISION_PRIORITY = {
    "ADOPT_NOW": 0,
    "ADOPT_PRINCIPLE": 1,
    "PROTOTYPE": 2,
    "BENCHMARK": 3,
    "REFERENCE_ONLY": 4,
    "WATCH": 5,
    "WATCH_RELEASE": 5,
    "REJECT_FOR_CURRENT_PIPELINE": 9,
}


class ImprovementError(ValueError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ImprovementError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _finding_text(finding: Mapping[str, Any]) -> str:
    values = [
        finding.get(key)
        for key in ("code", "aspect", "message", "observedDefect", "subtype")
    ]
    reasons = finding.get("reasons")
    if isinstance(reasons, list):
        values.extend(reasons)
    return " ".join(str(value) for value in values if isinstance(value, str)).lower()


def capabilities_for_finding(
    finding: Mapping[str, Any],
    *,
    implemented_capabilities: Iterable[str] = (),
) -> dict[str, Any]:
    aspect = str(finding.get("aspect") or "").strip()
    capabilities = list(ASPECT_CAPABILITIES.get(aspect, ()))
    text = _finding_text(finding)
    for needles, capability in TEXT_CAPABILITIES:
        if any(needle in text for needle in needles):
            capabilities.append(capability)
    capabilities = list(dict.fromkeys(capabilities))
    implemented = set(implemented_capabilities)
    evidence = finding.get("evidence")
    evidence_hashes = (
        sorted(
            {
                str(item["sha256"])
                for item in evidence
                if isinstance(item, dict) and isinstance(item.get("sha256"), str)
            }
        )
        if isinstance(evidence, list)
        else []
    )
    return {
        "schemaVersion": 1,
        "status": "MAPPED" if capabilities else "UNRESOLVED",
        "findingDigest": digest_value(dict(finding)),
        "returnStage": finding.get("recommendedReturnStage"),
        "evidenceHashes": evidence_hashes,
        "candidates": [
            {
                "capabilityId": capability,
                "classification": (
                    "IMPLEMENTATION_DEFECT"
                    if capability in implemented
                    else "CAPABILITY_GAP"
                ),
                "reason": (
                    f"mapped from quality aspect {aspect!r}"
                    if aspect
                    else "mapped from defect evidence"
                ),
            }
            for capability in capabilities
        ],
    }


def load_research_index(root: Path) -> dict[str, Any]:
    methods = read_json(root / METHODS_PATH)
    oss = read_json(root / OSS_PATH)
    capabilities = {
        str(item["id"]): dict(item)
        for item in methods.get("capabilities", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    publications = {
        str(item["id"]): dict(item)
        for item in methods.get("publications", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    licenses = {
        str(item["publicationId"]): dict(item)
        for item in methods.get("licenseAssessments", [])
        if isinstance(item, dict) and isinstance(item.get("publicationId"), str)
    }
    by_capability: dict[str, list[dict[str, Any]]] = {
        capability: [] for capability in capabilities
    }
    for assessment in methods.get("methodAssessments", []):
        if not isinstance(assessment, dict):
            continue
        publication = publications.get(str(assessment.get("publicationId")))
        if not publication:
            continue
        license_info = licenses.get(str(assessment.get("publicationId")), {})
        candidate = {
            "candidateId": str(assessment.get("id")),
            "sourceType": "PUBLICATION",
            "canonicalName": publication.get("title"),
            "primaryUrl": publication.get("officialUrl"),
            "decision": assessment.get("decision"),
            "version": publication.get("year"),
            "license": license_info.get("declaredLicense"),
            "licenseStatus": (
                "VERIFIED"
                if license_info.get("declaredLicense") not in {None, "", "UNVERIFIED"}
                else "UNVERIFIED"
            ),
            "implementationImplications": assessment.get(
                "implementationImplications", []
            ),
            "rejectionCriteria": assessment.get("rejectionCriteria", []),
            "experimentBinding": assessment.get("experimentBinding"),
        }
        for capability in assessment.get("capabilityIds", []):
            if capability in by_capability:
                by_capability[capability].append(dict(candidate))
    for item in oss.get("implementationCandidates", []):
        if not isinstance(item, dict):
            continue
        for capability in OSS_CAPABILITIES.get(str(item.get("category")), ()):
            if capability not in by_capability:
                continue
            by_capability[capability].append(
                {
                    "candidateId": str(item.get("id")),
                    "sourceType": "OSS",
                    "canonicalName": item.get("name"),
                    "primaryUrl": item.get("officialUrl"),
                    "decision": item.get("decision"),
                    "version": item.get("version"),
                    "license": item.get("codeLicense"),
                    "licenseStatus": (
                        "VERIFIED" if item.get("codeLicense") else "UNVERIFIED"
                    ),
                    "requirements": item.get("requirements", {}),
                    "integrationBoundary": item.get("integrationBoundary"),
                    "experimentBinding": item.get("experimentBinding"),
                }
            )
    for rows in by_capability.values():
        rows.sort(
            key=lambda row: (
                DECISION_PRIORITY.get(str(row.get("decision")), 8),
                0 if row.get("sourceType") == "OSS" else 1,
                str(row.get("candidateId")),
            )
        )
    return {
        "schemaVersion": 1,
        "capabilities": capabilities,
        "byCapability": by_capability,
    }


def candidate_method_key(candidate: Mapping[str, Any]) -> str:
    return digest_value(
        [
            candidate.get("candidateId"),
            candidate.get("version"),
            candidate.get("commit"),
            candidate.get("parameters"),
        ]
    )


def existing_candidates(
    index: Mapping[str, Any],
    capability_id: str,
    *,
    rejected_method_keys: Iterable[str] = (),
) -> list[dict[str, Any]]:
    rejected = set(rejected_method_keys)
    rows = index.get("byCapability", {}).get(capability_id, [])
    return [
        dict(row)
        for row in rows
        if isinstance(row, dict)
        and str(row.get("decision"))
        not in {"WATCH", "WATCH_RELEASE", "REJECT_FOR_CURRENT_PIPELINE"}
        and candidate_method_key(row) not in rejected
        and isinstance(row.get("primaryUrl"), str)
        and str(row["primaryUrl"]).startswith("https://")
    ]


def make_research_request(
    *,
    product_id: str,
    candidate_hash: str,
    finding: Mapping[str, Any],
    capability_id: str,
    current_method: Mapping[str, Any] | None = None,
    attempted_methods: Sequence[Mapping[str, Any]] = (),
    constraints: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    request = {
        "schemaVersion": 1,
        "productId": product_id,
        "candidateHash": candidate_hash,
        "defect": {
            "code": finding.get("code"),
            "aspect": finding.get("aspect"),
            "observedFailure": (
                finding.get("observedDefect")
                or finding.get("message")
                or finding.get("reasons")
            ),
            "view": finding.get("view"),
            "pose": finding.get("pose"),
        },
        "missingCapability": capability_id,
        "currentMethod": dict(current_method or {}),
        "attemptedMethods": [dict(item) for item in attempted_methods],
        "constraints": dict(constraints or {}),
        "sourcePriority": [
            "OFFICIAL_DOCUMENTATION",
            "PEER_REVIEWED_PUBLICATION",
            "PRIMARY_PREPRINT",
            "UPSTREAM_REPOSITORY_RELEASE",
            "UPSTREAM_ISSUE_OR_DISCUSSION",
        ],
        "searchTerms": [
            capability_id,
            str(finding.get("code") or ""),
            str(finding.get("aspect") or ""),
        ],
        "createdAt": utc_now(),
    }
    request["requestDigest"] = digest_value(request)
    return request


def validate_research_result(value: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if value.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")
    if not isinstance(value.get("requestDigest"), str):
        errors.append("requestDigest is required")
    candidates = value.get("candidates")
    if not isinstance(candidates, list):
        errors.append("candidates must be a list")
        candidates = []
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(candidates):
        if not isinstance(item, dict):
            errors.append(f"candidates[{index}]")
            continue
        name = item.get("canonicalName")
        urls = item.get("primaryUrls")
        checked = item.get("checkedAt")
        if not isinstance(name, str) or not name:
            errors.append(f"candidates[{index}].canonicalName")
            continue
        if (
            not isinstance(urls, list)
            or not urls
            or not all(
                isinstance(url, str) and url.startswith("https://") for url in urls
            )
        ):
            errors.append(f"candidates[{index}].primaryUrls")
        if not isinstance(checked, str) or not checked:
            errors.append(f"candidates[{index}].checkedAt")
        identity = canonical_json(
            [name, item.get("repository"), item.get("release"), item.get("commit")]
        )
        if identity in seen:
            continue
        seen.add(identity)
        license_status = str(item.get("licenseStatus") or "UNVERIFIED")
        normalized.append(
            {
                **item,
                "licenseStatus": license_status,
                "verified": (
                    bool(urls) and bool(checked) and license_status != "UNVERIFIED"
                ),
            }
        )
    return {
        "schemaVersion": 1,
        "passed": not errors,
        "errors": errors,
        "requestDigest": value.get("requestDigest"),
        "candidates": normalized,
    }


def validate_experiment_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if value.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")
    for field in ("productId", "fixtureId", "capability", "inputCandidateHash"):
        if not isinstance(value.get(field), str) or not value.get(field):
            errors.append(f"{field} is required")
    methods = value.get("methods")
    if not isinstance(methods, list) or len(methods) < 2:
        errors.append("methods must contain baseline and at least one candidate")
        methods = []
    ids: list[str] = []
    baseline_count = 0
    for index, method in enumerate(methods):
        if not isinstance(method, dict):
            errors.append(f"methods[{index}]")
            continue
        method_id = method.get("id")
        if not isinstance(method_id, str) or not re.fullmatch(
            r"[A-Za-z0-9._-]+", method_id
        ):
            errors.append(f"methods[{index}].id")
            continue
        ids.append(method_id)
        baseline_count += method.get("role") == "baseline"
        command = method.get("command")
        if command is not None and (
            not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) and part for part in command)
        ):
            errors.append(f"methods[{index}].command")
        if command and not isinstance(method.get("resultPath"), str):
            errors.append(f"methods[{index}].resultPath")
    if len(ids) != len(set(ids)):
        errors.append("method ids must be unique")
    if baseline_count != 1:
        errors.append("exactly one baseline method is required")
    evaluation = value.get("evaluation")
    if not isinstance(evaluation, dict):
        errors.append("evaluation is required")
    else:
        if not isinstance(evaluation.get("views"), list):
            errors.append("evaluation.views")
        if not isinstance(evaluation.get("poses"), list):
            errors.append("evaluation.poses")
        if not isinstance(evaluation.get("qualitySpec"), str):
            errors.append("evaluation.qualitySpec")
    return {
        "schemaVersion": 1,
        "passed": not errors,
        "errors": errors,
        "methodIds": ids,
    }


def experiment_matrix(value: Mapping[str, Any]) -> list[str]:
    validation = validate_experiment_manifest(value)
    if not validation["passed"]:
        raise ImprovementError("; ".join(validation["errors"]))
    return list(validation["methodIds"])


def _experiment_dir(root: Path, manifest: Mapping[str, Any]) -> Path:
    digest = str(manifest.get("manifestDigest") or digest_value(dict(manifest)))[:16]
    return root / EXPERIMENT_ROOT / digest


def run_experiment_method(
    root: Path,
    manifest: Mapping[str, Any],
    method_id: str,
) -> dict[str, Any]:
    validation = validate_experiment_manifest(manifest)
    if not validation["passed"]:
        raise ImprovementError("; ".join(validation["errors"]))
    method = next(
        (
            item
            for item in manifest["methods"]
            if isinstance(item, dict) and item.get("id") == method_id
        ),
        None,
    )
    if method is None:
        raise ImprovementError(f"unknown method {method_id}")
    output_dir = _experiment_dir(root, manifest)
    output_dir.mkdir(parents=True, exist_ok=True)
    record_path = output_dir / f"{method_id}.json"
    manifest_digest = str(
        manifest.get("manifestDigest") or digest_value(dict(manifest))
    )
    command = method.get("command")
    if not command:
        record = {
            "schemaVersion": 1,
            "manifestDigest": manifest_digest,
            "methodId": method_id,
            "role": method.get("role"),
            "status": "UNBOUND",
            "finishedAt": utc_now(),
        }
        write_json(record_path, record)
        return record
    env = os.environ.copy()
    env.update(
        {
            "IMAGE2OUTFIT_EXPERIMENT_METHOD": method_id,
            "IMAGE2OUTFIT_EXPERIMENT_PRODUCT": str(manifest["productId"]),
            "IMAGE2OUTFIT_EXPERIMENT_FIXTURE": str(manifest["fixtureId"]),
        }
    )
    timeout = manifest.get("resourceConstraints", {}).get("timeoutSeconds", 3600)
    timeout = timeout if isinstance(timeout, int) and timeout > 0 else 3600
    started = utc_now()
    try:
        completed = subprocess.run(
            list(command),
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        return_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        return_code = None
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        timed_out = True
    declared = root / str(method.get("resultPath"))
    result: dict[str, Any] = {}
    result_error: str | None = None
    if not timed_out and return_code == 0:
        try:
            result = read_json(declared)
        except (OSError, json.JSONDecodeError, ImprovementError) as exc:
            result_error = str(exc)
    status = (
        "PASS"
        if return_code == 0 and not timed_out and result.get("status") == "PASS"
        else "FAIL"
    )
    record = {
        "schemaVersion": 1,
        "manifestDigest": manifest_digest,
        "methodId": method_id,
        "role": method.get("role"),
        "status": status,
        "startedAt": started,
        "finishedAt": utc_now(),
        "returnCode": return_code,
        "timedOut": timed_out,
        "command": list(command),
        "resultPath": str(method.get("resultPath")),
        "resultSha256": sha256_file(declared) if declared.is_file() else None,
        "result": result,
        "resultError": result_error,
        "stdout": str(stdout)[-12000:],
        "stderr": str(stderr)[-12000:],
    }
    write_json(record_path, record)
    return record


def aggregate_experiment_results(
    root: Path,
    manifest: Mapping[str, Any],
    *,
    result_dir: Path | None = None,
) -> dict[str, Any]:
    method_ids = experiment_matrix(manifest)
    result_dir = result_dir or _experiment_dir(root, manifest)
    rows: list[dict[str, Any]] = []
    for method_id in method_ids:
        paths = sorted(result_dir.rglob(f"{method_id}.json"))
        rows.append(
            read_json(paths[0])
            if paths
            else {"methodId": method_id, "status": "MISSING"}
        )
    roles = {
        str(item.get("id")): item.get("role")
        for item in manifest["methods"]
        if isinstance(item, dict)
    }
    summary = {
        "schemaVersion": 1,
        "manifestDigest": manifest.get("manifestDigest")
        or digest_value(dict(manifest)),
        "productId": manifest.get("productId"),
        "capability": manifest.get("capability"),
        "baseline": next(
            (row for row in rows if roles.get(str(row.get("methodId"))) == "baseline"),
            None,
        ),
        "methods": rows,
        "allRecorded": all(row.get("status") != "MISSING" for row in rows),
        "finishedAt": utc_now(),
    }
    summary["summaryDigest"] = digest_value(summary)
    write_json(_experiment_dir(root, manifest) / "summary.json", summary)
    return summary


def make_adoption_decision(
    *,
    capability_id: str,
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    comparison: Mapping[str, Any],
    license_status: str,
    integration_point: str | None,
) -> dict[str, Any]:
    candidate_passed = candidate.get("status") == "PASS"
    eligible = comparison.get("eligibleForAdoption") is True
    reproducible = comparison.get("reproducible") is True
    regressions = comparison.get("regressions", [])
    license_ok = license_status not in {"", "UNVERIFIED", "UNASSESSED"}
    if (
        candidate_passed
        and eligible
        and reproducible
        and not regressions
        and license_ok
        and integration_point
    ):
        decision = "ADOPT"
    elif candidate_passed and not eligible:
        decision = "KEEP_BENCHMARK"
    else:
        decision = "REJECT"
    record = {
        "schemaVersion": 1,
        "capability": capability_id,
        "baselineMethod": baseline.get("methodId"),
        "candidateMethod": candidate.get("methodId"),
        "experimentManifestDigest": candidate.get("manifestDigest"),
        "comparison": dict(comparison),
        "licenseStatus": license_status,
        "productionIntegrationPoint": integration_point,
        "decision": decision,
        "decidedAt": utc_now(),
    }
    record["decisionDigest"] = digest_value(record)
    return record


def improvement_history_dir(root: Path, product_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", product_id):
        raise ImprovementError("invalid product id")
    return root / "Assets" / "GenWorks" / product_id / "Research" / "Improvement"


def load_iteration_records(root: Path, product_id: str) -> list[dict[str, Any]]:
    directory = improvement_history_dir(root, product_id)
    if not directory.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            value = read_json(path)
        except (OSError, json.JSONDecodeError, ImprovementError):
            continue
        if (
            value.get("schemaVersion") == 1
            and value.get("productId") == product_id
            and isinstance(value.get("recordDigest"), str)
        ):
            value["_path"] = path.relative_to(root).as_posix()
            records.append(value)
    return records


def prior_method_evidence(
    records: Sequence[Mapping[str, Any]],
    *,
    capability_id: str,
    defect_class: str | None = None,
    part: str | None = None,
    pose: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    adopted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for record in records:
        if record.get("missingCapability") != capability_id:
            continue
        context = (
            record.get("context") if isinstance(record.get("context"), dict) else {}
        )
        if defect_class and context.get("defectClass") not in {None, defect_class}:
            continue
        if part and context.get("part") not in {None, part}:
            continue
        if pose and context.get("pose") not in {None, pose}:
            continue
        methods = record.get("methodsTried")
        if not isinstance(methods, list):
            continue
        target = adopted if record.get("decision") == "ADOPT" else rejected
        target.extend(dict(item) for item in methods if isinstance(item, dict))
    return {"adopted": adopted, "rejected": rejected}


def append_iteration_record(
    root: Path,
    product_id: str,
    value: Mapping[str, Any],
) -> Path:
    record = {"schemaVersion": 1, "productId": product_id, **dict(value)}
    record.setdefault("recordedAt", utc_now())
    record["recordDigest"] = digest_value(record)
    directory = improvement_history_dir(root, product_id)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = re.sub(r"[^0-9]", "", str(record["recordedAt"]))[:14] or "record"
    path = directory / f"{stamp}-{record['recordDigest'][:12]}.json"
    if path.exists():
        raise ImprovementError(f"iteration record already exists: {path}")
    write_json(path, record)
    return path


def quality_findings(
    root: Path,
    product_id: str,
) -> tuple[str, list[dict[str, Any]]]:
    document = read_json(root / QUALITY_REPORT.format(product=product_id))
    evidence = document.get("evidence")
    quality = evidence.get("qualitySpec") if isinstance(evidence, dict) else None
    if not isinstance(quality, dict):
        raise ImprovementError("customer-quality.json lacks evidence.qualitySpec")
    candidate_hash = str(
        document.get("candidateManifestSha256")
        or quality.get("candidateManifestSha256")
        or ""
    )
    defects = quality.get("defects")
    return (
        candidate_hash,
        [dict(item) for item in defects if isinstance(item, dict)]
        if isinstance(defects, list)
        else [],
    )


def plan_improvement(
    root: Path,
    product_id: str,
    *,
    implemented_capabilities: Iterable[str] = (),
) -> dict[str, Any]:
    candidate_hash, findings = quality_findings(root, product_id)
    if not findings:
        plan = {
            "schemaVersion": 1,
            "productId": product_id,
            "candidateHash": candidate_hash,
            "status": "NO_DEFECT",
            "nextAction": "NONE",
            "createdAt": utc_now(),
        }
        plan["planDigest"] = digest_value(plan)
        return plan
    finding = findings[0]
    mapping = capabilities_for_finding(
        finding,
        implemented_capabilities=implemented_capabilities,
    )
    if not mapping["candidates"]:
        plan = {
            "schemaVersion": 1,
            "productId": product_id,
            "candidateHash": candidate_hash,
            "status": "UNRESOLVED",
            "finding": finding,
            "capabilityMapping": mapping,
            "nextAction": "RESEARCH_REQUIRED",
            "createdAt": utc_now(),
        }
        plan["planDigest"] = digest_value(plan)
        return plan
    capability_id = mapping["candidates"][0]["capabilityId"]
    history = load_iteration_records(root, product_id)
    context = {
        "defectClass": finding.get("aspect"),
        "part": finding.get("affectedPart"),
        "pose": finding.get("pose"),
    }
    prior = prior_method_evidence(
        history,
        capability_id=capability_id,
        defect_class=context["defectClass"],
        part=context["part"],
        pose=context["pose"],
    )
    if prior["adopted"]:
        candidates = prior["adopted"]
        selected = prior["adopted"][0]
        action = "REUSE_MEASURED_METHOD"
        request = None
    else:
        rejected = {candidate_method_key(item) for item in prior["rejected"]}
        candidates = existing_candidates(
            load_research_index(root),
            capability_id,
            rejected_method_keys=rejected,
        )
        if candidates:
            selected = candidates[0]
            action = (
                "RUN_EXPERIMENT"
                if selected.get("experimentBinding")
                else "IMPLEMENT_EXPERIMENT_BINDING"
            )
            request = None
        else:
            selected = None
            action = "RESEARCH_REQUIRED"
            request = make_research_request(
                product_id=product_id,
                candidate_hash=candidate_hash,
                finding=finding,
                capability_id=capability_id,
                attempted_methods=prior["rejected"],
            )
    plan = {
        "schemaVersion": 1,
        "productId": product_id,
        "candidateHash": candidate_hash,
        "status": "ACTIONABLE",
        "finding": finding,
        "capabilityMapping": mapping,
        "missingCapability": capability_id,
        "historyMatch": prior,
        "candidateMethods": candidates,
        "selectedMethod": selected,
        "researchRequest": request,
        "nextAction": action,
        "createdAt": utc_now(),
    }
    plan["planDigest"] = digest_value(plan)
    return plan


def persist_plan(
    root: Path,
    product_id: str,
    plan: Mapping[str, Any],
) -> Path:
    path = root / PLAN_PATH.format(product=product_id)
    write_json(path, plan)
    write_json(
        improvement_history_dir(root, product_id) / "latest-plan.json",
        plan,
    )
    if isinstance(plan.get("researchRequest"), dict):
        write_json(
            root / RESEARCH_REQUEST_PATH.format(product=product_id),
            plan["researchRequest"],
        )
    return path


def review_projection(root: Path, product_id: str) -> dict[str, Any]:
    local = root / PLAN_PATH.format(product=product_id)
    tracked = improvement_history_dir(root, product_id) / "latest-plan.json"
    visible = local if local.is_file() else tracked if tracked.is_file() else None
    plan = read_json(visible) if visible else {}
    history = load_iteration_records(root, product_id)
    latest = history[-1] if history else {}
    return {
        "status": plan.get("status", "NOT_RUN"),
        "nextAction": plan.get("nextAction", "NOT_RUN"),
        "missingCapability": plan.get("missingCapability"),
        "selectedMethod": (
            plan.get("selectedMethod", {}).get("candidateId")
            if isinstance(plan.get("selectedMethod"), dict)
            else None
        ),
        "lastDecision": latest.get("decision"),
        "lastRecord": latest.get("_path"),
        "iterationCount": len(history),
        "planPath": visible.relative_to(root).as_posix() if visible else None,
    }
