"""Auditable Stage 09 skin-weight transfer artifacts and deterministic repair."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Sequence


class WeightTransferMethod(StrEnum):
    BLENDER_DATA_TRANSFER = "blender-data-transfer"
    ROBUST_WEIGHT_TRANSFER = "robust-weight-transfer"
    RESEARCH_ADAPTER = "research-adapter"


@dataclass(frozen=True, slots=True)
class VertexWeight:
    bone: str
    weight: float

    def __post_init__(self) -> None:
        if not self.bone.strip():
            raise ValueError("bone is required")
        if not math.isfinite(self.weight) or self.weight < 0:
            raise ValueError("weight must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class WeightRepairResult:
    weights: tuple[tuple[VertexWeight, ...], ...]
    zero_weight_vertices: tuple[int, ...]
    non_normalized_vertices: tuple[int, ...]
    rejected_bone_groups: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WeightTransferArtifact:
    source_mesh_hash: str
    target_mesh_hash: str
    armature_hash: str
    bind_pose_hash: str
    method: WeightTransferMethod
    method_version: str
    parameters: Mapping[str, Any]
    vertex_group_hash: str
    influence_histogram: Mapping[int, int]
    zero_weight_vertices: tuple[int, ...]
    non_normalized_vertices: tuple[int, ...]
    left_right_contamination: tuple[int, ...]
    rejected_bone_groups: tuple[str, ...]
    pose_evidence: Mapping[str, str]
    metrics: Mapping[str, float]
    warnings: tuple[str, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported WeightTransferArtifact schema_version")
        for label, value in (
            ("source_mesh_hash", self.source_mesh_hash),
            ("target_mesh_hash", self.target_mesh_hash),
            ("armature_hash", self.armature_hash),
            ("bind_pose_hash", self.bind_pose_hash),
            ("method_version", self.method_version),
            ("vertex_group_hash", self.vertex_group_hash),
        ):
            if not value.strip():
                raise ValueError(f"{label} is required")
        if any(key < 0 or value < 0 for key, value in self.influence_histogram.items()):
            raise ValueError("influence histogram values must be non-negative")
        for collection in (
            self.zero_weight_vertices,
            self.non_normalized_vertices,
            self.left_right_contamination,
        ):
            if any(index < 0 for index in collection):
                raise ValueError("vertex indices must be non-negative")
        if any(not math.isfinite(value) for value in self.metrics.values()):
            raise ValueError("metrics must be finite")

    @property
    def release_ready(self) -> bool:
        return not (
            self.zero_weight_vertices
            or self.non_normalized_vertices
            or self.left_right_contamination
            or self.rejected_bone_groups
        ) and max(self.influence_histogram, default=0) <= 4


def repair_vertex_weights(
    vertices: Sequence[Sequence[VertexWeight]],
    *,
    deform_bones: set[str],
    max_influences: int = 4,
    normalization_tolerance: float = 1e-6,
) -> WeightRepairResult:
    if max_influences <= 0:
        raise ValueError("max_influences must be positive")
    repaired: list[tuple[VertexWeight, ...]] = []
    zero_weight: list[int] = []
    non_normalized: list[int] = []
    rejected: set[str] = set()

    for vertex_index, raw_weights in enumerate(vertices):
        combined: dict[str, float] = {}
        for item in raw_weights:
            if item.bone not in deform_bones:
                rejected.add(item.bone)
                continue
            if item.weight > 0:
                combined[item.bone] = combined.get(item.bone, 0.0) + item.weight
        selected = sorted(combined.items(), key=lambda item: (-item[1], item[0]))[
            :max_influences
        ]
        total = sum(weight for _, weight in selected)
        if total <= normalization_tolerance:
            zero_weight.append(vertex_index)
            repaired.append(())
            continue
        normalized = tuple(
            VertexWeight(bone=bone, weight=weight / total) for bone, weight in selected
        )
        if abs(sum(item.weight for item in normalized) - 1.0) > normalization_tolerance:
            non_normalized.append(vertex_index)
        repaired.append(normalized)

    return WeightRepairResult(
        weights=tuple(repaired),
        zero_weight_vertices=tuple(zero_weight),
        non_normalized_vertices=tuple(non_normalized),
        rejected_bone_groups=tuple(sorted(rejected)),
    )


def detect_left_right_contamination(
    vertices: Sequence[Sequence[VertexWeight]],
    *,
    vertex_sides: Sequence[str],
    center_bones: set[str] | None = None,
    threshold: float = 1e-6,
) -> tuple[int, ...]:
    if len(vertices) != len(vertex_sides):
        raise ValueError("vertex_sides must align with vertices")
    centers = center_bones or set()
    contaminated: list[int] = []
    for index, (weights, side) in enumerate(zip(vertices, vertex_sides, strict=True)):
        if side not in {"left", "right", "center"}:
            raise ValueError("vertex side must be left, right, or center")
        if side == "center":
            continue
        forbidden_suffix = ".R" if side == "left" else ".L"
        if any(
            item.weight > threshold
            and item.bone not in centers
            and item.bone.endswith(forbidden_suffix)
            for item in weights
        ):
            contaminated.append(index)
    return tuple(contaminated)


def vertex_group_digest(vertices: Sequence[Sequence[VertexWeight]]) -> str:
    payload = [
        [[item.bone, round(item.weight, 12)] for item in weights]
        for weights in vertices
    ]
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def influence_histogram(
    vertices: Sequence[Sequence[VertexWeight]],
) -> dict[int, int]:
    histogram: dict[int, int] = {}
    for weights in vertices:
        count = len(weights)
        histogram[count] = histogram.get(count, 0) + 1
    return histogram
