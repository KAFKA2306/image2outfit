"""Immutable planning artifacts for blueprint-guided garment experiments."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any

from .pipeline import PipelineStage

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BLUEPRINT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_PRODUCT_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
REGION_KINDS = frozenset(
    {"cloth", "hard-surface", "trim", "decoration", "material", "body-interface"}
)
EPISTEMIC_STATUSES = frozenset({"observed", "inferred", "unknown"})


class BlueprintRole(StrEnum):
    INITIAL_DESIGN = "initial-design"
    TURNAROUND = "turnaround"
    MESH_DRAFT = "mesh-draft"
    BLENDER_CLEANUP = "blender-cleanup"
    RENDER_BACK = "render-back"
    SEMANTIC_MASK = "semantic-mask"
    TEXTURE_AUTHORING = "texture-authoring"


class BlueprintOutcome(StrEnum):
    PASS = "PASS"
    REVISE = "REVISE"
    REJECT = "REJECT"
    RETURN_STAGE = "RETURN_STAGE"


ROLE_STAGE: dict[BlueprintRole, PipelineStage] = {
    BlueprintRole.INITIAL_DESIGN: PipelineStage.DECOMPOSE_GARMENT,
    BlueprintRole.TURNAROUND: PipelineStage.NORMALIZE_VIEW,
    BlueprintRole.MESH_DRAFT: PipelineStage.INITIALIZE_3D,
    BlueprintRole.BLENDER_CLEANUP: PipelineStage.BUILD_BLENDER,
    BlueprintRole.RENDER_BACK: PipelineStage.RENDER_EVIDENCE,
    BlueprintRole.SEMANTIC_MASK: PipelineStage.RENDER_EVIDENCE,
    BlueprintRole.TEXTURE_AUTHORING: PipelineStage.RENDER_EVIDENCE,
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest_blueprint(value: Mapping[str, Any]) -> str:
    """Return the identity used to freeze a blueprint revision before execution."""
    return hashlib.sha256(canonical_json(dict(value)).encode("utf-8")).hexdigest()


def _string_list(value: object, label: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        errors.append(f"{label} must be a string list")
        return []
    return list(value)


def _artifact_ref(value: object, label: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return
    if set(value) != {"path", "sha256"}:
        errors.append(f"{label} must contain only path and sha256")
        return
    if not isinstance(value.get("path"), str) or not value["path"]:
        errors.append(f"{label}.path is required")
    digest = value.get("sha256")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        errors.append(f"{label}.sha256 must be a lowercase SHA-256 digest")


def validate_blueprint(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the blueprint schema plus role/stage and revision semantics."""
    errors: list[str] = []
    if value.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")

    blueprint_id = value.get("blueprintId")
    if not isinstance(blueprint_id, str) or _BLUEPRINT_ID.fullmatch(blueprint_id) is None:
        errors.append("blueprintId must be a canonical id")
    product_id = value.get("productId")
    if not isinstance(product_id, str) or _PRODUCT_ID.fullmatch(product_id) is None:
        errors.append("productId must be a canonical product slug")
    target_avatar = value.get("targetAvatar")
    if not isinstance(target_avatar, str) or not target_avatar:
        errors.append("targetAvatar is required")
    for field in ("targetAvatarSha256", "sourceReferenceSha256"):
        digest = value.get(field)
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            errors.append(f"{field} must be a lowercase SHA-256 digest")

    role: BlueprintRole | None = None
    try:
        role = BlueprintRole(str(value.get("role")))
    except ValueError:
        errors.append("role is not supported")
    if role is not None and value.get("consumingStage") != ROLE_STAGE[role].value:
        errors.append(
            f"role {role.value} must consume stage {ROLE_STAGE[role].value}"
        )

    revision = value.get("revision")
    parent = value.get("parentBlueprintSha256")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        errors.append("revision must be a positive integer")
    elif revision == 1 and parent is not None:
        errors.append("revision 1 must not declare parentBlueprintSha256")
    elif revision > 1 and (
        not isinstance(parent, str) or _SHA256.fullmatch(parent) is None
    ):
        errors.append("revision > 1 requires parentBlueprintSha256")

    upstream = value.get("upstreamArtifacts")
    if not isinstance(upstream, list):
        errors.append("upstreamArtifacts must be a list")
    else:
        for index, item in enumerate(upstream):
            _artifact_ref(item, f"upstreamArtifacts[{index}]", errors)

    regions = value.get("regions")
    if not isinstance(regions, list):
        errors.append("regions must be a list")
    else:
        ids: list[str] = []
        for index, item in enumerate(regions):
            if not isinstance(item, dict):
                errors.append(f"regions[{index}] must be an object")
                continue
            region_id = item.get("id")
            if not isinstance(region_id, str) or not region_id:
                errors.append(f"regions[{index}].id is required")
            else:
                ids.append(region_id)
            if item.get("epistemicStatus") not in EPISTEMIC_STATUSES:
                errors.append(f"regions[{index}].epistemicStatus is invalid")
            if item.get("kind") not in REGION_KINDS:
                errors.append(f"regions[{index}].kind is invalid")
            if (
                item.get("kind") == "hard-surface"
                and item.get("manualReviewRequired") is not True
            ):
                errors.append(
                    f"hard-surface region {region_id!r} must require manual review"
                )
        if len(ids) != len(set(ids)):
            errors.append("region ids must be unique")

    for field in ("mustPreserve", "allowedFreedom", "knownAmbiguity"):
        _string_list(value.get(field), field, errors)
    expected = _string_list(
        value.get("expectedArtifactKinds"), "expectedArtifactKinds", errors
    )
    if not expected:
        errors.append("expectedArtifactKinds must not be empty")
    elif len(expected) != len(set(expected)):
        errors.append("expectedArtifactKinds must contain unique values")

    review = value.get("reviewImage")
    if review is not None:
        _artifact_ref(review, "reviewImage", errors)
    metadata = value.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        errors.append("metadata must be an object")

    allowed_fields = {
        "schemaVersion",
        "blueprintId",
        "revision",
        "parentBlueprintSha256",
        "role",
        "productId",
        "targetAvatar",
        "targetAvatarSha256",
        "sourceReferenceSha256",
        "consumingStage",
        "upstreamArtifacts",
        "regions",
        "mustPreserve",
        "allowedFreedom",
        "knownAmbiguity",
        "expectedArtifactKinds",
        "reviewImage",
        "metadata",
    }
    unexpected = sorted(set(value) - allowed_fields)
    if unexpected:
        errors.append("unexpected blueprint fields: " + ", ".join(unexpected))

    return {
        "schemaVersion": 1,
        "passed": not errors,
        "errors": errors,
        "blueprintDigest": digest_blueprint(value),
        "role": role.value if role is not None else value.get("role"),
        "consumingStage": value.get("consumingStage"),
    }


def make_blueprint_audit(
    blueprint: Mapping[str, Any],
    *,
    actual_artifact_sha256: str,
    deviations: Sequence[Mapping[str, Any]],
    outcome: BlueprintOutcome | str | None = None,
    return_stage: PipelineStage | str | None = None,
) -> dict[str, Any]:
    """Bind a frozen blueprint to an actual artifact without claiming quality PASS."""
    validation = validate_blueprint(blueprint)
    if not validation["passed"]:
        raise ValueError("invalid blueprint: " + "; ".join(validation["errors"]))
    if _SHA256.fullmatch(actual_artifact_sha256) is None:
        raise ValueError("actual_artifact_sha256 must be a lowercase SHA-256 digest")

    rows = [dict(item) for item in deviations]
    for index, row in enumerate(rows):
        if not isinstance(row.get("metric"), str) or not row["metric"]:
            raise ValueError(f"deviations[{index}].metric is required")
        if not isinstance(row.get("withinTolerance"), bool):
            raise ValueError(f"deviations[{index}].withinTolerance must be boolean")

    inferred = (
        BlueprintOutcome.PASS
        if all(row["withinTolerance"] for row in rows)
        else BlueprintOutcome.REVISE
    )
    selected = inferred if outcome is None else BlueprintOutcome(outcome)
    if selected is BlueprintOutcome.PASS and any(
        not row["withinTolerance"] for row in rows
    ):
        raise ValueError("PASS cannot contain an out-of-tolerance deviation")

    resolved_return_stage: str | None = None
    if selected is BlueprintOutcome.RETURN_STAGE:
        if return_stage is None:
            raise ValueError("RETURN_STAGE requires return_stage")
        resolved_return_stage = PipelineStage(return_stage).value
    elif return_stage is not None:
        raise ValueError("return_stage is only valid with RETURN_STAGE")

    return {
        "schemaVersion": 1,
        "blueprintId": blueprint["blueprintId"],
        "blueprintRevision": blueprint["revision"],
        "blueprintDigest": validation["blueprintDigest"],
        "role": blueprint["role"],
        "consumingStage": blueprint["consumingStage"],
        "actualArtifactSha256": actual_artifact_sha256,
        "deviations": rows,
        "outcome": selected.value,
        "returnStage": resolved_return_stage,
        "qualityPassClaimed": False,
    }
