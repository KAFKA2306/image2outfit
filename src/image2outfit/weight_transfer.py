"""Deterministic contracts and audits for Stage 09 garment skin weights."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from typing import Any

_HASH = re.compile(r"^[0-9a-f]{64}$")


class WeightTransferMethod(StrEnum):
    """Supported Stage 09 weight-generation adapters."""

    BLENDER_DATA_TRANSFER = "blender-data-transfer"
    ROBUST_WEIGHT_TRANSFER = "robust-weight-transfer"
    SKINTOKENS = "skintokens"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class BoneInfluence:
    """One bone contribution to one garment vertex."""

    bone: str
    weight: float

    def __post_init__(self) -> None:
        if not self.bone:
            raise ValueError("bone must be a non-empty string")
        if not math.isfinite(self.weight) or self.weight < 0.0:
            raise ValueError("weight must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class WeightTransferPolicy:
    """Release constraints applied after any transfer algorithm."""

    max_influences: int = 4
    minimum_weight: float = 1e-8
    normalization_tolerance: float = 1e-5
    laterality_contamination_limit: float = 0.05

    def __post_init__(self) -> None:
        if self.max_influences < 1:
            raise ValueError("max_influences must be at least one")
        if not math.isfinite(self.minimum_weight) or self.minimum_weight < 0.0:
            raise ValueError("minimum_weight must be finite and non-negative")
        if (
            not math.isfinite(self.normalization_tolerance)
            or self.normalization_tolerance <= 0.0
        ):
            raise ValueError("normalization_tolerance must be finite and positive")
        if (
            not math.isfinite(self.laterality_contamination_limit)
            or not 0.0 <= self.laterality_contamination_limit <= 1.0
        ):
            raise ValueError(
                "laterality_contamination_limit must be between zero and one"
            )


@dataclass(frozen=True, slots=True)
class WeightTransferAudit:
    """Auditable post-transfer quality measurements."""

    vertex_count: int
    zero_weight_vertices: tuple[int, ...]
    input_non_normalized_vertices: tuple[int, ...]
    over_limit_vertices: tuple[int, ...]
    laterality_contamination_vertices: tuple[int, ...]
    rejected_bone_groups: tuple[str, ...]
    influence_histogram: Mapping[int, int]
    maximum_discarded_weight: float
    vertex_group_hash: str

    def __post_init__(self) -> None:
        if self.vertex_count < 0:
            raise ValueError("vertex_count must be non-negative")
        if not _HASH.fullmatch(self.vertex_group_hash):
            raise ValueError("vertex_group_hash must be a lowercase SHA-256 digest")

    @property
    def passed(self) -> bool:
        """Whether constrained weights satisfy release-blocking postconditions."""
        return not (
            self.zero_weight_vertices or self.laterality_contamination_vertices
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "vertexCount": self.vertex_count,
            "zeroWeightVertices": list(self.zero_weight_vertices),
            "inputNonNormalizedVertices": list(
                self.input_non_normalized_vertices
            ),
            "overLimitVertices": list(self.over_limit_vertices),
            "lateralityContaminationVertices": list(
                self.laterality_contamination_vertices
            ),
            "rejectedBoneGroups": list(self.rejected_bone_groups),
            "influenceHistogram": {
                str(key): self.influence_histogram[key]
                for key in sorted(self.influence_histogram)
            },
            "maximumDiscardedWeight": self.maximum_discarded_weight,
            "vertexGroupHash": self.vertex_group_hash,
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class ConstrainedWeights:
    """Normalized per-vertex weights plus their audit."""

    weights: Mapping[int, tuple[BoneInfluence, ...]]
    audit: WeightTransferAudit

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": {
                str(index): [
                    {"bone": influence.bone, "weight": influence.weight}
                    for influence in self.weights[index]
                ]
                for index in sorted(self.weights)
            },
            "audit": self.audit.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class WeightTransferArtifact:
    """Hash-addressed authoritative Stage 09 weight-transfer result."""

    source_mesh_hash: str
    target_mesh_hash: str
    armature_hash: str
    bind_pose_hash: str
    method: WeightTransferMethod | str
    method_version: str
    parameters: Mapping[str, Any]
    result: ConstrainedWeights
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for label, digest in (
            ("source_mesh_hash", self.source_mesh_hash),
            ("target_mesh_hash", self.target_mesh_hash),
            ("armature_hash", self.armature_hash),
            ("bind_pose_hash", self.bind_pose_hash),
        ):
            if not _HASH.fullmatch(digest):
                raise ValueError(f"{label} must be a lowercase SHA-256 digest")
        WeightTransferMethod(self.method)
        if not self.method_version:
            raise ValueError("method_version must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "kind": "weight-transfer-artifact",
            "stage": "skin-and-export",
            "sourceMeshHash": self.source_mesh_hash,
            "targetMeshHash": self.target_mesh_hash,
            "armatureHash": self.armature_hash,
            "bindPoseHash": self.bind_pose_hash,
            "method": WeightTransferMethod(self.method).value,
            "methodVersion": self.method_version,
            "parameters": dict(self.parameters),
            "vertexGroupHash": self.result.audit.vertex_group_hash,
            "audit": self.result.audit.to_dict(),
            "warnings": list(self.warnings),
        }

    def digest(self) -> str:
        return canonical_digest(self.to_dict())


InfluenceInput = BoneInfluence | tuple[str, float]


def canonical_digest(payload: Mapping[str, Any]) -> str:
    """Hash a JSON-compatible mapping using stable key and separator rules."""
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _coerce_influence(value: InfluenceInput) -> BoneInfluence:
    if isinstance(value, BoneInfluence):
        return value
    if (
        not isinstance(value, tuple)
        or len(value) != 2
        or not isinstance(value[0], str)
    ):
        raise TypeError("influences must be BoneInfluence or (bone, weight) tuples")
    return BoneInfluence(value[0], float(value[1]))


def _vertex_group_digest(
    weights: Mapping[int, tuple[BoneInfluence, ...]],
) -> str:
    payload = {
        str(index): [
            [influence.bone, format(influence.weight, ".17g")]
            for influence in weights[index]
        ]
        for index in sorted(weights)
    }
    return canonical_digest(payload)


def constrain_vertex_weights(
    vertices: Mapping[int, Sequence[InfluenceInput]],
    *,
    deform_bones: Iterable[str],
    policy: WeightTransferPolicy = WeightTransferPolicy(),
    expected_laterality: Mapping[int, str] | None = None,
    left_bones: Iterable[str] = (),
    right_bones: Iterable[str] = (),
) -> ConstrainedWeights:
    """Prune, normalize and audit weights from any Stage 09 adapter.

    ``expected_laterality`` may map a vertex to ``left``, ``right`` or
    ``center``. Opposite-side influences are blockers only for explicitly
    lateral vertices; center vertices may legitimately blend both sides.
    """

    deform = frozenset(str(name) for name in deform_bones)
    if not deform or "" in deform:
        raise ValueError("deform_bones must contain non-empty bone names")
    left = frozenset(str(name) for name in left_bones)
    right = frozenset(str(name) for name in right_bones)
    if left & right:
        raise ValueError("left_bones and right_bones must not overlap")
    laterality = dict(expected_laterality or {})
    invalid_laterality = set(laterality.values()) - {"left", "right", "center"}
    if invalid_laterality:
        raise ValueError(
            "expected_laterality values must be left, right or center"
        )

    constrained: dict[int, tuple[BoneInfluence, ...]] = {}
    zero: list[int] = []
    input_non_normalized: list[int] = []
    over_limit: list[int] = []
    contamination: list[int] = []
    rejected: set[str] = set()
    discarded_by_vertex: list[float] = []

    for vertex_index in sorted(vertices):
        if not isinstance(vertex_index, int) or vertex_index < 0:
            raise ValueError("vertex indices must be non-negative integers")

        by_bone: dict[str, list[float]] = {}
        for raw in vertices[vertex_index]:
            influence = _coerce_influence(raw)
            if influence.bone not in deform:
                if influence.weight >= policy.minimum_weight:
                    rejected.add(influence.bone)
                continue
            if influence.weight < policy.minimum_weight:
                continue
            by_bone.setdefault(influence.bone, []).append(influence.weight)

        merged = {
            bone: math.fsum(weights) for bone, weights in by_bone.items()
        }

        valid_total = math.fsum(merged.values())
        if (
            merged
            and abs(valid_total - 1.0) > policy.normalization_tolerance
        ):
            input_non_normalized.append(vertex_index)

        ordered = sorted(
            merged.items(), key=lambda item: (-round(item[1], 15), item[0])
        )
        if len(ordered) > policy.max_influences:
            over_limit.append(vertex_index)
        kept = ordered[: policy.max_influences]
        discarded = sum(weight for _, weight in ordered[policy.max_influences :])
        discarded_by_vertex.append(discarded)

        total = sum(weight for _, weight in kept)
        if total <= policy.minimum_weight:
            constrained[vertex_index] = ()
            zero.append(vertex_index)
            continue

        normalized = tuple(
            BoneInfluence(bone, weight / total) for bone, weight in kept
        )
        constrained[vertex_index] = normalized

        side = laterality.get(vertex_index, "center")
        opposite_weight = 0.0
        if side == "left":
            opposite_weight = math.fsum(
                influence.weight
                for influence in normalized
                if influence.bone in right
            )
        elif side == "right":
            opposite_weight = math.fsum(
                influence.weight
                for influence in normalized
                if influence.bone in left
            )
        if opposite_weight > policy.laterality_contamination_limit:
            contamination.append(vertex_index)

    histogram = Counter(len(items) for items in constrained.values())
    vertex_group_hash = _vertex_group_digest(constrained)
    audit = WeightTransferAudit(
        vertex_count=len(constrained),
        zero_weight_vertices=tuple(zero),
        input_non_normalized_vertices=tuple(input_non_normalized),
        over_limit_vertices=tuple(over_limit),
        laterality_contamination_vertices=tuple(contamination),
        rejected_bone_groups=tuple(sorted(rejected)),
        influence_histogram=dict(sorted(histogram.items())),
        maximum_discarded_weight=max(discarded_by_vertex, default=0.0),
        vertex_group_hash=vertex_group_hash,
    )
    return ConstrainedWeights(weights=constrained, audit=audit)
