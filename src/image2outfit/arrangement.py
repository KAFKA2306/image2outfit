"""Deterministic panel placement and styling expansion for initialize-3d."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import StrEnum

from .avatar import AvatarSpec
from .pattern_stage import PatternHypothesis
from .seam_stage import SeamHypothesis
from .styling import StylingOperationKind, StylingSpec

Vec3 = tuple[float, float, float]


class WrapDirection(StrEnum):
    NONE = "none"
    CLOCKWISE = "clockwise"
    COUNTERCLOCKWISE = "counterclockwise"
    FRONT_TO_BACK = "front-to-back"
    BACK_TO_FRONT = "back-to-front"


class IntersectionKind(StrEnum):
    BODY = "body"
    GARMENT = "garment"
    SELF = "self"
    LAYER = "layer"


@dataclass(frozen=True, slots=True)
class PanelPlacement:
    piece_id: str
    anchor_landmark_ids: tuple[str, ...]
    position_mm: Vec3
    rotation_degrees_xyz: Vec3
    body_offset_mm: float
    wrap_direction: WrapDirection
    layer_order: int
    outward_facing: bool
    bounds_minimum_mm: Vec3
    bounds_maximum_mm: Vec3

    def __post_init__(self) -> None:
        if not self.piece_id.strip() or not self.anchor_landmark_ids:
            raise ValueError("panel placement identity and anchors are required")
        if len(self.anchor_landmark_ids) != len(set(self.anchor_landmark_ids)):
            raise ValueError("panel anchor landmark IDs must be unique")
        values = (
            *self.position_mm,
            *self.rotation_degrees_xyz,
            self.body_offset_mm,
            *self.bounds_minimum_mm,
            *self.bounds_maximum_mm,
        )
        if any(not math.isfinite(value) for value in values):
            raise ValueError("panel placement values must be finite")
        if self.body_offset_mm < 0:
            raise ValueError("body_offset_mm must be non-negative")
        if self.layer_order < 0:
            raise ValueError("layer_order must be non-negative")
        if any(
            minimum >= maximum
            for minimum, maximum in zip(
                self.bounds_minimum_mm,
                self.bounds_maximum_mm,
            )
        ):
            raise ValueError("panel placement bounds must have positive extent")


@dataclass(frozen=True, slots=True)
class ExpandedStylingConstraint:
    operation_id: str
    kind: StylingOperationKind
    target_ids: tuple[str, ...]
    anchor_target_ids: tuple[str, ...]
    strength: float
    friction: float
    release_condition: str
    reversible: bool


@dataclass(frozen=True, slots=True)
class InitialIntersection:
    intersection_id: str
    kind: IntersectionKind
    first_id: str
    second_id: str
    penetration_mm: float
    resolved: bool = False

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (self.intersection_id, self.first_id, self.second_id)
        ):
            raise ValueError("intersection identity fields are required")
        if self.first_id == self.second_id:
            raise ValueError("intersection requires two distinct objects")
        if not math.isfinite(self.penetration_mm) or self.penetration_mm <= 0:
            raise ValueError("intersection penetration_mm must be positive")


@dataclass(frozen=True, slots=True)
class ArrangementPlan:
    arrangement_id: str
    garment_id: str
    avatar_id: str
    pattern_hypothesis_id: str
    seam_hypothesis_id: str
    placements: tuple[PanelPlacement, ...]
    styling_constraints: tuple[ExpandedStylingConstraint, ...]
    intersections: tuple[InitialIntersection, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.arrangement_id,
                self.garment_id,
                self.avatar_id,
                self.pattern_hypothesis_id,
                self.seam_hypothesis_id,
            )
        ):
            raise ValueError("arrangement identity fields are required")
        if self.schema_version != 1:
            raise ValueError("unsupported ArrangementPlan schema_version")
        if not self.placements:
            raise ValueError("ArrangementPlan requires panel placements")
        piece_ids = [item.piece_id for item in self.placements]
        if len(piece_ids) != len(set(piece_ids)):
            raise ValueError("each pattern piece requires exactly one placement")
        operation_ids = [item.operation_id for item in self.styling_constraints]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("expanded styling operation IDs must be unique")
        intersection_ids = [item.intersection_id for item in self.intersections]
        if len(intersection_ids) != len(set(intersection_ids)):
            raise ValueError("initial intersection IDs must be unique")

    def unresolved_intersections(self) -> tuple[InitialIntersection, ...]:
        return tuple(item for item in self.intersections if not item.resolved)

    def validate_ready_for_solver(self) -> None:
        if not all(item.outward_facing for item in self.placements):
            invalid = sorted(
                item.piece_id for item in self.placements if not item.outward_facing
            )
            raise ValueError(f"panels have invalid face orientation: {invalid}")
        unresolved = self.unresolved_intersections()
        if unresolved:
            raise ValueError(
                "unresolved initial intersections: "
                f"{[item.intersection_id for item in unresolved]}"
            )
        overlaps = self.panel_overlaps()
        if overlaps:
            raise ValueError(f"same-layer panel bounds overlap: {overlaps}")

    def panel_overlaps(self) -> tuple[tuple[str, str], ...]:
        overlaps = []
        for index, first in enumerate(self.placements):
            for second in self.placements[index + 1 :]:
                if first.layer_order != second.layer_order:
                    continue
                intersects = all(
                    first_minimum < second_maximum and second_minimum < first_maximum
                    for first_minimum, first_maximum, second_minimum, second_maximum in zip(
                        first.bounds_minimum_mm,
                        first.bounds_maximum_mm,
                        second.bounds_minimum_mm,
                        second.bounds_maximum_mm,
                    )
                )
                if intersects:
                    overlaps.append(tuple(sorted((first.piece_id, second.piece_id))))
        return tuple(sorted(overlaps))

    def without_styling(self, *operation_ids: str) -> "ArrangementPlan":
        removed = set(operation_ids)
        for constraint in self.styling_constraints:
            if constraint.operation_id in removed and not constraint.reversible:
                raise ValueError(
                    f"styling operation {constraint.operation_id!r} is not reversible"
                )
        return ArrangementPlan(
            arrangement_id=self.arrangement_id,
            garment_id=self.garment_id,
            avatar_id=self.avatar_id,
            pattern_hypothesis_id=self.pattern_hypothesis_id,
            seam_hypothesis_id=self.seam_hypothesis_id,
            placements=self.placements,
            styling_constraints=tuple(
                item
                for item in self.styling_constraints
                if item.operation_id not in removed
            ),
            intersections=self.intersections,
            schema_version=self.schema_version,
        )

    def fingerprint(self) -> str:
        payload = {
            "arrangementId": self.arrangement_id,
            "garmentId": self.garment_id,
            "avatarId": self.avatar_id,
            "patternHypothesisId": self.pattern_hypothesis_id,
            "seamHypothesisId": self.seam_hypothesis_id,
            "placements": [
                {
                    "pieceId": item.piece_id,
                    "anchors": item.anchor_landmark_ids,
                    "positionMm": item.position_mm,
                    "rotationDegreesXyz": item.rotation_degrees_xyz,
                    "bodyOffsetMm": item.body_offset_mm,
                    "wrapDirection": item.wrap_direction.value,
                    "layerOrder": item.layer_order,
                    "outwardFacing": item.outward_facing,
                    "boundsMinimumMm": item.bounds_minimum_mm,
                    "boundsMaximumMm": item.bounds_maximum_mm,
                }
                for item in sorted(self.placements, key=lambda value: value.piece_id)
            ],
            "styling": [
                {
                    "operationId": item.operation_id,
                    "kind": item.kind.value,
                    "targetIds": item.target_ids,
                    "anchorTargetIds": item.anchor_target_ids,
                    "strength": item.strength,
                    "friction": item.friction,
                    "releaseCondition": item.release_condition,
                    "reversible": item.reversible,
                }
                for item in sorted(
                    self.styling_constraints,
                    key=lambda value: value.operation_id,
                )
            ],
            "intersections": [
                {
                    "intersectionId": item.intersection_id,
                    "kind": item.kind.value,
                    "firstId": item.first_id,
                    "secondId": item.second_id,
                    "penetrationMm": item.penetration_mm,
                    "resolved": item.resolved,
                }
                for item in sorted(
                    self.intersections,
                    key=lambda value: value.intersection_id,
                )
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_arrangement_plan(
    *,
    arrangement_id: str,
    avatar: AvatarSpec,
    pattern: PatternHypothesis,
    seam: SeamHypothesis,
    styling: StylingSpec,
    placements: tuple[PanelPlacement, ...],
    intersections: tuple[InitialIntersection, ...] = (),
) -> ArrangementPlan:
    if seam.pattern_hypothesis_id != pattern.hypothesis_id:
        raise ValueError("seam and pattern hypotheses do not match")
    expected_pieces = {
        item.piece_id for item in pattern.construction.garment.pattern_pieces
    }
    actual_pieces = {item.piece_id for item in placements}
    if expected_pieces != actual_pieces:
        raise ValueError(
            "placements must cover exactly the pattern pieces: "
            f"missing={sorted(expected_pieces - actual_pieces)}, "
            f"extra={sorted(actual_pieces - expected_pieces)}"
        )
    landmark_ids = {item.landmark_id for item in avatar.landmarks}
    unknown_anchors = sorted(
        {
            anchor
            for placement in placements
            for anchor in placement.anchor_landmark_ids
        }.difference(landmark_ids)
    )
    if unknown_anchors:
        raise ValueError(
            f"placements reference unknown avatar landmarks: {unknown_anchors}"
        )
    if styling.conflicts():
        raise ValueError("styling graph contains conflicting operations")
    constraints = tuple(
        ExpandedStylingConstraint(
            operation_id=item.operation_id,
            kind=item.kind,
            target_ids=item.target_ids,
            anchor_target_ids=item.anchor_target_ids,
            strength=item.strength,
            friction=item.friction,
            release_condition=item.release_condition,
            reversible=item.reversible,
        )
        for item in styling.application_order()
    )
    return ArrangementPlan(
        arrangement_id=arrangement_id,
        garment_id=pattern.construction.garment.product_id,
        avatar_id=avatar.avatar_id,
        pattern_hypothesis_id=pattern.hypothesis_id,
        seam_hypothesis_id=seam.hypothesis_id,
        placements=tuple(sorted(placements, key=lambda item: item.piece_id)),
        styling_constraints=constraints,
        intersections=intersections,
    )
