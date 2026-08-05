"""Construction details layered on the pattern-first garment domain model."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from .domain import GarmentSpecification, LayerPosition, PatternEdge, PatternPiece


class ConstructionComponentKind(StrEnum):
    SHELL = "shell"
    LINING = "lining"
    INTERFACING = "interfacing"
    PADDING = "padding"
    FACING = "facing"
    RIB = "rib"
    ELASTIC = "elastic"
    BUTTON = "button"
    ZIPPER = "zipper"


@dataclass(frozen=True, slots=True)
class Pleat:
    pleat_id: str
    piece_id: str
    first_fold_edge_id: str
    second_fold_edge_id: str
    intake_mm: float
    direction: str

    def __post_init__(self) -> None:
        if not self.pleat_id or not self.piece_id:
            raise ValueError("pleat IDs are required")
        if not math.isfinite(self.intake_mm) or self.intake_mm <= 0:
            raise ValueError("pleat intake_mm must be finite and positive")
        if self.direction not in {"inverted", "knife-left", "knife-right", "box"}:
            raise ValueError("unsupported pleat direction")


@dataclass(frozen=True, slots=True)
class Gather:
    gather_id: str
    source_edge_id: str
    target_edge_id: str
    ratio: float
    distribution: str = "uniform"

    def __post_init__(self) -> None:
        if not math.isfinite(self.ratio) or self.ratio <= 1:
            raise ValueError("gather ratio must be finite and greater than one")
        if self.distribution not in {"uniform", "center", "ends", "custom"}:
            raise ValueError("unsupported gather distribution")


@dataclass(frozen=True, slots=True)
class ConstructionComponent:
    component_id: str
    kind: ConstructionComponentKind
    layer: LayerPosition
    piece_ids: tuple[str, ...]
    material_id: str

    def __post_init__(self) -> None:
        if not self.component_id or not self.material_id or not self.piece_ids:
            raise ValueError("construction component fields are required")
        if len(self.piece_ids) != len(set(self.piece_ids)):
            raise ValueError("component piece IDs must be unique")


@dataclass(frozen=True, slots=True)
class ConstructionAudit:
    open_seams: tuple[str, ...]
    edge_length_mismatches: tuple[str, ...]
    orientation_mismatches: tuple[str, ...]
    unreferenced_edges: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not any(
            (
                self.open_seams,
                self.edge_length_mismatches,
                self.orientation_mismatches,
                self.unreferenced_edges,
            )
        )


@dataclass(frozen=True, slots=True)
class ConstructionSpec:
    garment: GarmentSpecification
    components: tuple[ConstructionComponent, ...]
    pleats: tuple[Pleat, ...] = ()
    gathers: tuple[Gather, ...] = ()
    intentional_open_edge_ids: tuple[str, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported ConstructionSpec schema_version")
        self.garment.validate()
        piece_ids = {piece.piece_id for piece in self.garment.pattern_pieces}
        edge_ids = {
            edge.edge_id
            for piece in self.garment.pattern_pieces
            for edge in piece.edges
        }
        for component in self.components:
            unknown = sorted(set(component.piece_ids).difference(piece_ids))
            if unknown:
                raise ValueError(
                    f"component {component.component_id!r} references unknown pieces: {unknown}"
                )
        for pleat in self.pleats:
            if pleat.piece_id not in piece_ids:
                raise ValueError(f"pleat {pleat.pleat_id!r} references unknown piece")
            unknown = {
                pleat.first_fold_edge_id,
                pleat.second_fold_edge_id,
            }.difference(edge_ids)
            if unknown:
                raise ValueError(f"pleat {pleat.pleat_id!r} references unknown edges")
        for gather in self.gathers:
            if {gather.source_edge_id, gather.target_edge_id}.difference(edge_ids):
                raise ValueError(
                    f"gather {gather.gather_id!r} references unknown edges"
                )
        if set(self.intentional_open_edge_ids).difference(edge_ids):
            raise ValueError(
                "intentional open edges must reference declared pattern edges"
            )

    @property
    def edge_by_id(self) -> dict[str, tuple[PatternPiece, PatternEdge]]:
        return {
            edge.edge_id: (piece, edge)
            for piece in self.garment.pattern_pieces
            for edge in piece.edges
        }

    @staticmethod
    def _edge_vector(piece: PatternPiece, edge: PatternEdge) -> tuple[float, float]:
        start = piece.boundary[edge.start_vertex]
        end = piece.boundary[edge.end_vertex]
        return end[0] - start[0], end[1] - start[1]

    @classmethod
    def _edge_length(cls, piece: PatternPiece, edge: PatternEdge) -> float:
        x, y = cls._edge_vector(piece, edge)
        return math.hypot(x, y)

    def audit(self, *, relative_length_tolerance: float = 0.05) -> ConstructionAudit:
        edge_map = self.edge_by_id
        stitched_edge_ids: set[str] = set()
        length_mismatches: list[str] = []
        orientation_mismatches: list[str] = []
        open_seams: list[str] = []
        for stitch in self.garment.stitches:
            if stitch.first.edge_id is None or stitch.second.edge_id is None:
                open_seams.append(stitch.stitch_id)
                continue
            stitched_edge_ids.update((stitch.first.edge_id, stitch.second.edge_id))
            first_piece, first_edge = edge_map[stitch.first.edge_id]
            second_piece, second_edge = edge_map[stitch.second.edge_id]
            first_length = self._edge_length(first_piece, first_edge)
            second_length = self._edge_length(second_piece, second_edge)
            expected_second = second_length * stitch.easing_ratio
            denominator = max(first_length, expected_second, 1e-12)
            if (
                abs(first_length - expected_second) / denominator
                > relative_length_tolerance
            ):
                length_mismatches.append(stitch.stitch_id)
            first_vector = self._edge_vector(first_piece, first_edge)
            second_vector = self._edge_vector(second_piece, second_edge)
            dot = sum(left * right for left, right in zip(first_vector, second_vector))
            if dot >= 0:
                orientation_mismatches.append(stitch.stitch_id)
        gathered_edges = {
            edge_id
            for gather in self.gathers
            for edge_id in (gather.source_edge_id, gather.target_edge_id)
        }
        pleat_edges = {
            edge_id
            for pleat in self.pleats
            for edge_id in (pleat.first_fold_edge_id, pleat.second_fold_edge_id)
        }
        used = (
            stitched_edge_ids
            | gathered_edges
            | pleat_edges
            | set(self.intentional_open_edge_ids)
        )
        unreferenced = tuple(sorted(set(edge_map).difference(used)))
        return ConstructionAudit(
            open_seams=tuple(sorted(open_seams)),
            edge_length_mismatches=tuple(sorted(length_mismatches)),
            orientation_mismatches=tuple(sorted(orientation_mismatches)),
            unreferenced_edges=unreferenced,
        )

    def preview_svg(self) -> str:
        """Return deterministic, dependency-free panel preview SVG."""
        pieces = sorted(self.garment.pattern_pieces, key=lambda item: item.piece_id)
        if not pieces:
            raise ValueError("pattern pieces are required for preview")
        margin = 20.0
        cursor_x = margin
        rendered: list[str] = []
        maximum_height = 0.0
        for piece in pieces:
            xs = [point[0] * 1000 for point in piece.boundary]
            ys = [point[1] * 1000 for point in piece.boundary]
            width = max(xs) - min(xs)
            height = max(ys) - min(ys)
            maximum_height = max(maximum_height, height)
            points = " ".join(
                f"{cursor_x + x - min(xs):.3f},{margin + max(ys) - y:.3f}"
                for x, y in zip(xs, ys, strict=True)
            )
            rendered.append(
                f'<polygon id="{piece.piece_id}" points="{points}" '
                'fill="none" stroke="black" />'
            )
            cursor_x += width + margin
        width = cursor_x
        height = maximum_height + 2 * margin
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.3f}" '
            f'height="{height:.3f}" viewBox="0 0 {width:.3f} {height:.3f}">'
            + "".join(rendered)
            + "</svg>\n"
        )

    def preview_json(self) -> str:
        payload: Mapping[str, object] = {
            "schemaVersion": self.schema_version,
            "productId": self.garment.product_id,
            "pieces": [
                {
                    "pieceId": piece.piece_id,
                    "partId": piece.part_id,
                    "boundary": piece.boundary,
                    "grainAngleDegrees": piece.grain_angle_degrees,
                    "correspondenceIds": dict(sorted(piece.correspondence_ids.items())),
                }
                for piece in sorted(
                    self.garment.pattern_pieces, key=lambda item: item.piece_id
                )
            ],
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
