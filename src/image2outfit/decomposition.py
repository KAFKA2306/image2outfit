"""Garment-part observations and structural hypotheses for decompose-garment."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping

from .domain import (
    ConstructionRole,
    GarmentLocation,
    GarmentPartKind,
    LayerPosition,
)
from .normalization import NormalizedReferenceSet

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_EXTENSION = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)+$")


class ObservationState(StrEnum):
    VISIBLE = "visible"
    OCCLUDED = "occluded"
    INFERRED = "inferred"


class PartRelationKind(StrEnum):
    CONNECTED_TO = "connected-to"
    CONTAINS = "contains"
    OVERLAPS = "overlaps"
    INSIDE = "inside"
    CLOSES_WITH = "closes-with"
    LAYERED_OVER = "layered-over"


@dataclass(frozen=True, slots=True)
class PartObservation:
    part_id: str
    kind: GarmentPartKind
    locations: tuple[GarmentLocation, ...]
    construction_role: ConstructionRole
    layer: LayerPosition
    state: ObservationState
    confidence: float
    source_view_ids: tuple[str, ...]
    mask_references: tuple[str, ...] = ()
    extension_kind: str | None = None

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.part_id):
            raise ValueError("part_id must be kebab-case")
        if not self.locations:
            raise ValueError("part observation requires garment locations")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("part confidence must be between zero and one")
        if not self.source_view_ids:
            raise ValueError("part observation requires source views")
        if len(self.source_view_ids) != len(set(self.source_view_ids)):
            raise ValueError("part source view IDs must be unique")
        if self.state is ObservationState.VISIBLE and not self.mask_references:
            raise ValueError("visible parts require mask references")
        if self.state is not ObservationState.VISIBLE and self.confidence >= 1:
            raise ValueError("occluded and inferred parts cannot be certain")
        if self.extension_kind is not None and not _EXTENSION.fullmatch(
            self.extension_kind
        ):
            raise ValueError("extension_kind must be namespaced")


@dataclass(frozen=True, slots=True)
class PartRelation:
    relation_id: str
    kind: PartRelationKind
    source_part_id: str
    target_part_id: str
    confidence: float
    source_view_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.relation_id):
            raise ValueError("relation_id must be kebab-case")
        if self.source_part_id == self.target_part_id:
            raise ValueError("part relation cannot target itself")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("relation confidence must be between zero and one")
        if not self.source_view_ids:
            raise ValueError("part relation requires source views")


@dataclass(frozen=True, slots=True)
class DecompositionHypothesis:
    hypothesis_id: str
    parts: tuple[PartObservation, ...]
    relations: tuple[PartRelation, ...]
    parent_hypothesis_id: str | None = None
    confidence: float = 0.0
    extensions: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.hypothesis_id):
            raise ValueError("hypothesis_id must be kebab-case")
        if self.parent_hypothesis_id is not None:
            if not _IDENTIFIER.fullmatch(self.parent_hypothesis_id):
                raise ValueError("parent_hypothesis_id must be kebab-case")
            if self.parent_hypothesis_id == self.hypothesis_id:
                raise ValueError("hypothesis cannot be its own parent")
        if not self.parts:
            raise ValueError("decomposition hypothesis requires parts")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("hypothesis confidence must be between zero and one")
        part_ids = [item.part_id for item in self.parts]
        if len(part_ids) != len(set(part_ids)):
            raise ValueError("part IDs must be unique within a hypothesis")
        relation_ids = [item.relation_id for item in self.relations]
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("relation IDs must be unique within a hypothesis")
        known_parts = set(part_ids)
        for relation in self.relations:
            unknown = {
                relation.source_part_id,
                relation.target_part_id,
            }.difference(known_parts)
            if unknown:
                raise ValueError(
                    f"relation {relation.relation_id!r} references unknown parts: "
                    f"{sorted(unknown)}"
                )
        for namespace in self.extensions:
            if not _EXTENSION.fullmatch(namespace):
                raise ValueError("decomposition extensions must be namespaced")

    @property
    def asymmetric_part_ids(self) -> tuple[str, ...]:
        by_kind: dict[tuple[object, object], set[object]] = {}
        for part in self.parts:
            for location in part.locations:
                key = (part.kind, location.body_region)
                by_kind.setdefault(key, set()).add(location.laterality)
        asymmetric: set[str] = set()
        for part in self.parts:
            for location in part.locations:
                key = (part.kind, location.body_region)
                laterality = by_kind[key]
                if len(laterality) == 1 and location.laterality.value in {
                    "left",
                    "right",
                }:
                    asymmetric.add(part.part_id)
        return tuple(sorted(asymmetric))


@dataclass(frozen=True, slots=True)
class GarmentDecomposition:
    decomposition_id: str
    normalized_set_id: str
    garment_id: str
    hypotheses: tuple[DecompositionHypothesis, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        for value in (
            self.decomposition_id,
            self.normalized_set_id,
            self.garment_id,
        ):
            if not value.strip():
                raise ValueError("decomposition identity fields are required")
        if self.schema_version != 1:
            raise ValueError("unsupported GarmentDecomposition schema_version")
        if not self.hypotheses:
            raise ValueError("GarmentDecomposition requires hypotheses")
        identifiers = [item.hypothesis_id for item in self.hypotheses]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("decomposition hypothesis IDs must be unique")
        known = set(identifiers)
        for hypothesis in self.hypotheses:
            if (
                hypothesis.parent_hypothesis_id is not None
                and hypothesis.parent_hypothesis_id not in known
            ):
                raise ValueError(
                    f"hypothesis {hypothesis.hypothesis_id!r} has unknown parent"
                )

    def validate_sources(self, normalized: NormalizedReferenceSet) -> None:
        if normalized.normalized_set_id != self.normalized_set_id:
            raise ValueError("decomposition references another normalized set")
        if normalized.garment_id != self.garment_id:
            raise ValueError("decomposition references another garment")
        available = {item.normalized_view_id for item in normalized.views}
        referenced = {
            view_id
            for hypothesis in self.hypotheses
            for part in hypothesis.parts
            for view_id in part.source_view_ids
        } | {
            view_id
            for hypothesis in self.hypotheses
            for relation in hypothesis.relations
            for view_id in relation.source_view_ids
        }
        unknown = sorted(referenced.difference(available))
        if unknown:
            raise ValueError(f"decomposition references unknown views: {unknown}")

    def ranked_hypotheses(self) -> tuple[DecompositionHypothesis, ...]:
        return tuple(
            sorted(
                self.hypotheses,
                key=lambda item: (-item.confidence, item.hypothesis_id),
            )
        )
