"""Contracts for blueprint-guided, multi-hypothesis garment reconstruction.

These contracts let external generators contribute bounded hypotheses without
becoming a second pipeline or a source of truth for pattern, seam, quality, or
product completion.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

OBSERVATION_STATES = frozenset({"OBSERVED", "INFERRED", "UNKNOWN"})
SEMANTIC_ROLES = frozenset({"cloth", "trim", "rigid", "accessory", "decoration"})
GENERATION_MODES = frozenset({"pattern-first", "tripo-draft", "manual", "hybrid"})
HYPOTHESIS_SOURCES = frozenset(
    {
        "pattern-first",
        "astra-turnaround",
        "tripo-draft",
        "manual",
        "previous-candidate",
    }
)
AUDIT_DECISIONS = frozenset({"PASS", "REVISE", "REJECT", "RETURN_STAGE"})
EXTERNAL_HYPOTHESIS_SOURCES = frozenset({"astra-turnaround", "tripo-draft"})


def stable_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _sha256(value: object, *, label: str) -> str:
    text = _string(value, label=label)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return text


def _unique_strings(value: object, *, label: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{label} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{label} must not contain duplicates")
    return list(value)


def _mapping(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def validate_target_avatar_authority(
    payload: Mapping[str, Any],
    *,
    expected_avatar_id: str | None = None,
) -> dict[str, Any]:
    """Validate the coordinate/rig authority shared by generated hypotheses."""
    avatar_id = _string(payload.get("avatarId"), label="targetAvatar.avatarId")
    if expected_avatar_id is not None and avatar_id != expected_avatar_id:
        raise ValueError("target avatar identity mismatch")
    source_asset = _string(payload.get("sourceAsset"), label="targetAvatar.sourceAsset")
    t_pose = _string(payload.get("tPoseId"), label="targetAvatar.tPoseId")
    armature = _string(payload.get("armatureId"), label="targetAvatar.armatureId")
    coordinate_system = _string(
        payload.get("coordinateSystem"), label="targetAvatar.coordinateSystem"
    )
    garment_origin = _string(
        payload.get("garmentOriginReference"),
        label="targetAvatar.garmentOriginReference",
    )
    unit_scale = payload.get("unitScaleM")
    if (
        isinstance(unit_scale, bool)
        or not isinstance(unit_scale, (int, float))
        or not math.isfinite(unit_scale)
        or unit_scale <= 0
    ):
        raise ValueError("targetAvatar.unitScaleM must be a positive finite number")
    normalized = {
        "avatarId": avatar_id,
        "sourceAsset": source_asset,
        "tPoseId": t_pose,
        "armatureId": armature,
        "coordinateSystem": coordinate_system,
        "unitScaleM": float(unit_scale),
        "garmentOriginReference": garment_origin,
    }
    return {**normalized, "authoritySha256": stable_sha256(normalized)}


def validate_blueprint(
    payload: Mapping[str, Any],
    *,
    expected_product_id: str,
    expected_source_sha256: str | None = None,
    expected_avatar_id: str | None = None,
) -> dict[str, Any]:
    """Validate a pre-stage planning artifact without treating it as evidence."""
    if payload.get("schemaVersion") != 1:
        raise ValueError("blueprint schemaVersion must be 1")
    if payload.get("productId") != expected_product_id:
        raise ValueError("blueprint product identity mismatch")
    blueprint_id = _string(payload.get("blueprintId"), label="blueprintId")
    revision = payload.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("blueprint revision must be a positive integer")
    source_sha = _sha256(payload.get("sourceSha256"), label="blueprint.sourceSha256")
    if expected_source_sha256 is not None and source_sha != expected_source_sha256:
        raise ValueError("blueprint source hash mismatch")
    consuming_stage = _string(payload.get("consumingStage"), label="consumingStage")
    authority = validate_target_avatar_authority(
        _mapping(payload.get("targetAvatar"), label="targetAvatar"),
        expected_avatar_id=expected_avatar_id,
    )

    observations = payload.get("observations")
    if not isinstance(observations, list) or not observations:
        raise ValueError("blueprint observations must be a non-empty list")
    observation_counts = {state: 0 for state in OBSERVATION_STATES}
    for index, raw in enumerate(observations):
        item = _mapping(raw, label=f"observations[{index}]")
        state = item.get("state")
        if state not in OBSERVATION_STATES:
            raise ValueError(f"observations[{index}].state is invalid")
        _string(item.get("region"), label=f"observations[{index}].region")
        observation_counts[str(state)] += 1

    must_preserve = _unique_strings(
        payload.get("mustPreserveRegions", []), label="mustPreserveRegions"
    )
    allowed_freedom = _unique_strings(
        payload.get("allowedFreedom", []), label="allowedFreedom"
    )
    if set(must_preserve).intersection(allowed_freedom):
        raise ValueError("mustPreserveRegions and allowedFreedom must be disjoint")
    expected_artifacts = _unique_strings(
        payload.get("expectedArtifactKinds", []), label="expectedArtifactKinds"
    )
    if not expected_artifacts:
        raise ValueError("expectedArtifactKinds must not be empty")

    review_image = payload.get("reviewImage")
    if review_image is not None:
        review = _mapping(review_image, label="reviewImage")
        _string(review.get("path"), label="reviewImage.path")
        _sha256(review.get("sha256"), label="reviewImage.sha256")

    return {
        "blueprintId": blueprint_id,
        "revision": revision,
        "sourceSha256": source_sha,
        "consumingStage": consuming_stage,
        "targetAvatarAuthoritySha256": authority["authoritySha256"],
        "observationCounts": observation_counts,
        "mustPreserveRegions": must_preserve,
        "allowedFreedom": allowed_freedom,
        "expectedArtifactKinds": expected_artifacts,
        "blueprintSha256": stable_sha256(payload),
        "isEvidence": False,
    }


def validate_generation_assignments(
    payload: Mapping[str, Any],
    *,
    expected_product_id: str,
) -> dict[str, Any]:
    """Validate semantic garment parts separately from their generation method."""
    if payload.get("schemaVersion") != 1:
        raise ValueError("generation assignment schemaVersion must be 1")
    if payload.get("productId") != expected_product_id:
        raise ValueError("generation assignment product identity mismatch")
    parts = payload.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValueError("generation assignments require parts")
    seen: set[str] = set()
    mode_counts = {mode: 0 for mode in GENERATION_MODES}
    for index, raw in enumerate(parts):
        item = _mapping(raw, label=f"parts[{index}]")
        part_id = _string(item.get("partId"), label=f"parts[{index}].partId")
        if part_id in seen:
            raise ValueError(f"duplicate generation partId: {part_id}")
        seen.add(part_id)
        role = item.get("semanticRole")
        mode = item.get("generationMode")
        if role not in SEMANTIC_ROLES:
            raise ValueError(f"parts[{index}].semanticRole is invalid")
        if mode not in GENERATION_MODES:
            raise ValueError(f"parts[{index}].generationMode is invalid")
        mode_counts[str(mode)] += 1
    return {
        "partCount": len(parts),
        "generationModeCounts": mode_counts,
        "assignmentSha256": stable_sha256(payload),
    }


def validate_hypothesis_set(
    payload: Mapping[str, Any],
    *,
    expected_product_id: str,
    expected_blueprint_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate multiple 3D hypotheses and forbid external drafts as canonical truth."""
    if payload.get("schemaVersion") != 1:
        raise ValueError("hypothesis set schemaVersion must be 1")
    if payload.get("productId") != expected_product_id:
        raise ValueError("hypothesis set product identity mismatch")
    blueprint_sha = _sha256(
        payload.get("blueprintSha256"), label="hypothesisSet.blueprintSha256"
    )
    if expected_blueprint_sha256 is not None and blueprint_sha != expected_blueprint_sha256:
        raise ValueError("hypothesis set blueprint hash mismatch")
    authority_sha = _sha256(
        payload.get("targetAvatarAuthoritySha256"),
        label="hypothesisSet.targetAvatarAuthoritySha256",
    )
    hypotheses = payload.get("hypotheses")
    if not isinstance(hypotheses, list) or not hypotheses:
        raise ValueError("hypothesis set requires at least one hypothesis")
    seen: set[str] = set()
    external_count = 0
    for index, raw in enumerate(hypotheses):
        item = _mapping(raw, label=f"hypotheses[{index}]")
        hypothesis_id = _string(
            item.get("hypothesisId"), label=f"hypotheses[{index}].hypothesisId"
        )
        if hypothesis_id in seen:
            raise ValueError(f"duplicate hypothesisId: {hypothesis_id}")
        seen.add(hypothesis_id)
        source = item.get("source")
        if source not in HYPOTHESIS_SOURCES:
            raise ValueError(f"hypotheses[{index}].source is invalid")
        _sha256(item.get("artifactSha256"), label=f"hypotheses[{index}].artifactSha256")
        if item.get("targetAvatarAuthoritySha256") != authority_sha:
            raise ValueError(f"hypotheses[{index}] target avatar authority mismatch")
        canonical_source = item.get("canonicalSource")
        if not isinstance(canonical_source, bool):
            raise ValueError(f"hypotheses[{index}].canonicalSource must be boolean")
        if source in EXTERNAL_HYPOTHESIS_SOURCES:
            external_count += 1
            if canonical_source:
                raise ValueError("external hypothesis cannot be promoted to canonical source")
            provenance = _mapping(
                item.get("generatorProvenance"),
                label=f"hypotheses[{index}].generatorProvenance",
            )
            _string(provenance.get("tool"), label="generatorProvenance.tool")
            _string(provenance.get("version"), label="generatorProvenance.version")
    selected = _string(payload.get("selectedHypothesisId"), label="selectedHypothesisId")
    if selected not in seen:
        raise ValueError("selectedHypothesisId is not present in hypotheses")
    if payload.get("silentFallbackUsed") is not False:
        raise ValueError("hypothesis selection must record silentFallbackUsed=false")
    return {
        "hypothesisCount": len(hypotheses),
        "externalHypothesisCount": external_count,
        "selectedHypothesisId": selected,
        "targetAvatarAuthoritySha256": authority_sha,
        "hypothesisSetSha256": stable_sha256(payload),
    }


def validate_reconciliation_contract(
    payload: Mapping[str, Any],
    *,
    expected_product_id: str,
) -> dict[str, Any]:
    """Bound Blender cleanup to declared changed/preserved regions and operations."""
    if payload.get("schemaVersion") != 1:
        raise ValueError("reconciliation schemaVersion must be 1")
    if payload.get("productId") != expected_product_id:
        raise ValueError("reconciliation product identity mismatch")
    _sha256(payload.get("blueprintSha256"), label="reconciliation.blueprintSha256")
    _sha256(
        payload.get("hypothesisSetSha256"),
        label="reconciliation.hypothesisSetSha256",
    )
    changed = _unique_strings(payload.get("changedRegions", []), label="changedRegions")
    preserved = _unique_strings(
        payload.get("mustPreserveRegions", []), label="mustPreserveRegions"
    )
    if set(changed).intersection(preserved):
        raise ValueError("changedRegions and mustPreserveRegions must be disjoint")
    allowed = _unique_strings(
        payload.get("allowedOperations", []), label="allowedOperations"
    )
    disallowed = _unique_strings(
        payload.get("disallowedOperations", []), label="disallowedOperations"
    )
    if set(allowed).intersection(disallowed):
        raise ValueError("allowedOperations and disallowedOperations must be disjoint")
    if payload.get("preserveSilhouette") is not True:
        raise ValueError("reconciliation must explicitly preserve silhouette")
    if payload.get("preserveProportions") is not True:
        raise ValueError("reconciliation must explicitly preserve proportions")
    return {
        "changedRegionCount": len(changed),
        "preservedRegionCount": len(preserved),
        "allowedOperationCount": len(allowed),
        "reconciliationSha256": stable_sha256(payload),
    }


def validate_render_back_contract(
    payload: Mapping[str, Any],
    *,
    expected_product_id: str,
) -> dict[str, Any]:
    """Keep AI re-input renders separate from canonical QA evidence."""
    if payload.get("schemaVersion") != 1:
        raise ValueError("render-back schemaVersion must be 1")
    if payload.get("productId") != expected_product_id:
        raise ValueError("render-back product identity mismatch")
    if payload.get("purpose") != "ai-reinput":
        raise ValueError("render-back purpose must be ai-reinput")
    if payload.get("canonicalQualityEvidence") is not False:
        raise ValueError("render-back cannot claim canonical quality evidence")
    protocol = _mapping(payload.get("protocol"), label="render-back.protocol")
    for key in ("camera", "pose", "lighting", "exposure", "resolution", "framing"):
        if key not in protocol:
            raise ValueError(f"render-back protocol is missing {key}")
    return {
        "protocolSha256": stable_sha256(protocol),
        "renderBackSha256": stable_sha256(payload),
        "canonicalQualityEvidence": False,
    }


def validate_blueprint_actual_audit(
    payload: Mapping[str, Any],
    *,
    expected_product_id: str,
) -> dict[str, Any]:
    """Validate measurable blueprint-vs-actual findings and explicit routing."""
    if payload.get("schemaVersion") != 1:
        raise ValueError("blueprint audit schemaVersion must be 1")
    if payload.get("productId") != expected_product_id:
        raise ValueError("blueprint audit product identity mismatch")
    _sha256(payload.get("blueprintSha256"), label="blueprintAudit.blueprintSha256")
    _sha256(payload.get("actualArtifactSha256"), label="blueprintAudit.actualArtifactSha256")
    decision = payload.get("decision")
    if decision not in AUDIT_DECISIONS:
        raise ValueError("blueprint audit decision is invalid")
    deviations = payload.get("deviations")
    if not isinstance(deviations, list):
        raise ValueError("blueprint audit deviations must be a list")
    for index, raw in enumerate(deviations):
        item = _mapping(raw, label=f"deviations[{index}]")
        _string(item.get("metric"), label=f"deviations[{index}].metric")
        status = item.get("status")
        if status not in {"PASS", "FAIL", "NOT_ASSESSABLE"}:
            raise ValueError(f"deviations[{index}].status is invalid")
    return {
        "decision": decision,
        "deviationCount": len(deviations),
        "auditSha256": stable_sha256(payload),
    }
