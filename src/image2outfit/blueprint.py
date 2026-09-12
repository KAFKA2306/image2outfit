"""Immutable planning artifacts for blueprint-guided garment experiments."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .pipeline import PipelineStage

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "pipeline"
    / "blueprint.schema.v1.json"
)


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


def _load_schema() -> dict[str, Any]:
    value = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("blueprint schema must be a JSON object")
    return value


def validate_blueprint(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate structure plus role/stage and immutable revision semantics."""
    errors = [
        error.message
        for error in sorted(
            Draft202012Validator(_load_schema()).iter_errors(dict(value)),
            key=lambda item: list(item.absolute_path),
        )
    ]
    role: BlueprintRole | None = None
    try:
        role = BlueprintRole(str(value.get("role")))
    except ValueError:
        pass
    if role is not None and value.get("consumingStage") != ROLE_STAGE[role].value:
        errors.append(
            f"role {role.value} must consume stage {ROLE_STAGE[role].value}"
        )

    revision = value.get("revision")
    parent = value.get("parentBlueprintSha256")
    if revision == 1 and parent is not None:
        errors.append("revision 1 must not declare parentBlueprintSha256")
    if isinstance(revision, int) and revision > 1 and not isinstance(parent, str):
        errors.append("revision > 1 requires parentBlueprintSha256")

    regions = value.get("regions")
    if isinstance(regions, list):
        ids = [item.get("id") for item in regions if isinstance(item, dict)]
        if len(ids) != len(set(ids)):
            errors.append("region ids must be unique")
        for item in regions:
            if (
                isinstance(item, dict)
                and item.get("kind") == "hard-surface"
                and item.get("manualReviewRequired") is not True
            ):
                errors.append(
                    f"hard-surface region {item.get('id')!r} must require manual review"
                )

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
    """Bind a frozen blueprint to an actual artifact without treating it as quality PASS."""
    validation = validate_blueprint(blueprint)
    if not validation["passed"]:
        raise ValueError("invalid blueprint: " + "; ".join(validation["errors"]))
    if len(actual_artifact_sha256) != 64 or any(
        char not in "0123456789abcdef" for char in actual_artifact_sha256
    ):
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
