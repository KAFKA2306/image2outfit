"""Runner-only machine audit primitives for garment completion.

This module is intentionally Blender-agnostic. Producers emit observations and
an evidence index; this module owns immutable request identity, tri-state metric
classification, evidence binding, blocker selection, Pareto adoption, and
terminal Runner status.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

_HASH = re.compile(r"^[0-9a-f]{64}$")


class MetricState(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNVERIFIED = "UNVERIFIED"


class Decision(StrEnum):
    KEEP = "KEEP"
    REVERT = "REVERT"


class StopReason(StrEnum):
    SUCCESS = "SUCCESS"
    STALLED = "STALLED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    FAILED_HARD = "FAILED_HARD"


STAGE_ORDER = (
    "reproducibility-evidence",
    "geometry",
    "seam-structure",
    "fit-collision",
    "pose-robustness",
    "silhouette-fidelity",
    "material-fidelity",
)

_REQUEST_REQUIRED = (
    "requestId",
    "productId",
    "referenceImages",
    "targetAvatarAuthoritySha256",
    "garmentType",
    "regionFitClass",
    "requiredViews",
    "requiredPoses",
    "materialTargets",
    "thresholdProfileId",
    "randomSeed",
    "blenderVersion",
    "producerVersions",
    "maxAttemptsPerBlocker",
    "maxTotalAttempts",
    "maxRunnerMinutes",
    "thresholds",
    "fitBands",
    "epsilonArea",
    "epsilonPenetrationMeters",
)


@dataclass(frozen=True)
class MetricResult:
    metric_id: str
    stage: str
    value: Any
    threshold: Any
    state: MetricState
    producer: str | None
    evidence_sha256: str | None
    cause: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "threshold": self.threshold,
            "state": self.state.value,
            "producer": self.producer,
            "evidenceSha256": self.evidence_sha256,
            "cause": self.cause,
            "stage": self.stage,
        }


def canonical_json_bytes(value: Any) -> bytes:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("runner audit data must be finite JSON") from exc
    return payload.encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def validate_request_manifest(request: Mapping[str, Any]) -> None:
    missing = [name for name in _REQUEST_REQUIRED if name not in request]
    if missing:
        raise ValueError("request manifest missing fields: " + ", ".join(missing))
    if not isinstance(request["requestId"], str) or not request["requestId"]:
        raise ValueError("requestId must be a non-empty string")
    if not isinstance(request["productId"], str) or not request["productId"]:
        raise ValueError("productId must be a non-empty string")
    authority = request["targetAvatarAuthoritySha256"]
    if not isinstance(authority, str) or not _HASH.fullmatch(authority):
        raise ValueError("targetAvatarAuthoritySha256 must be a lowercase SHA-256")
    references = request["referenceImages"]
    if not isinstance(references, list):
        raise ValueError("referenceImages must be a list")
    for index, item in enumerate(references):
        if not isinstance(item, Mapping):
            raise ValueError(f"referenceImages[{index}] must be an object")
        digest = item.get("sha256")
        if not isinstance(digest, str) or not _HASH.fullmatch(digest):
            raise ValueError(f"referenceImages[{index}].sha256 is invalid")
        if not isinstance(item.get("path"), str) or not item["path"]:
            raise ValueError(f"referenceImages[{index}].path is required")
    fit = request["regionFitClass"]
    if not isinstance(fit, Mapping) or not fit:
        raise ValueError("regionFitClass must be a non-empty object")
    bad_fit = sorted(k for k, v in fit.items() if v not in {"close", "regular", "loose"})
    if bad_fit:
        raise ValueError("invalid regionFitClass values: " + ", ".join(bad_fit))
    for field in ("requiredViews", "requiredPoses"):
        value = request[field]
        if not isinstance(value, list) or not value or not all(
            isinstance(item, str) and item for item in value
        ):
            raise ValueError(f"{field} must be a non-empty string list")
        if len(value) != len(set(value)):
            raise ValueError(f"{field} must not contain duplicates")
    if not isinstance(request["materialTargets"], (dict, list)):
        raise ValueError("materialTargets must be an object or list")
    if not isinstance(request["producerVersions"], Mapping):
        raise ValueError("producerVersions must be an object")
    if not isinstance(request["thresholds"], list) or not request["thresholds"]:
        raise ValueError("thresholds must be a non-empty frozen metric list")
    if not isinstance(request["fitBands"], Mapping) or not request["fitBands"]:
        raise ValueError("fitBands must be a non-empty frozen object")
    for field in ("epsilonArea", "epsilonPenetrationMeters"):
        value = _finite_number(request[field])
        if value is None or value < 0:
            raise ValueError(f"{field} must be a finite non-negative number")
    for field in ("maxAttemptsPerBlocker", "maxTotalAttempts", "maxRunnerMinutes"):
        value = request[field]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"{field} must be a positive integer")
    if request["maxAttemptsPerBlocker"] > request["maxTotalAttempts"]:
        raise ValueError("maxAttemptsPerBlocker cannot exceed maxTotalAttempts")
    seed = request["randomSeed"]
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("randomSeed must be an integer")


def freeze_request_manifest(
    draft: Mapping[str, Any], profile: Mapping[str, Any]
) -> dict[str, Any]:
    profile_id = profile.get("profileId")
    if draft.get("thresholdProfileId") != profile_id:
        raise ValueError("thresholdProfileId does not match selected profile")
    metrics = profile.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        raise ValueError("threshold profile metrics must be a non-empty list")
    frozen = dict(draft)
    frozen["thresholds"] = [dict(item) for item in metrics if isinstance(item, Mapping)]
    frozen["fitBands"] = dict(profile.get("fitBands", {}))
    frozen["epsilonArea"] = profile.get("epsilonArea")
    frozen["epsilonPenetrationMeters"] = profile.get("epsilonPenetrationMeters")
    frozen["stageOrder"] = list(profile.get("stageOrder", STAGE_ORDER))
    frozen["auditPolicyVersion"] = profile.get("schemaVersion", 1)
    validate_request_manifest(frozen)
    return frozen


def frozen_profile(request: Mapping[str, Any]) -> dict[str, Any]:
    validate_request_manifest(request)
    return {
        "schemaVersion": request.get("auditPolicyVersion", 1),
        "profileId": request["thresholdProfileId"],
        "stageOrder": list(request.get("stageOrder", STAGE_ORDER)),
        "fitBands": dict(request["fitBands"]),
        "epsilonArea": request["epsilonArea"],
        "epsilonPenetrationMeters": request["epsilonPenetrationMeters"],
        "metrics": [dict(item) for item in request["thresholds"]],
    }


def request_sha256(request: Mapping[str, Any]) -> str:
    validate_request_manifest(request)
    return sha256_json(dict(request))


def _material_targets(request: Mapping[str, Any]) -> Mapping[str, Any]:
    value = request.get("materialTargets")
    return value if isinstance(value, Mapping) else {}


def _required_metric(definition: Mapping[str, Any], request: Mapping[str, Any]) -> bool:
    if definition.get("required") is True:
        return True
    material_targets = _material_targets(request)
    if definition.get("requiredIfMaterialTargets") is True:
        return bool(material_targets)
    key = definition.get("requiredWhenMaterialKey")
    if isinstance(key, str) and key:
        return bool(material_targets.get(key))
    return False


def required_metric_ids(
    profile: Mapping[str, Any], request: Mapping[str, Any]
) -> list[str]:
    metrics = profile.get("metrics")
    if not isinstance(metrics, list):
        raise ValueError("threshold profile metrics must be a list")
    result: list[str] = []
    for item in metrics:
        if not isinstance(item, Mapping):
            raise ValueError("threshold profile metric must be an object")
        metric_id = item.get("id")
        if not isinstance(metric_id, str) or not metric_id:
            raise ValueError("threshold profile metric id is required")
        if _required_metric(item, request):
            result.append(metric_id)
    if len(result) != len(set(result)):
        raise ValueError("threshold profile contains duplicate required metric ids")
    return result


def _compare(value: float, operator: str, threshold: Any) -> bool:
    if operator == "eq":
        target = _finite_number(threshold)
        return target is not None and value == target
    if operator == "lte":
        target = _finite_number(threshold)
        return target is not None and value <= target
    if operator == "gte":
        target = _finite_number(threshold)
        return target is not None and value >= target
    if operator == "range":
        if not isinstance(threshold, Sequence) or isinstance(threshold, (str, bytes)):
            return False
        if len(threshold) != 2:
            return False
        lower = _finite_number(threshold[0])
        upper = _finite_number(threshold[1])
        return lower is not None and upper is not None and lower <= value <= upper
    raise ValueError(f"unsupported metric operator: {operator}")


def _resolve_inside(root: Path, relative_path: str) -> Path:
    path = Path(relative_path)
    if path.is_absolute():
        raise ValueError("evidence path must be relative")
    resolved_root = root.resolve()
    resolved = (resolved_root / path).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError("evidence path escapes repository root")
    return resolved


def _evidence_state(
    observation: Mapping[str, Any], *, root: Path
) -> tuple[str | None, str | None]:
    path_value = observation.get("evidencePath")
    declared = observation.get("evidenceSha256")
    if not isinstance(path_value, str) or not path_value:
        return None, "EVIDENCE_MISSING"
    if not isinstance(declared, str) or not _HASH.fullmatch(declared):
        return None, "EVIDENCE_HASH_MISSING"
    try:
        path = _resolve_inside(root, path_value)
    except ValueError:
        return None, "EVIDENCE_PATH_INVALID"
    if not path.is_file():
        return None, "EVIDENCE_MISSING"
    actual = sha256_file(path)
    if actual != declared:
        return actual, "EVIDENCE_HASH_MISMATCH"
    return actual, None


def evaluate_metric(
    definition: Mapping[str, Any],
    observation: Mapping[str, Any] | None,
    *,
    root: Path,
) -> MetricResult:
    metric_id = str(definition["id"])
    stage = str(definition["stage"])
    threshold = definition.get("threshold")
    if observation is None:
        return MetricResult(
            metric_id, stage, None, threshold, MetricState.UNVERIFIED,
            None, None, "OBSERVATION_MISSING",
        )
    producer = observation.get("producer")
    if not isinstance(producer, str) or not producer:
        return MetricResult(
            metric_id, stage, observation.get("value"), threshold,
            MetricState.UNVERIFIED, None, None, "PRODUCER_MISSING",
        )
    actual_evidence_sha, evidence_error = _evidence_state(observation, root=root)
    if evidence_error:
        return MetricResult(
            metric_id, stage, observation.get("value"), threshold,
            MetricState.UNVERIFIED, producer, actual_evidence_sha, evidence_error,
        )
    value = _finite_number(observation.get("value"))
    if value is None:
        return MetricResult(
            metric_id, stage, observation.get("value"), threshold,
            MetricState.UNVERIFIED, producer, actual_evidence_sha,
            "VALUE_UNMEASURABLE",
        )
    passed = _compare(value, str(definition["operator"]), threshold)
    return MetricResult(
        metric_id, stage, value, threshold,
        MetricState.PASS if passed else MetricState.FAIL,
        producer, actual_evidence_sha, None,
    )


def verify_artifacts(
    artifacts: Sequence[Mapping[str, Any]],
    *, root: Path, product_id: str, request_digest: str,
) -> MetricResult:
    if not artifacts:
        return MetricResult(
            "evidence.artifact_identity", "reproducibility-evidence", None, 0,
            MetricState.UNVERIFIED, "artifact-verifier", None,
            "ARTIFACT_SET_MISSING",
        )
    mismatches = 0
    for artifact in artifacts:
        path_value = artifact.get("path")
        declared = artifact.get("sha256")
        if not isinstance(path_value, str) or not path_value:
            return MetricResult(
                "evidence.artifact_identity", "reproducibility-evidence", None, 0,
                MetricState.UNVERIFIED, "artifact-verifier", None,
                "ARTIFACT_PATH_MISSING",
            )
        if not isinstance(declared, str) or not _HASH.fullmatch(declared):
            return MetricResult(
                "evidence.artifact_identity", "reproducibility-evidence", None, 0,
                MetricState.UNVERIFIED, "artifact-verifier", None,
                "ARTIFACT_HASH_MISSING",
            )
        try:
            path = _resolve_inside(root, path_value)
        except ValueError:
            mismatches += 1
            continue
        if (
            not path.is_file()
            or sha256_file(path) != declared
            or artifact.get("productId") != product_id
            or artifact.get("requestSha256") != request_digest
        ):
            mismatches += 1
    return MetricResult(
        "evidence.artifact_identity", "reproducibility-evidence", mismatches, 0,
        MetricState.PASS if mismatches == 0 else MetricState.FAIL,
        "artifact-verifier", None, None,
    )


def verified_evidence_ratio(
    evidence: Sequence[Mapping[str, Any]],
    *, root: Path, product_id: str, request_digest: str,
) -> MetricResult:
    required = [item for item in evidence if item.get("required") is True]
    if not required:
        return MetricResult(
            "evidence.verified_ratio", "reproducibility-evidence", None, 1.0,
            MetricState.UNVERIFIED, "evidence-verifier", None,
            "REQUIRED_EVIDENCE_UNDEFINED",
        )
    verified = 0
    unverifiable = False
    for item in required:
        path_value = item.get("path")
        declared = item.get("sha256")
        if not isinstance(path_value, str) or not path_value:
            unverifiable = True
            continue
        if not isinstance(declared, str) or not _HASH.fullmatch(declared):
            unverifiable = True
            continue
        try:
            path = _resolve_inside(root, path_value)
        except ValueError:
            unverifiable = True
            continue
        if not path.is_file():
            unverifiable = True
            continue
        if item.get("productId") != product_id or item.get("requestSha256") != request_digest:
            continue
        if sha256_file(path) == declared:
            verified += 1
    ratio = verified / len(required)
    if unverifiable:
        state = MetricState.UNVERIFIED
        cause = "EVIDENCE_MISSING_OR_UNMEASURABLE"
    else:
        state = MetricState.PASS if ratio == 1.0 else MetricState.FAIL
        cause = None
    return MetricResult(
        "evidence.verified_ratio", "reproducibility-evidence", ratio, 1.0,
        state, "evidence-verifier", None, cause,
    )


def evaluate_metrics(
    profile: Mapping[str, Any], request: Mapping[str, Any],
    observations: Mapping[str, Any], *, root: Path,
) -> dict[str, MetricResult]:
    result: dict[str, MetricResult] = {}
    metrics = profile.get("metrics", [])
    for definition in metrics:
        if not isinstance(definition, Mapping) or not _required_metric(definition, request):
            continue
        metric_id = str(definition["id"])
        observation = observations.get(metric_id)
        result[metric_id] = evaluate_metric(
            definition,
            observation if isinstance(observation, Mapping) else None,
            root=root,
        )
    return result


def _severity(definition: Mapping[str, Any], result: MetricResult) -> float:
    if result.state is MetricState.UNVERIFIED:
        return math.inf
    if result.state is MetricState.PASS:
        return 0.0
    value = _finite_number(result.value)
    threshold = _finite_number(definition.get("threshold"))
    scale = _finite_number(definition.get("scale"))
    if value is None or threshold is None or scale is None or scale <= 0:
        return math.inf
    direction = str(definition.get("direction", "lower"))
    delta = value - threshold if direction == "lower" else threshold - value
    return max(0.0, delta / scale)


def select_blocker(
    profile: Mapping[str, Any], results: Mapping[str, MetricResult]
) -> str | None:
    definitions = {
        str(item["id"]): item
        for item in profile.get("metrics", [])
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    stage_order = tuple(profile.get("stageOrder", STAGE_ORDER))
    for stage in stage_order:
        candidates = [
            result for result in results.values()
            if result.stage == stage and result.state is not MetricState.PASS
        ]
        if not candidates:
            continue
        candidates.sort(
            key=lambda item: (-_severity(definitions[item.metric_id], item), item.metric_id)
        )
        return candidates[0].metric_id
    return None


def _normalized_value(definition: Mapping[str, Any], result: MetricResult) -> float | None:
    value = _finite_number(result.value)
    if value is None:
        return None
    return -value if definition.get("direction") == "higher" else value


def pareto_decision(
    profile: Mapping[str, Any], current: Mapping[str, MetricResult],
    new: Mapping[str, MetricResult],
) -> Decision:
    definitions = {
        str(item["id"]): item
        for item in profile.get("metrics", [])
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    improved = False
    for metric_id in sorted(set(current) | set(new)):
        old = current.get(metric_id)
        fresh = new.get(metric_id)
        definition = definitions.get(metric_id)
        if old is None or fresh is None or definition is None:
            return Decision.REVERT
        if old.state is MetricState.UNVERIFIED or fresh.state is MetricState.UNVERIFIED:
            return Decision.REVERT
        if old.state is MetricState.PASS and fresh.state is not MetricState.PASS:
            return Decision.REVERT
        old_value = _normalized_value(definition, old)
        new_value = _normalized_value(definition, fresh)
        if old_value is None or new_value is None:
            return Decision.REVERT
        tolerance = float(definition.get("tolerance", 0.0))
        minimum = float(definition.get("minImprovement", 0.0))
        if new_value > old_value + tolerance:
            return Decision.REVERT
        if new_value <= old_value - minimum and new_value < old_value:
            improved = True
    return Decision.KEEP if improved else Decision.REVERT


def runner_complete(
    results: Mapping[str, MetricResult], *, required_ids: Sequence[str],
    request_digest: str, audit_request_digest: str, candidate_sha256: str,
    audit_candidate_sha256: str, final_attempt_decision: Decision | None,
) -> bool:
    if request_digest != audit_request_digest or candidate_sha256 != audit_candidate_sha256:
        return False
    if final_attempt_decision is Decision.REVERT:
        return False
    for metric_id in required_ids:
        result = results.get(metric_id)
        if result is None or result.state is not MetricState.PASS:
            return False
    evidence = results.get("evidence.verified_ratio")
    artifact = results.get("evidence.artifact_identity")
    if evidence is None or evidence.state is not MetricState.PASS:
        return False
    if artifact is None or artifact.state is not MetricState.PASS:
        return False
    return True


def stop_reason(
    *, complete: bool, failed_hard: bool, total_attempts: int,
    elapsed_minutes: float, max_total_attempts: int, max_runner_minutes: int,
    blocker_attempts: int, max_attempts_per_blocker: int,
    accepted_for_blocker: int,
) -> StopReason | None:
    if complete:
        return StopReason.SUCCESS
    if failed_hard:
        return StopReason.FAILED_HARD
    if total_attempts >= max_total_attempts or elapsed_minutes >= max_runner_minutes:
        return StopReason.BUDGET_EXHAUSTED
    if blocker_attempts >= max_attempts_per_blocker and accepted_for_blocker == 0:
        return StopReason.STALLED
    return None


def audit_result(
    *, request_digest: str, candidate_sha256: str,
    results: Mapping[str, MetricResult], attempts: int,
    stop: StopReason | None,
) -> dict[str, Any]:
    required_states = [item.state for item in results.values()]
    if any(state is MetricState.UNVERIFIED for state in required_states):
        status = MetricState.UNVERIFIED
    elif any(state is MetricState.FAIL for state in required_states):
        status = MetricState.FAIL
    else:
        status = MetricState.PASS
    return {
        "requestSha256": request_digest,
        "candidateSha256": candidate_sha256,
        "status": status.value,
        "metrics": {key: value.as_dict() for key, value in sorted(results.items())},
        "attempts": attempts,
        "stopReason": stop.value if stop is not None else None,
    }
