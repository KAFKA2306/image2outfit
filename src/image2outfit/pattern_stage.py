"""Pattern hypotheses, geometry audits, provenance, and CAD previews."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

from .construction import ConstructionSpec
from .decomposition import GarmentDecomposition
from .domain import PatternPiece

Point2 = tuple[float, float]


def _orientation(first: Point2, second: Point2, third: Point2) -> float:
    return (second[0] - first[0]) * (third[1] - first[1]) - (
        second[1] - first[1]
    ) * (third[0] - first[0])


def _segments_intersect(
    first_start: Point2,
    first_end: Point2,
    second_start: Point2,
    second_end: Point2,
) -> bool:
    values = (
        _orientation(first_start, first_end, second_start),
        _orientation(first_start, first_end, second_end),
        _orientation(second_start, second_end, first_start),
        _orientation(second_start, second_end, first_end),
    )
    return values[0] * values[1] < 0 and values[2] * values[3] < 0


def _polygon_area(boundary: tuple[Point2, ...]) -> float:
    return abs(
        sum(
            first[0] * second[1] - second[0] * first[1]
            for first, second in zip(boundary, boundary[1:] + boundary[:1])
        )
    ) / 2


def _edge_lengths(boundary: tuple[Point2, ...]) -> tuple[float, ...]:
    return tuple(
        math.dist(first, second)
        for first, second in zip(boundary, boundary[1:] + boundary[:1])
    )


def _minimum_angle_degrees(boundary: tuple[Point2, ...]) -> float:
    angles = []
    for previous, current, following in zip(
        boundary[-1:] + boundary[:-1],
        boundary,
        boundary[1:] + boundary[:1],
    ):
        first = (previous[0] - current[0], previous[1] - current[1])
        second = (following[0] - current[0], following[1] - current[1])
        first_length = math.hypot(*first)
        second_length = math.hypot(*second)
        if first_length == 0 or second_length == 0:
            return 0.0
        cosine = sum(left * right for left, right in zip(first, second)) / (
            first_length * second_length
        )
        angles.append(math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
    return min(angles)


def _self_intersections(piece: PatternPiece) -> tuple[tuple[int, int], ...]:
    boundary = piece.boundary
    count = len(boundary)
    intersections = []
    for first in range(count):
        first_next = (first + 1) % count
        for second in range(first + 1, count):
            second_next = (second + 1) % count
            if len({first, first_next, second, second_next}) < 4:
                continue
            if first == 0 and second_next == 0:
                continue
            if _segments_intersect(
                boundary[first],
                boundary[first_next],
                boundary[second],
                boundary[second_next],
            ):
                intersections.append((first, second))
    return tuple(intersections)


@dataclass(frozen=True, slots=True)
class DimensionSource:
    dimension_id: str
    piece_id: str
    value_mm: float
    avatar_measurement_id: str
    ease_target_id: str

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.dimension_id,
                self.piece_id,
                self.avatar_measurement_id,
                self.ease_target_id,
            )
        ):
            raise ValueError("dimension source identity fields are required")
        if not math.isfinite(self.value_mm) or self.value_mm <= 0:
            raise ValueError("dimension source value_mm must be finite and positive")


@dataclass(frozen=True, slots=True)
class PatternReprojectionEvidence:
    source_view_id: str
    piece_id: str
    mean_error_px: float
    maximum_error_px: float
    evidence_path: str
    evidence_sha256: str

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.source_view_id,
                self.piece_id,
                self.evidence_path,
                self.evidence_sha256,
            )
        ):
            raise ValueError("pattern reprojection evidence fields are required")
        if any(
            not math.isfinite(value) or value < 0
            for value in (self.mean_error_px, self.maximum_error_px)
        ):
            raise ValueError("pattern reprojection errors must be non-negative")
        if self.maximum_error_px < self.mean_error_px:
            raise ValueError("maximum reprojection error cannot be below mean")


@dataclass(frozen=True, slots=True)
class PatternGeometryDefect:
    piece_id: str
    code: str
    value: float
    threshold: float


@dataclass(frozen=True, slots=True)
class PatternHypothesis:
    hypothesis_id: str
    decomposition_hypothesis_id: str
    construction: ConstructionSpec
    dimensions: tuple[DimensionSource, ...]
    reprojection: tuple[PatternReprojectionEvidence, ...]
    hidden_fields: tuple[str, ...]
    confidence: float
    parent_hypothesis_id: str | None = None

    def __post_init__(self) -> None:
        if (
            not self.hypothesis_id.strip()
            or not self.decomposition_hypothesis_id.strip()
        ):
            raise ValueError("pattern hypothesis identity fields are required")
        if self.parent_hypothesis_id == self.hypothesis_id:
            raise ValueError("pattern hypothesis cannot be its own parent")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("pattern hypothesis confidence must be between zero and one")
        if not self.dimensions:
            raise ValueError("pattern hypothesis requires dimension provenance")
        piece_ids = {item.piece_id for item in self.construction.garment.pattern_pieces}
        unknown_dimensions = sorted(
            {item.piece_id for item in self.dimensions}.difference(piece_ids)
        )
        unknown_reprojection = sorted(
            {item.piece_id for item in self.reprojection}.difference(piece_ids)
        )
        if unknown_dimensions or unknown_reprojection:
            raise ValueError(
                "pattern provenance references unknown pieces: "
                f"{sorted(set(unknown_dimensions + unknown_reprojection))}"
            )
        if len(self.hidden_fields) != len(set(self.hidden_fields)):
            raise ValueError("hidden pattern fields must be unique")

    def geometry_defects(
        self,
        *,
        minimum_area_m2: float = 1e-6,
        minimum_edge_m: float = 1e-4,
        minimum_angle_degrees: float = 2.0,
    ) -> tuple[PatternGeometryDefect, ...]:
        defects: list[PatternGeometryDefect] = []
        for piece in self.construction.garment.pattern_pieces:
            area = _polygon_area(piece.boundary)
            if area < minimum_area_m2:
                defects.append(
                    PatternGeometryDefect(
                        piece.piece_id,
                        "area",
                        area,
                        minimum_area_m2,
                    )
                )
            minimum_edge = min(_edge_lengths(piece.boundary))
            if minimum_edge < minimum_edge_m:
                defects.append(
                    PatternGeometryDefect(
                        piece.piece_id,
                        "edge-length",
                        minimum_edge,
                        minimum_edge_m,
                    )
                )
            minimum_angle = _minimum_angle_degrees(piece.boundary)
            if minimum_angle < minimum_angle_degrees:
                defects.append(
                    PatternGeometryDefect(
                        piece.piece_id,
                        "angle",
                        minimum_angle,
                        minimum_angle_degrees,
                    )
                )
            intersections = _self_intersections(piece)
            if intersections:
                defects.append(
                    PatternGeometryDefect(
                        piece.piece_id,
                        "self-intersection",
                        float(len(intersections)),
                        0.0,
                    )
                )
        return tuple(defects)

    def preview_svg(self) -> str:
        return self.construction.preview_svg()

    def preview_json(self) -> str:
        payload = {
            "hypothesisId": self.hypothesis_id,
            "decompositionHypothesisId": self.decomposition_hypothesis_id,
            "dimensions": [
                {
                    "dimensionId": item.dimension_id,
                    "pieceId": item.piece_id,
                    "valueMm": item.value_mm,
                    "avatarMeasurementId": item.avatar_measurement_id,
                    "easeTargetId": item.ease_target_id,
                }
                for item in sorted(self.dimensions, key=lambda value: value.dimension_id)
            ],
            "construction": json.loads(self.construction.preview_json()),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"

    def preview_dxf(self) -> str:
        """Return a deterministic ASCII DXF polyline preview in millimetres."""
        lines = ["0", "SECTION", "2", "ENTITIES"]
        for piece in sorted(
            self.construction.garment.pattern_pieces,
            key=lambda value: value.piece_id,
        ):
            lines.extend(
                (
                    "0",
                    "LWPOLYLINE",
                    "8",
                    piece.piece_id,
                    "90",
                    str(len(piece.boundary)),
                    "70",
                    "1",
                )
            )
            for x, y in piece.boundary:
                lines.extend(
                    ("10", f"{x * 1000:.6f}", "20", f"{y * 1000:.6f}")
                )
        lines.extend(("0", "ENDSEC", "0", "EOF"))
        return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class PatternHypothesisSet:
    pattern_set_id: str
    decomposition_id: str
    garment_id: str
    hypotheses: tuple[PatternHypothesis, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (self.pattern_set_id, self.decomposition_id, self.garment_id)
        ):
            raise ValueError("pattern set identity fields are required")
        if self.schema_version != 1:
            raise ValueError("unsupported PatternHypothesisSet schema_version")
        if not self.hypotheses:
            raise ValueError("PatternHypothesisSet requires hypotheses")
        identifiers = [item.hypothesis_id for item in self.hypotheses]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("pattern hypothesis IDs must be unique")
        known = set(identifiers)
        for hypothesis in self.hypotheses:
            if (
                hypothesis.parent_hypothesis_id is not None
                and hypothesis.parent_hypothesis_id not in known
            ):
                raise ValueError(
                    f"pattern hypothesis {hypothesis.hypothesis_id!r} has unknown parent"
                )

    def validate_decomposition(self, decomposition: GarmentDecomposition) -> None:
        if decomposition.decomposition_id != self.decomposition_id:
            raise ValueError("pattern set references another decomposition")
        if decomposition.garment_id != self.garment_id:
            raise ValueError("pattern set references another garment")
        available = {item.hypothesis_id for item in decomposition.hypotheses}
        unknown = sorted(
            {
                item.decomposition_hypothesis_id for item in self.hypotheses
            }.difference(available)
        )
        if unknown:
            raise ValueError(
                f"pattern hypotheses reference unknown decompositions: {unknown}"
            )

    def ranked_hypotheses(self) -> tuple[PatternHypothesis, ...]:
        return tuple(
            sorted(
                self.hypotheses,
                key=lambda item: (-item.confidence, item.hypothesis_id),
            )
        )
