"""Evidence-bound garment quality specification and release evaluation.

The module deliberately keeps diagnostic quality axes separate from the fixed
completion gates.  It produces one defect per failed cause, verifies every
referenced artifact by SHA-256, and only allows ``visualAppearanceReview`` to
pass after direct image review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EXPECTED_ASPECTS = {
    "topology",
    "seam",
    "fit",
    "material-response",
    "layering",
    "skinning",
    "collision",
    "silhouette",
    "styling-fidelity",
    "evidence-completeness",
}


class QualityStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class ReviewMethod(StrEnum):
    AUTOMATED = "AUTOMATED"
    DIRECT_IMAGE_REVIEW = "DIRECT_IMAGE_REVIEW"


class MetricOperator(StrEnum):
    EQ = "eq"
    LTE = "lte"
    GTE = "gte"


@dataclass(frozen=True)
class MetricRule:
    name: str
    operator: MetricOperator
    threshold: bool | int | float | str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MetricRule":
        name = value.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("metric.name is required")
        try:
            operator = MetricOperator(value.get("operator"))
        except ValueError as exc:
            raise ValueError(f"unsupported metric operator for {name}") from exc
        threshold = value.get("threshold")
        if not isinstance(threshold, (bool, int, float, str)):
            raise ValueError(f"metric.threshold is required for {name}")
        return cls(name=name, operator=operator, threshold=threshold)

    def passes(self, value: Any) -> bool:
        if self.operator is MetricOperator.EQ:
            return value == self.threshold
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        if isinstance(self.threshold, bool) or not isinstance(
            self.threshold, (int, float)
        ):
            return False
        if self.operator is MetricOperator.LTE:
            return float(value) <= float(self.threshold)
        return float(value) >= float(self.threshold)


@dataclass(frozen=True)
class QualityAspectSpec:
    aspect_id: str
    metric: MetricRule
    allowed_methods: tuple[ReviewMethod, ...]
    required_evidence_kinds: tuple[str, ...]
    target_views: tuple[str, ...]
    target_poses: tuple[str, ...]
    defect_code: str
    return_stage: str
    completion_gate: str
    allow_out_of_scope: bool = False
    computed: bool = False

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "QualityAspectSpec":
        aspect_id = value.get("id")
        if not isinstance(aspect_id, str) or not aspect_id.strip():
            raise ValueError("aspect.id is required")
        methods_raw = value.get("allowedReviewMethods")
        if not isinstance(methods_raw, list) or not methods_raw:
            raise ValueError(f"{aspect_id}: allowedReviewMethods is required")
        try:
            methods = tuple(ReviewMethod(item) for item in methods_raw)
        except ValueError as exc:
            raise ValueError(f"{aspect_id}: invalid review method") from exc

        def strings(field: str) -> tuple[str, ...]:
            raw = value.get(field, [])
            if not isinstance(raw, list) or not all(
                isinstance(item, str) and item for item in raw
            ):
                raise ValueError(f"{aspect_id}: {field} must be a string list")
            return tuple(raw)

        defect_code = value.get("defectCode")
        return_stage = value.get("returnStage")
        completion_gate = value.get("completionGate")
        for field, candidate in (
            ("defectCode", defect_code),
            ("returnStage", return_stage),
            ("completionGate", completion_gate),
        ):
            if not isinstance(candidate, str) or not candidate:
                raise ValueError(f"{aspect_id}: {field} is required")
        return cls(
            aspect_id=aspect_id,
            metric=MetricRule.from_dict(value.get("metric", {})),
            allowed_methods=methods,
            required_evidence_kinds=strings("requiredEvidenceKinds"),
            target_views=strings("targetViews"),
            target_poses=strings("targetPoses"),
            defect_code=defect_code,
            return_stage=return_stage,
            completion_gate=completion_gate,
            allow_out_of_scope=value.get("allowOutOfScope") is True,
            computed=value.get("computed") is True,
        )


@dataclass(frozen=True)
class DirectImageReviewSpec:
    required_method: ReviewMethod
    allowed_reviewer_prefixes: tuple[str, ...]
    required_evidence_kind: str
    required_views: tuple[str, ...]
    required_poses: tuple[str, ...]
    allowed_extensions: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DirectImageReviewSpec":
        try:
            method = ReviewMethod(value.get("requiredMethod"))
        except ValueError as exc:
            raise ValueError("directImageReview.requiredMethod is invalid") from exc
        if method is not ReviewMethod.DIRECT_IMAGE_REVIEW:
            raise ValueError("visualAppearanceReview must require direct image review")

        def strings(field: str) -> tuple[str, ...]:
            raw = value.get(field)
            if (
                not isinstance(raw, list)
                or not raw
                or not all(isinstance(item, str) and item for item in raw)
            ):
                raise ValueError(f"directImageReview.{field} is required")
            return tuple(raw)

        kind = value.get("requiredEvidenceKind")
        if not isinstance(kind, str) or not kind:
            raise ValueError("directImageReview.requiredEvidenceKind is required")
        return cls(
            required_method=method,
            allowed_reviewer_prefixes=strings("allowedReviewerPrefixes"),
            required_evidence_kind=kind,
            required_views=strings("requiredViews"),
            required_poses=strings("requiredPoses"),
            allowed_extensions=tuple(
                extension.lower() for extension in strings("allowedExtensions")
            ),
        )


@dataclass(frozen=True)
class QualitySpec:
    schema_version: int
    spec_id: str
    completion_gate: str
    hash_algorithm: str
    aspects: tuple[QualityAspectSpec, ...]
    direct_image_review: DirectImageReviewSpec

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "QualitySpec":
        if value.get("schemaVersion") != 1:
            raise ValueError("quality spec schemaVersion must be 1")
        spec_id = value.get("specId")
        if not isinstance(spec_id, str) or not spec_id:
            raise ValueError("quality spec specId is required")
        if value.get("completionGate") != "visualAppearanceReview":
            raise ValueError("quality spec must refine visualAppearanceReview")
        if value.get("hashAlgorithm") != "sha256":
            raise ValueError("quality spec hashAlgorithm must be sha256")
        raw_aspects = value.get("aspects")
        if not isinstance(raw_aspects, list):
            raise ValueError("quality spec aspects are required")
        aspects = tuple(QualityAspectSpec.from_dict(item) for item in raw_aspects)
        ids = [item.aspect_id for item in aspects]
        if len(ids) != len(set(ids)):
            raise ValueError("quality spec aspect ids must be unique")
        if set(ids) != _EXPECTED_ASPECTS:
            missing = sorted(_EXPECTED_ASPECTS - set(ids))
            extra = sorted(set(ids) - _EXPECTED_ASPECTS)
            raise ValueError(
                f"quality spec axes mismatch: missing={missing}, extra={extra}"
            )
        evidence_axis = next(
            item for item in aspects if item.aspect_id == "evidence-completeness"
        )
        if not evidence_axis.computed:
            raise ValueError("evidence-completeness must be computed")
        return cls(
            schema_version=1,
            spec_id=spec_id,
            completion_gate="visualAppearanceReview",
            hash_algorithm="sha256",
            aspects=aspects,
            direct_image_review=DirectImageReviewSpec.from_dict(
                value.get("directImageReview", {})
            ),
        )


@dataclass
class _EvidenceAudit:
    normalized: list[dict[str, Any]]
    errors: list[str]
    declared: int
    verified: int


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _relative_path(value: Any) -> str | None:
    if not _text(value):
        return None
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or normalized.startswith("./"):
        return None
    return path.as_posix()


def _contains_all(actual: Any, required: tuple[str, ...]) -> bool:
    return isinstance(actual, list) and set(required).issubset(
        item for item in actual if isinstance(item, str)
    )


def _audit_evidence(
    *,
    value: Any,
    required_kinds: tuple[str, ...],
    prefix: str,
    resolve_repo_path: Callable[[str], Path],
    digest: Callable[[Path], str],
    require_image_extensions: tuple[str, ...] = (),
    allow_empty: bool = False,
) -> _EvidenceAudit:
    if not isinstance(value, list):
        return _EvidenceAudit([], [f"{prefix}.evidence"], 0, 0)
    if not value:
        return _EvidenceAudit([], [] if allow_empty else [f"{prefix}.evidence"], 0, 0)
    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    kinds: set[str] = set()
    verified = 0
    for index, item in enumerate(value):
        item_prefix = f"{prefix}.evidence[{index}]"
        if not isinstance(item, dict):
            errors.append(item_prefix)
            continue
        kind = item.get("kind")
        path_value = _relative_path(item.get("path"))
        expected_hash = item.get("sha256")
        if not _text(kind):
            errors.append(f"{item_prefix}.kind")
            kind = ""
        if path_value is None:
            errors.append(f"{item_prefix}.path")
            path_value = ""
        if not isinstance(expected_hash, str) or not _SHA256.fullmatch(expected_hash):
            errors.append(f"{item_prefix}.sha256")
            expected_hash = ""
        if kind:
            kinds.add(kind)
        if path_value and kind:
            key = (path_value, kind)
            if key in seen:
                errors.append(f"{item_prefix}.duplicate")
            seen.add(key)
        if require_image_extensions and path_value:
            if Path(path_value).suffix.lower() not in require_image_extensions:
                errors.append(f"{item_prefix}.imageExtension")
        evidence_ok = bool(path_value and expected_hash)
        if evidence_ok:
            try:
                path = resolve_repo_path(path_value)
                if not path.is_file():
                    errors.append(f"{item_prefix}.missing")
                    evidence_ok = False
                elif digest(path) != expected_hash:
                    errors.append(f"{item_prefix}.sha256Mismatch")
                    evidence_ok = False
            except (OSError, ValueError):
                errors.append(f"{item_prefix}.path")
                evidence_ok = False
        if evidence_ok:
            verified += 1
        normalized.append(
            {
                "kind": kind or None,
                "path": path_value or None,
                "sha256": expected_hash or None,
                "verified": evidence_ok,
                "view": item.get("view"),
                "pose": item.get("pose"),
            }
        )
    for kind in required_kinds:
        if kind not in kinds:
            errors.append(f"{prefix}.requiredEvidenceKind:{kind}")
    return _EvidenceAudit(normalized, errors, len(value), verified)


def _defect(
    spec: QualityAspectSpec,
    reasons: list[str],
    declared_status: str | None,
) -> dict[str, Any]:
    return {
        "code": spec.defect_code,
        "aspect": spec.aspect_id,
        "declaredStatus": declared_status,
        "completionGate": spec.completion_gate,
        "recommendedReturnStage": spec.return_stage,
        "reasons": sorted(set(reasons)) or [f"{spec.aspect_id}: failed"],
    }


def _validate_visual_review(
    *,
    spec: QualitySpec,
    value: Any,
    resolve_repo_path: Callable[[str], Path],
    digest: Callable[[Path], str],
) -> tuple[dict[str, Any], list[str], _EvidenceAudit]:
    prefix = "visualAppearanceReview"
    errors: list[str] = []
    if not isinstance(value, dict):
        value = {}
        errors.append(prefix)
    declared_status = value.get("status")
    if declared_status != QualityStatus.PASS.value:
        errors.append(f"{prefix}.status")
    if value.get("reviewMethod") != spec.direct_image_review.required_method.value:
        errors.append(f"{prefix}.reviewMethod")
    reviewer = value.get("reviewer")
    if not _text(reviewer) or not any(
        reviewer.startswith(item)
        for item in spec.direct_image_review.allowed_reviewer_prefixes
    ):
        errors.append(f"{prefix}.reviewer")
    if not _text(value.get("reviewerReference")):
        errors.append(f"{prefix}.reviewerReference")
    evidence = _audit_evidence(
        value=value.get("evidence"),
        required_kinds=(spec.direct_image_review.required_evidence_kind,),
        prefix=prefix,
        resolve_repo_path=resolve_repo_path,
        digest=digest,
        require_image_extensions=spec.direct_image_review.allowed_extensions,
    )
    errors.extend(evidence.errors)
    views = {
        item.get("view")
        for item in evidence.normalized
        if item.get("kind") == spec.direct_image_review.required_evidence_kind
    }
    poses = {
        item.get("pose")
        for item in evidence.normalized
        if item.get("kind") == spec.direct_image_review.required_evidence_kind
    }
    for view in spec.direct_image_review.required_views:
        if view not in views:
            errors.append(f"{prefix}.requiredView:{view}")
    for pose in spec.direct_image_review.required_poses:
        if pose not in poses:
            errors.append(f"{prefix}.requiredPose:{pose}")
    unique = sorted(set(errors))
    return (
        {
            "status": QualityStatus.FAIL.value if unique else QualityStatus.PASS.value,
            "declaredStatus": declared_status,
            "reviewMethod": value.get("reviewMethod"),
            "reviewer": reviewer,
            "reviewerReference": value.get("reviewerReference"),
            "evidence": evidence.normalized,
            "failedFields": unique,
        },
        unique,
        evidence,
    )


def validate_quality_assessment(
    *,
    spec_data: Mapping[str, Any],
    assessment: Mapping[str, Any] | Any,
    job_id: str,
    adapter_id: str,
    candidate_manifest_sha256: str,
    resolve_repo_path: Callable[[str], Path],
    digest: Callable[[Path], str],
) -> tuple[dict[str, Any], list[str]]:
    """Validate one QualitySpec assessment and build a console-ready projection."""

    try:
        spec = QualitySpec.from_dict(spec_data)
    except (TypeError, ValueError) as exc:
        return {
            "schemaVersion": 1,
            "passed": False,
            "releaseReady": False,
            "errors": [f"spec: {exc}"],
        }, [f"spec: {exc}"]

    errors: list[str] = []
    if not isinstance(assessment, Mapping):
        assessment = {}
        errors.append("assessment")
    bindings = {
        "schemaVersion": assessment.get("schemaVersion") == 1,
        "specId": assessment.get("specId") == spec.spec_id,
        "jobId": assessment.get("jobId") == job_id,
        "adapterId": assessment.get("adapterId") == adapter_id,
        "candidateManifestSha256": assessment.get("candidateManifestSha256")
        == candidate_manifest_sha256,
    }
    errors.extend(name for name, passed in bindings.items() if not passed)

    results_value = assessment.get("results")
    if not isinstance(results_value, Mapping):
        results_value = {}
        errors.append("results")
    submitted_ids = set(results_value)
    expected_submitted = {item.aspect_id for item in spec.aspects if not item.computed}
    for extra in sorted(submitted_ids - expected_submitted):
        errors.append(f"results.unknown:{extra}")

    aspect_projection: dict[str, dict[str, Any]] = {}
    defects: list[dict[str, Any]] = []
    declared_evidence = 0
    verified_evidence = 0
    evidence_errors: list[str] = []

    for aspect in spec.aspects:
        if aspect.computed:
            continue
        prefix = f"results.{aspect.aspect_id}"
        raw = results_value.get(aspect.aspect_id)
        local_errors: list[str] = []
        if not isinstance(raw, Mapping):
            raw = {}
            local_errors.append(prefix)
        declared_status = raw.get("status")
        try:
            status = QualityStatus(declared_status)
        except ValueError:
            status = QualityStatus.FAIL
            local_errors.append(f"{prefix}.status")
        method_value = raw.get("reviewMethod")
        try:
            method = ReviewMethod(method_value)
        except ValueError:
            method = ReviewMethod.AUTOMATED
            local_errors.append(f"{prefix}.reviewMethod")
        if method not in aspect.allowed_methods:
            local_errors.append(f"{prefix}.reviewMethod")
        reviewer = raw.get("reviewer")
        if not _text(reviewer):
            local_errors.append(f"{prefix}.reviewer")
        if not _contains_all(raw.get("targetViews"), aspect.target_views):
            local_errors.append(f"{prefix}.targetViews")
        if not _contains_all(raw.get("targetPoses"), aspect.target_poses):
            local_errors.append(f"{prefix}.targetPoses")

        required_kinds = (
            ()
            if status is QualityStatus.OUT_OF_SCOPE
            else aspect.required_evidence_kinds
        )
        evidence = _audit_evidence(
            value=raw.get("evidence"),
            required_kinds=required_kinds,
            prefix=prefix,
            resolve_repo_path=resolve_repo_path,
            digest=digest,
            require_image_extensions=(
                spec.direct_image_review.allowed_extensions
                if method is ReviewMethod.DIRECT_IMAGE_REVIEW
                else ()
            ),
            allow_empty=status is QualityStatus.OUT_OF_SCOPE,
        )
        local_errors.extend(evidence.errors)
        declared_evidence += evidence.declared
        verified_evidence += evidence.verified
        evidence_errors.extend(evidence.errors)

        metric_value = raw.get("metricValue")
        metric_passed = aspect.metric.passes(metric_value)
        if status is QualityStatus.OUT_OF_SCOPE:
            if not aspect.allow_out_of_scope:
                local_errors.append(f"{prefix}.outOfScopeNotAllowed")
            if not _text(raw.get("outOfScopeReason")):
                local_errors.append(f"{prefix}.outOfScopeReason")
        elif status is QualityStatus.PASS and not metric_passed:
            local_errors.append(f"{prefix}.metricThreshold")
        elif status is QualityStatus.FAIL:
            local_errors.append(f"{prefix}.declaredFailure")

        effective_status = status
        if local_errors:
            effective_status = QualityStatus.FAIL
        if effective_status is QualityStatus.FAIL:
            defects.append(_defect(aspect, local_errors, declared_status))
        aspect_projection[aspect.aspect_id] = {
            "status": effective_status.value,
            "declaredStatus": declared_status,
            "metric": {
                "name": aspect.metric.name,
                "operator": aspect.metric.operator.value,
                "threshold": aspect.metric.threshold,
                "value": metric_value,
                "passed": metric_passed,
            },
            "targetViews": list(raw.get("targetViews", []))
            if isinstance(raw.get("targetViews"), list)
            else [],
            "targetPoses": list(raw.get("targetPoses", []))
            if isinstance(raw.get("targetPoses"), list)
            else [],
            "reviewMethod": method_value,
            "reviewer": reviewer,
            "reviewerReference": raw.get("reviewerReference"),
            "outOfScopeReason": raw.get("outOfScopeReason"),
            "evidence": evidence.normalized,
            "completionGate": aspect.completion_gate,
            "recommendedReturnStage": aspect.return_stage,
            "failedFields": sorted(set(local_errors)),
        }
        errors.extend(local_errors)

    visual, visual_errors, visual_evidence = _validate_visual_review(
        spec=spec,
        value=assessment.get("visualAppearanceReview"),
        resolve_repo_path=resolve_repo_path,
        digest=digest,
    )
    errors.extend(visual_errors)
    evidence_errors.extend(visual_evidence.errors)
    declared_evidence += visual_evidence.declared
    verified_evidence += visual_evidence.verified

    evidence_axis = next(
        item for item in spec.aspects if item.aspect_id == "evidence-completeness"
    )
    evidence_ratio = verified_evidence / declared_evidence if declared_evidence else 0.0
    evidence_passed = not evidence_errors and declared_evidence > 0
    evidence_status = QualityStatus.PASS if evidence_passed else QualityStatus.FAIL
    evidence_reasons = sorted(set(evidence_errors))
    if not evidence_passed and not evidence_reasons:
        evidence_reasons = ["evidence-completeness: no evidence declared"]
    if not evidence_passed:
        defects.append(_defect(evidence_axis, evidence_reasons, None))
        errors.extend(evidence_reasons)
    aspect_projection[evidence_axis.aspect_id] = {
        "status": evidence_status.value,
        "declaredStatus": None,
        "metric": {
            "name": evidence_axis.metric.name,
            "operator": evidence_axis.metric.operator.value,
            "threshold": evidence_axis.metric.threshold,
            "value": evidence_ratio,
            "passed": evidence_passed,
        },
        "targetViews": list(evidence_axis.target_views),
        "targetPoses": list(evidence_axis.target_poses),
        "reviewMethod": ReviewMethod.AUTOMATED.value,
        "reviewer": "tool:quality-spec-validator",
        "reviewerReference": None,
        "outOfScopeReason": None,
        "evidence": [],
        "completionGate": evidence_axis.completion_gate,
        "recommendedReturnStage": evidence_axis.return_stage,
        "failedFields": evidence_reasons,
    }

    unique_errors = sorted(set(errors))
    failed_aspects = sorted(
        aspect_id
        for aspect_id, result in aspect_projection.items()
        if result["status"] == QualityStatus.FAIL.value
    )
    out_of_scope_aspects = sorted(
        aspect_id
        for aspect_id, result in aspect_projection.items()
        if result["status"] == QualityStatus.OUT_OF_SCOPE.value
    )
    passed = not unique_errors and not failed_aspects and visual["status"] == "PASS"
    projection = {
        "schemaVersion": 1,
        "specId": spec.spec_id,
        "completionGate": spec.completion_gate,
        "candidateManifestSha256": assessment.get("candidateManifestSha256"),
        "passed": passed,
        "releaseReady": passed,
        "aspects": aspect_projection,
        "visualAppearanceReview": visual,
        "defects": defects,
        "defectTaxonomy": {
            item.aspect_id: {
                "code": item.defect_code,
                "recommendedReturnStage": item.return_stage,
                "completionGate": item.completion_gate,
            }
            for item in spec.aspects
        },
        "failedAspects": failed_aspects,
        "outOfScopeAspects": out_of_scope_aspects,
        "evidenceSummary": {
            "hashAlgorithm": spec.hash_algorithm,
            "declared": declared_evidence,
            "verified": verified_evidence,
            "verificationRatio": evidence_ratio,
        },
        "errors": unique_errors,
    }
    return projection, unique_errors
