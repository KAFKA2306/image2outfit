#!/usr/bin/env python3
"""Advance the evidence-bound improvement loop as far as evidence permits.

The reusable :mod:`image2outfit.improvement` module owns capability mapping,
research validation, experiment records, adoption rules, and iteration history.
This tool-side module owns resumable orchestration and external process calls.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from image2outfit import improvement

RESEARCH_RESULT = "research-result.json"
EXPERIMENT_BINDING = "experiment-binding.json"
EXPERIMENT_MANIFEST = "experiment-manifest.json"
EXPERIMENT_SUMMARY = "experiment-summary.json"
EXPERIMENT_COMPARISON = "experiment-comparison.json"
ADOPTION_DECISION = "adoption-decision.json"
INTEGRATION_RECORD = "production-integration.json"

WAITING = {
    "WAITING_FOR_EXTERNAL_RESEARCH",
    "WAITING_FOR_EXPERIMENT_BINDING",
    "WAITING_FOR_COMPARISON",
    "WAITING_FOR_PRODUCTION_INTEGRATION",
    "WAITING_FOR_REEVALUATION",
}


class LoopError(ValueError):
    pass


def reports_dir(root: Path, product_id: str) -> Path:
    if not product_id or any(part in product_id for part in ("/", "\\", "..")):
        raise LoopError("invalid product id")
    return root / ".image2outfit" / "products" / product_id / "reports"


def _optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return improvement.read_json(path)


def _persist(
    root: Path,
    product_id: str,
    name: str,
    value: Mapping[str, Any],
) -> Path:
    path = reports_dir(root, product_id) / name
    improvement.write_json(path, value)
    return path


def _relative(root: Path, path: Path | None) -> str | None:
    return path.relative_to(root).as_posix() if path is not None else None


def _stored_plan(root: Path, product_id: str) -> dict[str, Any] | None:
    return _optional_json(root / improvement.PLAN_PATH.format(product=product_id))


def _finding_digest(plan: Mapping[str, Any]) -> str | None:
    mapping = plan.get("capabilityMapping")
    if isinstance(mapping, dict) and isinstance(mapping.get("findingDigest"), str):
        return mapping["findingDigest"]
    finding = plan.get("finding")
    if isinstance(finding, dict):
        return improvement.digest_value(finding)
    return None


def _same_context(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return (
        left.get("candidateHash") == right.get("candidateHash")
        and _finding_digest(left) == _finding_digest(right)
    )


def _base_plan(root: Path, product_id: str) -> dict[str, Any]:
    fresh = improvement.plan_improvement(root, product_id)
    stored = _stored_plan(root, product_id)
    if stored and _same_context(stored, fresh) and stored.get("nextAction") in WAITING:
        return stored
    improvement.persist_plan(root, product_id, fresh)
    return fresh


def _waiting(
    root: Path,
    product_id: str,
    plan: dict[str, Any],
    action: str,
    *,
    reason: str,
    required_artifact: Path | None = None,
) -> dict[str, Any]:
    plan = {
        **plan,
        "status": "WAITING",
        "nextAction": action,
        "waitingReason": reason,
        "requiredArtifact": _relative(root, required_artifact),
        "updatedAt": improvement.utc_now(),
    }
    plan["planDigest"] = improvement.digest_value(
        {key: value for key, value in plan.items() if key != "planDigest"}
    )
    improvement.persist_plan(root, product_id, plan)
    return {
        "status": action,
        "productId": product_id,
        "candidateHash": plan.get("candidateHash"),
        "missingCapability": plan.get("missingCapability"),
        "selectedMethod": plan.get("selectedMethod"),
        "reason": reason,
        "requiredArtifact": plan.get("requiredArtifact"),
        "resumeCommand": f"python tools/manage.py improve --product {product_id}",
        "plan": plan,
    }


def _research_request(plan: dict[str, Any]) -> dict[str, Any]:
    request = plan.get("researchRequest")
    if isinstance(request, dict):
        return dict(request)
    finding = plan.get("finding") if isinstance(plan.get("finding"), dict) else {}
    return improvement.make_research_request(
        product_id=str(plan.get("productId") or ""),
        candidate_hash=str(plan.get("candidateHash") or ""),
        finding=finding,
        capability_id=str(plan.get("missingCapability") or "unresolved"),
    )


def _research_candidate(item: Mapping[str, Any]) -> dict[str, Any]:
    urls = item.get("primaryUrls")
    primary_url = urls[0] if isinstance(urls, list) and urls else None
    identity = improvement.digest_value(
        [
            item.get("canonicalName"),
            item.get("repository"),
            item.get("release"),
            item.get("commit"),
        ]
    )[:16]
    return {
        "candidateId": str(item.get("candidateId") or f"research:{identity}"),
        "sourceType": str(item.get("sourceType") or "EXTERNAL_RESEARCH"),
        "canonicalName": item.get("canonicalName"),
        "primaryUrl": primary_url,
        "primaryUrls": list(urls) if isinstance(urls, list) else [],
        "version": item.get("release") or item.get("version"),
        "commit": item.get("commit"),
        "license": item.get("license"),
        "licenseStatus": item.get("licenseStatus"),
        "compatibilityFacts": item.get("compatibilityFacts", []),
        "unresolvedFacts": item.get("unresolvedFacts", []),
        "experimentBinding": item.get("experimentBinding"),
        "productionIntegrationPoint": item.get("productionIntegrationPoint"),
    }


def _consume_research(
    root: Path,
    product_id: str,
    plan: dict[str, Any],
) -> dict[str, Any]:
    request = _research_request(plan)
    plan = {**plan, "researchRequest": request}
    improvement.persist_plan(root, product_id, plan)
    result_path = reports_dir(root, product_id) / RESEARCH_RESULT
    value = _optional_json(result_path)
    if value is None:
        return _waiting(
            root,
            product_id,
            plan,
            "WAITING_FOR_EXTERNAL_RESEARCH",
            reason=(
                "No ResearchResult matching the current concrete failure is available yet."
            ),
            required_artifact=result_path,
        )
    validated = improvement.validate_research_result(value)
    if validated.get("requestDigest") != request.get("requestDigest"):
        raise LoopError(
            "research-result requestDigest does not match current ResearchRequest"
        )
    if validated.get("passed") is not True:
        raise LoopError(
            "invalid research-result: " + "; ".join(validated.get("errors", []))
        )
    candidates = [
        _research_candidate(item)
        for item in validated.get("candidates", [])
        if isinstance(item, dict) and item.get("verified") is True
    ]
    if not candidates:
        return _waiting(
            root,
            product_id,
            plan,
            "WAITING_FOR_EXTERNAL_RESEARCH",
            reason=(
                "ResearchResult contains no verified candidate with primary evidence "
                "and verified license status."
            ),
            required_artifact=result_path,
        )
    selected = candidates[0]
    plan = {
        **plan,
        "status": "ACTIONABLE",
        "candidateMethods": candidates,
        "selectedMethod": selected,
        "nextAction": (
            "RUN_EXPERIMENT"
            if isinstance(selected.get("experimentBinding"), dict)
            else "IMPLEMENT_EXPERIMENT_BINDING"
        ),
        "researchResultPath": _relative(root, result_path),
        "updatedAt": improvement.utc_now(),
    }
    plan["planDigest"] = improvement.digest_value(
        {key: value for key, value in plan.items() if key != "planDigest"}
    )
    improvement.persist_plan(root, product_id, plan)
    return plan


def _binding_for_plan(
    root: Path,
    product_id: str,
    plan: Mapping[str, Any],
) -> dict[str, Any] | None:
    selected = (
        plan.get("selectedMethod")
        if isinstance(plan.get("selectedMethod"), dict)
        else {}
    )
    embedded = selected.get("experimentBinding")
    merged = dict(embedded) if isinstance(embedded, dict) else {}
    path = reports_dir(root, product_id) / EXPERIMENT_BINDING
    external = _optional_json(path)
    if external is not None:
        expected = selected.get("candidateId")
        if expected and external.get("candidateId") not in {None, expected}:
            raise LoopError(
                "experiment-binding candidateId does not match selected method"
            )
        capability = plan.get("missingCapability")
        if capability and external.get("capability") not in {None, capability}:
            raise LoopError(
                "experiment-binding capability does not match current missing capability"
            )
        merged.update(external)
    return merged or None


def _normalize_method(method: Mapping[str, Any], role: str) -> dict[str, Any]:
    value = dict(method)
    value["role"] = role
    if not isinstance(value.get("id"), str) or not value["id"]:
        value["id"] = role
    return value


def _selected_method_key(plan: Mapping[str, Any]) -> str:
    selected = (
        plan.get("selectedMethod")
        if isinstance(plan.get("selectedMethod"), dict)
        else {}
    )
    return improvement.candidate_method_key(selected)


def build_experiment_manifest(
    product_id: str,
    plan: Mapping[str, Any],
    binding: Mapping[str, Any],
) -> dict[str, Any]:
    supplied = binding.get("manifest")
    if isinstance(supplied, dict):
        manifest = dict(supplied)
        manifest.setdefault("schemaVersion", 1)
        manifest["productId"] = product_id
        manifest.setdefault("fixtureId", f"{product_id}:{plan.get('candidateHash')}")
        manifest["capability"] = str(plan.get("missingCapability") or "unresolved")
        manifest["inputCandidateHash"] = str(plan.get("candidateHash") or "")
    else:
        baseline = binding.get("baseline")
        candidate = binding.get("candidate")
        if not isinstance(baseline, dict) or not isinstance(candidate, dict):
            raise LoopError(
                "experiment binding requires baseline and candidate method objects"
            )
        evaluation = binding.get("evaluation")
        if not isinstance(evaluation, dict):
            evaluation = {
                "views": [],
                "poses": [],
                "qualitySpec": "quality-spec.v1",
            }
        manifest = {
            "schemaVersion": 1,
            "productId": product_id,
            "fixtureId": str(
                binding.get("fixtureId")
                or f"{product_id}:{plan.get('candidateHash')}"
            ),
            "capability": str(plan.get("missingCapability") or "unresolved"),
            "inputCandidateHash": str(plan.get("candidateHash") or ""),
            "evaluation": dict(evaluation),
            "methods": [
                _normalize_method(baseline, "baseline"),
                _normalize_method(candidate, "candidate"),
            ],
        }
        if isinstance(binding.get("resourceConstraints"), dict):
            manifest["resourceConstraints"] = dict(binding["resourceConstraints"])
    selected = (
        plan.get("selectedMethod")
        if isinstance(plan.get("selectedMethod"), dict)
        else {}
    )
    manifest["selectedMethodId"] = selected.get("candidateId")
    manifest["selectedMethodKey"] = _selected_method_key(plan)
    validation = improvement.validate_experiment_manifest(manifest)
    if validation.get("passed") is not True:
        raise LoopError(
            "invalid experiment manifest: "
            + "; ".join(validation.get("errors", []))
        )
    manifest["manifestDigest"] = improvement.digest_value(
        {key: value for key, value in manifest.items() if key != "manifestDigest"}
    )
    return manifest


def _method_by_role(
    summary: Mapping[str, Any],
    role: str,
    manifest: Mapping[str, Any],
) -> dict[str, Any] | None:
    roles = {
        str(item.get("id")): item.get("role")
        for item in manifest.get("methods", [])
        if isinstance(item, dict)
    }
    for row in summary.get("methods", []):
        if isinstance(row, dict) and roles.get(str(row.get("methodId"))) == role:
            return dict(row)
    return None


def _comparison_from_candidate(
    candidate: Mapping[str, Any],
) -> dict[str, Any] | None:
    result = candidate.get("result")
    if not isinstance(result, dict):
        return None
    comparison = result.get("comparison")
    return dict(comparison) if isinstance(comparison, dict) else None


def _validate_comparison(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value.get("eligibleForAdoption"), bool):
        raise LoopError("comparison.eligibleForAdoption must be boolean")
    if not isinstance(value.get("reproducible"), bool):
        raise LoopError("comparison.reproducible must be boolean")
    regressions = value.get("regressions")
    if not isinstance(regressions, list):
        raise LoopError("comparison.regressions must be a list")
    return dict(value)


def _external_comparison(
    root: Path,
    product_id: str,
    summary: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any] | None:
    path = reports_dir(root, product_id) / EXPERIMENT_COMPARISON
    value = _optional_json(path)
    if value is None:
        return None
    expected_digest = summary.get("summaryDigest")
    if value.get("summaryDigest") != expected_digest:
        raise LoopError(
            "experiment-comparison summaryDigest does not match current experiment"
        )
    expected_method = candidate.get("methodId")
    if value.get("candidateMethod") not in {None, expected_method}:
        raise LoopError(
            "experiment-comparison candidateMethod does not match current candidate"
        )
    comparison = value.get("comparison")
    if isinstance(comparison, dict):
        return _validate_comparison(comparison)
    return _validate_comparison(value)


def _record_iteration(
    root: Path,
    product_id: str,
    plan: Mapping[str, Any],
    selected: Mapping[str, Any],
    decision: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> Path:
    existing = improvement.load_iteration_records(root, product_id)
    for record in existing:
        if record.get("decisionDigest") == decision.get("decisionDigest"):
            return root / str(record["_path"])
    finding = plan.get("finding") if isinstance(plan.get("finding"), dict) else {}
    return improvement.append_iteration_record(
        root,
        product_id,
        {
            "candidateHash": plan.get("candidateHash"),
            "defect": dict(finding),
            "missingCapability": plan.get("missingCapability"),
            "context": {
                "defectClass": finding.get("aspect"),
                "part": finding.get("affectedPart"),
                "pose": finding.get("pose"),
                "view": finding.get("view"),
            },
            "methodsTried": [dict(selected)],
            "experimentDigest": summary.get("summaryDigest"),
            "comparison": decision.get("comparison"),
            "decision": decision.get("decision"),
            "decisionDigest": decision.get("decisionDigest"),
            "nextRetryPoint": finding.get("recommendedReturnStage"),
        },
    )


def _load_or_run_experiment(
    root: Path,
    product_id: str,
    plan: Mapping[str, Any],
    binding: Mapping[str, Any],
    *,
    run: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_path = reports_dir(root, product_id) / EXPERIMENT_MANIFEST
    summary_path = reports_dir(root, product_id) / EXPERIMENT_SUMMARY
    manifest = _optional_json(manifest_path)
    current_key = _selected_method_key(plan)
    stale = (
        manifest is None
        or manifest.get("inputCandidateHash") != plan.get("candidateHash")
        or manifest.get("selectedMethodKey") != current_key
    )
    if stale:
        if not run:
            raise LoopError("persisted experiment does not match current plan")
        manifest = build_experiment_manifest(product_id, plan, binding)
        _persist(root, product_id, EXPERIMENT_MANIFEST, manifest)
    else:
        validation = improvement.validate_experiment_manifest(manifest)
        if validation.get("passed") is not True:
            raise LoopError("persisted experiment manifest is invalid")

    if run:
        for method_id in improvement.experiment_matrix(manifest):
            improvement.run_experiment_method(root, manifest, method_id)
        summary = improvement.aggregate_experiment_results(root, manifest)
        _persist(root, product_id, EXPERIMENT_SUMMARY, summary)
    else:
        summary = _optional_json(summary_path)
        if summary is None:
            raise LoopError("persisted experiment summary is missing")
        if summary.get("manifestDigest") != manifest.get("manifestDigest"):
            raise LoopError("experiment summary does not match current manifest")
    return manifest, summary


def _decision(
    plan: Mapping[str, Any],
    binding: Mapping[str, Any],
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    comparison: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    selected = dict(plan.get("selectedMethod") or {})
    selected["experimentBinding"] = dict(binding)
    license_status = str(selected.get("licenseStatus") or "UNVERIFIED")
    integration_point = (
        selected.get("productionIntegrationPoint")
        or binding.get("productionIntegrationPoint")
        or selected.get("integrationBoundary")
    )
    decision = improvement.make_adoption_decision(
        capability_id=str(plan.get("missingCapability") or "unresolved"),
        baseline=baseline,
        candidate=candidate,
        comparison=comparison,
        license_status=license_status,
        integration_point=str(integration_point) if integration_point else None,
    )
    return selected, decision


def _apply_once(
    root: Path,
    product_id: str,
    decision_digest: str,
    command: list[Any],
) -> Path:
    path = reports_dir(root, product_id) / INTEGRATION_RECORD
    existing = _optional_json(path)
    if (
        existing
        and existing.get("decisionDigest") == decision_digest
        and existing.get("status") == "APPLIED"
    ):
        return path
    completed = subprocess.run(
        [str(part) for part in command],
        cwd=root,
        check=False,
    )
    if completed.returncode != 0:
        raise LoopError(
            f"production integration command failed with {completed.returncode}"
        )
    record = {
        "schemaVersion": 1,
        "decisionDigest": decision_digest,
        "status": "APPLIED",
        "appliedAt": improvement.utc_now(),
        "command": [str(part) for part in command],
    }
    _persist(root, product_id, INTEGRATION_RECORD, record)
    return path


def _regenerate_and_replan(
    root: Path,
    product_id: str,
    previous_plan: Mapping[str, Any],
    regenerate: Callable[[], int] | None,
) -> dict[str, Any]:
    if regenerate is None:
        return {
            "status": "ADOPTED",
            "productId": product_id,
            "nextAction": "REGENERATE_AND_REEVALUATE",
        }
    code = regenerate()
    if code != 0:
        raise LoopError(f"product regeneration failed with {code}")
    next_plan = improvement.plan_improvement(root, product_id)
    if _same_context(previous_plan, next_plan):
        return _waiting(
            root,
            product_id,
            dict(previous_plan),
            "WAITING_FOR_REEVALUATION",
            reason=(
                "Production command completed, but candidate/defect evidence has not "
                "changed yet; new QualitySpec evidence is required before another retry."
            ),
            required_artifact=(
                root / improvement.QUALITY_REPORT.format(product=product_id)
            ),
        )
    improvement.persist_plan(root, product_id, next_plan)
    return {
        "status": "REEVALUATED",
        "productId": product_id,
        "nextPlan": next_plan,
    }


def _resume_adoption(
    root: Path,
    product_id: str,
    plan: dict[str, Any],
    binding: Mapping[str, Any],
    *,
    regenerate: Callable[[], int] | None,
) -> dict[str, Any]:
    decision_path = reports_dir(root, product_id) / ADOPTION_DECISION
    decision = _optional_json(decision_path)
    if decision is None or decision.get("decision") != "ADOPT":
        raise LoopError("no measured ADOPT decision is available for production integration")
    command = binding.get("applyCommand")
    if not isinstance(command, list) or not command:
        return _waiting(
            root,
            product_id,
            plan,
            "WAITING_FOR_PRODUCTION_INTEGRATION",
            reason=(
                "Measured candidate qualifies for adoption, but no explicit applyCommand "
                "is bound to the production stage."
            ),
            required_artifact=reports_dir(root, product_id) / EXPERIMENT_BINDING,
        )
    decision_digest = str(decision.get("decisionDigest") or "")
    if not decision_digest:
        raise LoopError("adoption decision is missing decisionDigest")
    _apply_once(root, product_id, decision_digest, command)
    summary = _optional_json(reports_dir(root, product_id) / EXPERIMENT_SUMMARY)
    if summary is None:
        raise LoopError("experiment summary is required to record adoption")
    selected = dict(plan.get("selectedMethod") or {})
    selected["experimentBinding"] = dict(binding)
    record_path = _record_iteration(
        root,
        product_id,
        plan,
        selected,
        decision,
        summary,
    )
    result = _regenerate_and_replan(
        root,
        product_id,
        plan,
        regenerate,
    )
    return {
        **result,
        "decisionPath": _relative(root, decision_path),
        "iterationPath": _relative(root, record_path),
    }


def _reuse_measured_method(
    root: Path,
    product_id: str,
    plan: dict[str, Any],
    *,
    regenerate: Callable[[], int] | None,
) -> dict[str, Any]:
    binding = _binding_for_plan(root, product_id, plan)
    if binding is None:
        return _waiting(
            root,
            product_id,
            plan,
            "WAITING_FOR_PRODUCTION_INTEGRATION",
            reason="Measured method is reusable but its executable production binding is unavailable.",
            required_artifact=reports_dir(root, product_id) / EXPERIMENT_BINDING,
        )
    command = binding.get("applyCommand")
    if not isinstance(command, list) or not command:
        return _waiting(
            root,
            product_id,
            plan,
            "WAITING_FOR_PRODUCTION_INTEGRATION",
            reason="Measured method is reusable but its applyCommand is unavailable.",
            required_artifact=reports_dir(root, product_id) / EXPERIMENT_BINDING,
        )
    reuse_digest = improvement.digest_value(
        [
            plan.get("candidateHash"),
            plan.get("missingCapability"),
            _selected_method_key(plan),
            "reuse",
        ]
    )
    _apply_once(root, product_id, reuse_digest, command)
    return _regenerate_and_replan(root, product_id, plan, regenerate)


def advance(
    root: Path,
    product_id: str,
    *,
    regenerate: Callable[[], int] | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    plan = _base_plan(root, product_id)
    action = str(plan.get("nextAction") or "NONE")

    if action == "NONE" or plan.get("status") == "NO_DEFECT":
        return {
            "status": "NO_DEFECT",
            "productId": product_id,
            "candidateHash": plan.get("candidateHash"),
            "plan": plan,
        }

    if action == "WAITING_FOR_REEVALUATION":
        return _waiting(
            root,
            product_id,
            plan,
            "WAITING_FOR_REEVALUATION",
            reason=str(
                plan.get("waitingReason")
                or "New QualitySpec evidence is required before another retry."
            ),
            required_artifact=(
                root / improvement.QUALITY_REPORT.format(product=product_id)
            ),
        )

    if action in {"RESEARCH_REQUIRED", "WAITING_FOR_EXTERNAL_RESEARCH"}:
        progressed = _consume_research(root, product_id, plan)
        if progressed.get("status") == "WAITING_FOR_EXTERNAL_RESEARCH":
            return progressed
        plan = progressed
        action = str(plan.get("nextAction"))

    if action in {
        "IMPLEMENT_EXPERIMENT_BINDING",
        "WAITING_FOR_EXPERIMENT_BINDING",
    }:
        binding = _binding_for_plan(root, product_id, plan)
        if binding is None:
            return _waiting(
                root,
                product_id,
                plan,
                "WAITING_FOR_EXPERIMENT_BINDING",
                reason=(
                    "The selected technique has primary evidence but no executable "
                    "baseline/candidate experiment binding yet."
                ),
                required_artifact=reports_dir(root, product_id) / EXPERIMENT_BINDING,
            )
        selected = dict(plan.get("selectedMethod") or {})
        selected["experimentBinding"] = binding
        plan = {
            **plan,
            "selectedMethod": selected,
            "nextAction": "RUN_EXPERIMENT",
            "status": "ACTIONABLE",
        }
        improvement.persist_plan(root, product_id, plan)
        action = "RUN_EXPERIMENT"

    if action in {"RUN_EXPERIMENT", "WAITING_FOR_COMPARISON"}:
        binding = _binding_for_plan(root, product_id, plan)
        if binding is None:
            return _waiting(
                root,
                product_id,
                plan,
                "WAITING_FOR_EXPERIMENT_BINDING",
                reason="Experiment cannot continue without an executable binding.",
                required_artifact=reports_dir(root, product_id) / EXPERIMENT_BINDING,
            )
        manifest, summary = _load_or_run_experiment(
            root,
            product_id,
            plan,
            binding,
            run=action == "RUN_EXPERIMENT",
        )
        baseline = _method_by_role(summary, "baseline", manifest)
        candidate = _method_by_role(summary, "candidate", manifest)
        if baseline is None or baseline.get("status") != "PASS":
            raise LoopError(
                "baseline experiment did not PASS; candidate comparison is invalid"
            )
        if candidate is None:
            raise LoopError("candidate experiment result is missing")
        comparison = _comparison_from_candidate(candidate)
        if comparison is not None:
            comparison = _validate_comparison(comparison)
        elif candidate.get("status") == "PASS":
            comparison = _external_comparison(
                root,
                product_id,
                summary,
                candidate,
            )
            if comparison is None:
                return _waiting(
                    root,
                    product_id,
                    plan,
                    "WAITING_FOR_COMPARISON",
                    reason=(
                        "Candidate ran successfully but no same-condition A/B comparison "
                        "is bound to the current experiment summary."
                    ),
                    required_artifact=(
                        reports_dir(root, product_id) / EXPERIMENT_COMPARISON
                    ),
                )
        else:
            comparison = {
                "eligibleForAdoption": False,
                "reproducible": True,
                "regressions": ["candidate experiment failed"],
            }
        selected, decision = _decision(
            plan,
            binding,
            baseline,
            candidate,
            comparison,
        )
        decision_path = _persist(
            root,
            product_id,
            ADOPTION_DECISION,
            decision,
        )
        if decision.get("decision") == "ADOPT":
            plan = {
                **plan,
                "selectedMethod": selected,
                "adoptionDecisionPath": _relative(root, decision_path),
            }
            improvement.persist_plan(root, product_id, plan)
            return _resume_adoption(
                root,
                product_id,
                plan,
                binding,
                regenerate=regenerate,
            )
        record_path = _record_iteration(
            root,
            product_id,
            plan,
            selected,
            decision,
            summary,
        )
        next_plan = improvement.plan_improvement(root, product_id)
        improvement.persist_plan(root, product_id, next_plan)
        return {
            "status": "ITERATION_RECORDED",
            "productId": product_id,
            "decision": decision.get("decision"),
            "decisionPath": _relative(root, decision_path),
            "iterationPath": _relative(root, record_path),
            "nextPlan": next_plan,
        }

    if action == "WAITING_FOR_PRODUCTION_INTEGRATION":
        binding = _binding_for_plan(root, product_id, plan)
        if binding is None:
            return _waiting(
                root,
                product_id,
                plan,
                "WAITING_FOR_PRODUCTION_INTEGRATION",
                reason="Production integration binding is still unavailable.",
                required_artifact=reports_dir(root, product_id) / EXPERIMENT_BINDING,
            )
        return _resume_adoption(
            root,
            product_id,
            plan,
            binding,
            regenerate=regenerate,
        )

    if action == "REUSE_MEASURED_METHOD":
        return _reuse_measured_method(
            root,
            product_id,
            plan,
            regenerate=regenerate,
        )

    if action in WAITING:
        return {
            "status": action,
            "productId": product_id,
            "plan": plan,
            "resumeCommand": f"python tools/manage.py improve --product {product_id}",
        }

    raise LoopError(f"unsupported improvement action: {action}")
