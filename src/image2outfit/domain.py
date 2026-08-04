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


def _require_finite_points(points: Sequence[Vec2], label: str) -> None:
    if len(points) < 3:
        raise ValueError(f"{label} requires at least three boundary points")
    if any(not math.isfinite(number) for point in points for number in point):
        raise ValueError(f"{label} contains a non-finite coordinate")


@dataclass(frozen=True, slots=True)
class GarmentPart:
    part_id: str
    kind: GarmentPartKind
    body_regions: tuple[BodyRegion, ...]
    construction_role: ConstructionRole
    layer: LayerPosition
    material_behavior: MaterialBehavior
    fit_profile: FitProfile
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


@dataclass(frozen=True, slots=True)
class PatternPiece:
    piece_id: str
    part_id: str
    boundary: tuple[Vec2, ...]
    grain_angle_degrees: float = 0.0
    cut_count: int = 1
    on_fold: bool = False

    def __post_init__(self) -> None:
        _require_identifier(self.piece_id, "piece_id")
        _require_identifier(self.part_id, "part_id")
        _require_finite_points(self.boundary, f"pattern piece {self.piece_id!r}")
        if not math.isfinite(self.grain_angle_degrees):
            raise ValueError("grain angle must be finite")
        if self.cut_count < 1:
            raise ValueError("cut_count must be positive")


@dataclass(frozen=True, slots=True)
class StitchEdge:
    piece_id: str
    start_vertex: int
    end_vertex: int

    def __post_init__(self) -> None:
        _require_identifier(self.piece_id, "piece_id")
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
