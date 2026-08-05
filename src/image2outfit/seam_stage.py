"""Edge-addressed seam graph hypotheses and structural audits."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import StrEnum

from .construction import ConstructionComponentKind
from .domain import PatternEdgeRole
from .pattern_stage import PatternHypothesis, PatternHypothesisSet


class SeamType(StrEnum):
    PLAIN = "plain"
    FLAT_FELLED = "flat-felled"
    OVERLOCK = "overlock"
    BOUND = "bound"
    ZIPPER = "zipper"
    BUTTONED = "buttoned"
    ELASTIC = "elastic"


class EaseDistribution(StrEnum):
    UNIFORM = "uniform"
    CENTER = "center"
    ENDS = "ends"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class SeamConnection:
    connection_id: str
    first_edge_id: str
    second_edge_id: str
    seam_type: SeamType
    ease_ratio: float = 1.0
    ease_distribution: EaseDistribution = EaseDistribution.UNIFORM
    gather_ratio: float = 1.0
    first_start_matches_second_start: bool = False
    hidden: bool = False

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.connection_id,
                self.first_edge_id,
                self.second_edge_id,
            )
        ):
            raise ValueError("seam connection identity fields are required")
        if self.first_edge_id == self.second_edge_id:
            raise ValueError("seam connection requires two distinct edges")
        if not math.isfinite(self.ease_ratio) or self.ease_ratio <= 0:
            raise ValueError("seam ease_ratio must be finite and positive")
        if not math.isfinite(self.gather_ratio) or self.gather_ratio < 1:
            raise ValueError("seam gather_ratio must be finite and at least one")
        if self.gather_ratio > 1 and self.ease_distribution is EaseDistribution.CUSTOM:
            raise ValueError("custom gather distribution requires an external profile")


@dataclass(frozen=True, slots=True)
class SeamGraphDefect:
    code: str
    connection_id: str | None
    edge_ids: tuple[str, ...]
    detail: str


@dataclass(frozen=True, slots=True)
class SeamHypothesis:
    hypothesis_id: str
    pattern_hypothesis_id: str
    connections: tuple[SeamConnection, ...]
    intentional_open_edge_ids: tuple[str, ...]
    confidence: float
    parent_hypothesis_id: str | None = None

    def __post_init__(self) -> None:
        if not self.hypothesis_id.strip() or not self.pattern_hypothesis_id.strip():
            raise ValueError("seam hypothesis identity fields are required")
        if self.parent_hypothesis_id == self.hypothesis_id:
            raise ValueError("seam hypothesis cannot be its own parent")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("seam hypothesis confidence must be between zero and one")
        connection_ids = [item.connection_id for item in self.connections]
        if len(connection_ids) != len(set(connection_ids)):
            raise ValueError("seam connection IDs must be unique")
        if len(self.intentional_open_edge_ids) != len(
            set(self.intentional_open_edge_ids)
        ):
            raise ValueError("intentional open edge IDs must be unique")

    def audit(
        self,
        pattern: PatternHypothesis,
        *,
        relative_length_tolerance: float = 0.05,
    ) -> tuple[SeamGraphDefect, ...]:
        if pattern.hypothesis_id != self.pattern_hypothesis_id:
            raise ValueError("seam hypothesis references another pattern hypothesis")
        edge_map = pattern.construction.edge_by_id
        defects: list[SeamGraphDefect] = []
        usage: dict[str, list[str]] = {}
        for connection in self.connections:
            unknown = sorted(
                {
                    connection.first_edge_id,
                    connection.second_edge_id,
                }.difference(edge_map)
            )
            if unknown:
                defects.append(
                    SeamGraphDefect(
                        "unknown-edge",
                        connection.connection_id,
                        tuple(unknown),
                        "connection references undeclared pattern edges",
                    )
                )
                continue
            for edge_id in (connection.first_edge_id, connection.second_edge_id):
                usage.setdefault(edge_id, []).append(connection.connection_id)
            first_piece, first_edge = edge_map[connection.first_edge_id]
            second_piece, second_edge = edge_map[connection.second_edge_id]
            first_length = pattern.construction._edge_length(first_piece, first_edge)
            second_length = pattern.construction._edge_length(second_piece, second_edge)
            expected_second = (
                second_length * connection.ease_ratio * connection.gather_ratio
            )
            denominator = max(first_length, expected_second, 1e-12)
            if (
                abs(first_length - expected_second) / denominator
                > relative_length_tolerance
            ):
                defects.append(
                    SeamGraphDefect(
                        "edge-length",
                        connection.connection_id,
                        (connection.first_edge_id, connection.second_edge_id),
                        "edge lengths exceed declared ease and gather tolerance",
                    )
                )
            first_vector = pattern.construction._edge_vector(first_piece, first_edge)
            second_vector = pattern.construction._edge_vector(second_piece, second_edge)
            dot = sum(
                left * right for left, right in zip(first_vector, second_vector)
            )
            should_share_direction = connection.first_start_matches_second_start
            if should_share_direction == (dot < 0):
                defects.append(
                    SeamGraphDefect(
                        "orientation",
                        connection.connection_id,
                        (connection.first_edge_id, connection.second_edge_id),
                        "edge direction contradicts endpoint correspondence",
                    )
                )
            component_kinds = {
                component.kind
                for component in pattern.construction.components
                if first_piece.piece_id in component.piece_ids
                or second_piece.piece_id in component.piece_ids
            }
            if (
                connection.seam_type is SeamType.ZIPPER
                and ConstructionComponentKind.ZIPPER not in component_kinds
            ):
                defects.append(
                    SeamGraphDefect(
                        "missing-component",
                        connection.connection_id,
                        (connection.first_edge_id, connection.second_edge_id),
                        "zipper seam requires a zipper construction component",
                    )
                )
        for edge_id, connection_ids in sorted(usage.items()):
            if len(connection_ids) > 1:
                defects.append(
                    SeamGraphDefect(
                        "over-sewn-edge",
                        None,
                        (edge_id,),
                        f"edge is used by connections {sorted(connection_ids)}",
                    )
                )
        open_edges = set(self.intentional_open_edge_ids)
        unknown_open = sorted(open_edges.difference(edge_map))
        if unknown_open:
            defects.append(
                SeamGraphDefect(
                    "unknown-open-edge",
                    None,
                    tuple(unknown_open),
                    "intentional openings reference undeclared edges",
                )
            )
        required = {
            edge_id
            for edge_id, (_, edge) in edge_map.items()
            if edge.role is PatternEdgeRole.SEAM
        }
        unsewn = sorted(required.difference(usage).difference(open_edges))
        if unsewn:
            defects.append(
                SeamGraphDefect(
                    "unsewn-edge",
                    None,
                    tuple(unsewn),
                    "required seam edges are neither sewn nor intentional openings",
                )
            )
        return tuple(defects)

    def preview_json(self) -> str:
        payload = {
            "hypothesisId": self.hypothesis_id,
            "patternHypothesisId": self.pattern_hypothesis_id,
            "connections": [
                {
                    "connectionId": item.connection_id,
                    "firstEdgeId": item.first_edge_id,
                    "secondEdgeId": item.second_edge_id,
                    "seamType": item.seam_type.value,
                    "easeRatio": item.ease_ratio,
                    "easeDistribution": item.ease_distribution.value,
                    "gatherRatio": item.gather_ratio,
                    "firstStartMatchesSecondStart": (
                        item.first_start_matches_second_start
                    ),
                    "hidden": item.hidden,
                }
                for item in sorted(
                    self.connections,
                    key=lambda value: value.connection_id,
                )
            ],
            "intentionalOpenEdgeIds": sorted(self.intentional_open_edge_ids),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"


@dataclass(frozen=True, slots=True)
class SeamHypothesisSet:
    seam_set_id: str
    pattern_set_id: str
    garment_id: str
    hypotheses: tuple[SeamHypothesis, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (self.seam_set_id, self.pattern_set_id, self.garment_id)
        ):
            raise ValueError("seam set identity fields are required")
        if self.schema_version != 1:
            raise ValueError("unsupported SeamHypothesisSet schema_version")
        if not self.hypotheses:
            raise ValueError("SeamHypothesisSet requires hypotheses")
        identifiers = [item.hypothesis_id for item in self.hypotheses]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("seam hypothesis IDs must be unique")
        known = set(identifiers)
        for hypothesis in self.hypotheses:
            if (
                hypothesis.parent_hypothesis_id is not None
                and hypothesis.parent_hypothesis_id not in known
            ):
                raise ValueError(
                    f"seam hypothesis {hypothesis.hypothesis_id!r} has unknown parent"
                )

    def validate_patterns(self, patterns: PatternHypothesisSet) -> None:
        if patterns.pattern_set_id != self.pattern_set_id:
            raise ValueError("seam set references another pattern set")
        if patterns.garment_id != self.garment_id:
            raise ValueError("seam set references another garment")
        available = {item.hypothesis_id for item in patterns.hypotheses}
        unknown = sorted(
            {item.pattern_hypothesis_id for item in self.hypotheses}.difference(
                available
            )
        )
        if unknown:
            raise ValueError(f"seam hypotheses reference unknown patterns: {unknown}")
