"""Stable garment vocabulary and pattern-first intermediate representation."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Sequence

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


class BodyRegion(StrEnum):
    HEAD = "head"
    NECK = "neck"
    SHOULDER = "shoulder"
    CHEST = "chest"
    UPPER_BACK = "upper-back"
    ABDOMEN = "abdomen"
    WAIST = "waist"
    PELVIS = "pelvis"
    CROTCH = "crotch"
    BUTTOCK = "buttock"
    UPPER_ARM = "upper-arm"
    ELBOW = "elbow"
    FOREARM = "forearm"
    WRIST = "wrist"
    HAND = "hand"
    UPPER_LEG = "upper-leg"
    KNEE = "knee"
    LOWER_LEG = "lower-leg"
    ANKLE = "ankle"
    FOOT = "foot"


class Laterality(StrEnum):
    CENTER = "center"
    LEFT = "left"
    RIGHT = "right"
    BILATERAL = "bilateral"


class SurfaceOrientation(StrEnum):
    FULL = "full"
    FRONT = "front"
    BACK = "back"
    SIDE = "side"
    INNER = "inner"
    OUTER = "outer"
    UPPER = "upper"
    LOWER = "lower"


@dataclass(frozen=True, slots=True)
class GarmentLocation:
    body_region: BodyRegion
    laterality: Laterality = Laterality.CENTER
    surface: SurfaceOrientation = SurfaceOrientation.FULL


class GarmentPartKind(StrEnum):
    FRONT_BODICE_PANEL = "front-bodice-panel"
    BACK_BODICE_PANEL = "back-bodice-panel"
    SIDE_PANEL = "side-panel"
    SHOULDER_YOKE = "shoulder-yoke"
    SLEEVE_CAP = "sleeve-cap"
    SLEEVE = "sleeve"
    CUFF = "cuff"
    COLLAR = "collar"
    HOOD = "hood"
    PLACKET = "placket"
    WAISTBAND = "waistband"
    SKIRT_PANEL = "skirt-panel"
    PELVIC_SADDLE = "pelvic-saddle"
    CROTCH_GUSSET = "crotch-gusset"
    LEG_PANEL = "leg-panel"
    LEG_WARMER = "leg-warmer"
    SHOE_UPPER = "shoe-upper"
    WING_PANEL = "wing-panel"
    TRIM = "trim"
    FASTENER = "fastener"
    CORD = "cord"


class ConstructionRole(StrEnum):
    STRUCTURAL_PANEL = "structural-panel"
    OPENING = "opening"
    REINFORCEMENT = "reinforcement"
    CLOSURE = "closure"
    EDGE_FINISH = "edge-finish"
    TRIM = "trim"
    ACCESSORY = "accessory"


class LayerPosition(StrEnum):
    BASE = "base"
    MID = "mid"
    OUTER = "outer"
    FLOATING = "floating"
    ATTACHED = "attached"


class MaterialBehavior(StrEnum):
    WOVEN = "woven"
    KNIT = "knit"
    RIB_KNIT = "rib-knit"
    STRETCH = "stretch"
    SHEER = "sheer"
    LEATHER_LIKE = "leather-like"
    RIGID_TRIM = "rigid-trim"


class FitProfile(StrEnum):
    COMPRESSION = "compression"
    FITTED = "fitted"
    REGULAR = "regular"
    RELAXED = "relaxed"
    OVERSIZED = "oversized"


class PatternEdgeRole(StrEnum):
    CUT = "cut"
    SEAM = "seam"
    HEM = "hem"
    NECKLINE = "neckline"
    ARMSCYE = "armscye"
    WAISTLINE = "waistline"
    FOLD = "fold"
    OPENING = "opening"
    ATTACHMENT = "attachment"
    DART_LEG = "dart-leg"


class StitchType(StrEnum):
    PLAIN = "plain"
    OVERLOCK = "overlock"
    FLATLOCK = "flatlock"
    BOUND = "bound"
    ATTACHMENT = "attachment"


Vec2 = tuple[float, float]


def _require_identifier(value: str, label: str) -> None:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must be kebab-case: {value!r}")


def _require_finite_point(point: Vec2, label: str) -> None:
    if len(point) != 2 or any(not math.isfinite(number) for number in point):
        raise ValueError(f"{label} must contain two finite coordinates")


def _signed_area(points: Sequence[Vec2]) -> float:
    return 0.5 * sum(
        first[0] * second[1] - second[0] * first[1]
        for first, second in zip(points, (*points[1:], points[0]), strict=True)
    )


def _require_finite_polygon(points: Sequence[Vec2], label: str) -> None:
    if len(points) < 3:
        raise ValueError(f"{label} requires at least three boundary points")
    for index, point in enumerate(points):
        _require_finite_point(point, f"{label} point {index}")
        following = points[(index + 1) % len(points)]
        if point == following:
            raise ValueError(f"{label} contains adjacent duplicate points")
    if abs(_signed_area(points)) <= 1e-12:
        raise ValueError(f"{label} has zero signed area")


@dataclass(frozen=True, slots=True)
class GarmentPart:
    part_id: str
    kind: GarmentPartKind
    body_regions: tuple[BodyRegion, ...]
    construction_role: ConstructionRole
    layer: LayerPosition
    material_behavior: MaterialBehavior
    fit_profile: FitProfile
    locations: tuple[GarmentLocation, ...] = ()
    mirror_of: str | None = None
    attributes: Mapping[str, str | int | float | bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_identifier(self.part_id, "part_id")
        if not self.body_regions:
            raise ValueError(
                f"part {self.part_id!r} must declare at least one body region"
            )
        if self.mirror_of == self.part_id:
            raise ValueError("a part cannot mirror itself")
        declared = set(self.body_regions)
        unknown = sorted(
            {location.body_region for location in self.locations}.difference(declared)
        )
        if unknown:
            raise ValueError(
                f"part {self.part_id!r} locations reference undeclared regions: "
                f"{[value.value for value in unknown]}"
            )
        if len(self.locations) != len(set(self.locations)):
            raise ValueError(f"part {self.part_id!r} locations must be unique")

    @property
    def resolved_locations(self) -> tuple[GarmentLocation, ...]:
        if self.locations:
            return self.locations
        return tuple(GarmentLocation(region) for region in self.body_regions)


@dataclass(frozen=True, slots=True)
class PatternEdge:
    edge_id: str
    piece_id: str
    start_vertex: int
    end_vertex: int
    role: PatternEdgeRole = PatternEdgeRole.CUT
    seam_allowance_m: float = 0.0
    notch_positions: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        _require_identifier(self.edge_id, "edge_id")
        _require_identifier(self.piece_id, "piece_id")
        if self.start_vertex < 0 or self.end_vertex < 0:
            raise ValueError("pattern edge indices must be non-negative")
        if self.start_vertex == self.end_vertex:
            raise ValueError("pattern edge must span two different vertices")
        if not math.isfinite(self.seam_allowance_m) or self.seam_allowance_m < 0:
            raise ValueError("seam_allowance_m must be finite and non-negative")
        if len(self.notch_positions) != len(set(self.notch_positions)):
            raise ValueError("pattern edge notch positions must be unique")
        for position in self.notch_positions:
            if not math.isfinite(position) or not 0 < position < 1:
                raise ValueError(
                    "notch positions must be finite ratios between 0 and 1"
                )


@dataclass(frozen=True, slots=True)
class PatternDart:
    dart_id: str
    piece_id: str
    apex: Vec2
    first_leg_vertex: int
    second_leg_vertex: int
    intake_m: float

    def __post_init__(self) -> None:
        _require_identifier(self.dart_id, "dart_id")
        _require_identifier(self.piece_id, "piece_id")
        _require_finite_point(self.apex, "dart apex")
        if self.first_leg_vertex < 0 or self.second_leg_vertex < 0:
            raise ValueError("dart leg indices must be non-negative")
        if self.first_leg_vertex == self.second_leg_vertex:
            raise ValueError("dart legs must use different vertices")
        if not math.isfinite(self.intake_m) or self.intake_m <= 0:
            raise ValueError("dart intake_m must be finite and positive")


@dataclass(frozen=True, slots=True)
class PatternPiece:
    piece_id: str
    part_id: str
    boundary: tuple[Vec2, ...]
    grain_angle_degrees: float = 0.0
    cut_count: int = 1
    on_fold: bool = False
    edges: tuple[PatternEdge, ...] = ()
    darts: tuple[PatternDart, ...] = ()
    correspondence_ids: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_identifier(self.piece_id, "piece_id")
        _require_identifier(self.part_id, "part_id")
        _require_finite_polygon(self.boundary, f"pattern piece {self.piece_id!r}")
        if not math.isfinite(self.grain_angle_degrees):
            raise ValueError("grain angle must be finite")
        if self.cut_count < 1:
            raise ValueError("cut_count must be positive")

        boundary_size = len(self.boundary)
        edge_ids = [edge.edge_id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError(f"pattern piece {self.piece_id!r} has duplicate edge IDs")
        dart_ids = [dart.dart_id for dart in self.darts]
        if len(dart_ids) != len(set(dart_ids)):
            raise ValueError(f"pattern piece {self.piece_id!r} has duplicate dart IDs")

        for edge in self.edges:
            if edge.piece_id != self.piece_id:
                raise ValueError(
                    f"pattern edge {edge.edge_id!r} references another piece"
                )
            if edge.start_vertex >= boundary_size or edge.end_vertex >= boundary_size:
                raise ValueError(
                    f"pattern edge {edge.edge_id!r} exceeds piece boundary"
                )
        for dart in self.darts:
            if dart.piece_id != self.piece_id:
                raise ValueError(f"dart {dart.dart_id!r} references another piece")
            if (
                dart.first_leg_vertex >= boundary_size
                or dart.second_leg_vertex >= boundary_size
            ):
                raise ValueError(f"dart {dart.dart_id!r} exceeds piece boundary")


@dataclass(frozen=True, slots=True)
class StitchEdge:
    piece_id: str
    start_vertex: int
    end_vertex: int
    edge_id: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.piece_id, "piece_id")
        if self.edge_id is not None:
            _require_identifier(self.edge_id, "edge_id")
        if self.start_vertex < 0 or self.end_vertex < 0:
            raise ValueError("stitch edge indices must be non-negative")
        if self.start_vertex == self.end_vertex:
            raise ValueError("stitch edge must span two different vertices")


@dataclass(frozen=True, slots=True)
class Stitch:
    stitch_id: str
    first: StitchEdge
    second: StitchEdge
    stitch_type: StitchType = StitchType.PLAIN
    easing_ratio: float = 1.0

    def __post_init__(self) -> None:
        _require_identifier(self.stitch_id, "stitch_id")
        if self.first == self.second:
            raise ValueError("a stitch cannot connect an edge to itself")
        if not math.isfinite(self.easing_ratio) or self.easing_ratio <= 0:
            raise ValueError("easing_ratio must be finite and positive")


@dataclass(frozen=True, slots=True)
class GarmentSpecification:
    product_id: str
    target_avatar: str
    source_reference: str
    parts: tuple[GarmentPart, ...]
    pattern_pieces: tuple[PatternPiece, ...] = ()
    stitches: tuple[Stitch, ...] = ()
    research_principles: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_identifier(self.product_id, "product_id")
        if not self.target_avatar.strip():
            raise ValueError("target_avatar is required")
        if not self.source_reference.strip():
            raise ValueError("source_reference is required")
        self.validate()

    def validate(self) -> None:
        part_ids = [part.part_id for part in self.parts]
        piece_ids = [piece.piece_id for piece in self.pattern_pieces]
        stitch_ids = [stitch.stitch_id for stitch in self.stitches]
        for label, values in (
            ("part", part_ids),
            ("pattern piece", piece_ids),
            ("stitch", stitch_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {label} identifiers are not allowed")

        part_set = set(part_ids)
        piece_by_id = {piece.piece_id: piece for piece in self.pattern_pieces}
        explicit_edges = {
            edge.edge_id: edge for piece in self.pattern_pieces for edge in piece.edges
        }
        if sum(len(piece.edges) for piece in self.pattern_pieces) != len(
            explicit_edges
        ):
            raise ValueError("pattern edge identifiers must be globally unique")

        for part in self.parts:
            if part.mirror_of is not None and part.mirror_of not in part_set:
                raise ValueError(
                    f"part {part.part_id!r} mirrors unknown part {part.mirror_of!r}"
                )
        for piece in self.pattern_pieces:
            if piece.part_id not in part_set:
                raise ValueError(
                    f"pattern piece {piece.piece_id!r} references unknown part"
                )
        for stitch in self.stitches:
            for edge in (stitch.first, stitch.second):
                piece = piece_by_id.get(edge.piece_id)
                if piece is None:
                    raise ValueError(
                        f"stitch {stitch.stitch_id!r} references unknown piece"
                    )
                boundary_size = len(piece.boundary)
                if (
                    edge.start_vertex >= boundary_size
                    or edge.end_vertex >= boundary_size
                ):
                    raise ValueError(
                        f"stitch {stitch.stitch_id!r} exceeds piece boundary"
                    )
                if piece.edges and edge.edge_id is None:
                    raise ValueError(
                        f"stitch {stitch.stitch_id!r} must reference an explicit edge"
                    )
                if edge.edge_id is not None:
                    declared_edge = explicit_edges.get(edge.edge_id)
                    if declared_edge is None:
                        raise ValueError(
                            f"stitch {stitch.stitch_id!r} references unknown edge"
                        )
                    if (
                        declared_edge.piece_id != edge.piece_id
                        or declared_edge.start_vertex != edge.start_vertex
                        or declared_edge.end_vertex != edge.end_vertex
                    ):
                        raise ValueError(
                            f"stitch {stitch.stitch_id!r} edge reference does not "
                            "match the declared pattern edge"
                        )
