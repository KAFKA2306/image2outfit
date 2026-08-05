"""Camera, pose, occlusion, and reprojection contracts for normalize-view."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

from .reference import ReferenceSet

Point2 = tuple[float, float]
Point3 = tuple[float, float, float]
Matrix3 = tuple[Point3, Point3, Point3]


def _finite(values: tuple[float, ...], label: str) -> None:
    if any(not math.isfinite(value) for value in values):
        raise ValueError(f"{label} must contain finite values")


def _apply(matrix: Matrix3, point: Point2) -> Point2:
    x, y = point
    denominator = matrix[2][0] * x + matrix[2][1] * y + matrix[2][2]
    if abs(denominator) < 1e-12:
        raise ValueError("normalization transform maps point to infinity")
    return (
        (matrix[0][0] * x + matrix[0][1] * y + matrix[0][2]) / denominator,
        (matrix[1][0] * x + matrix[1][1] * y + matrix[1][2]) / denominator,
    )


def _multiply(first: Matrix3, second: Matrix3) -> Matrix3:
    return tuple(
        tuple(
            sum(first[row][index] * second[index][column] for index in range(3))
            for column in range(3)
        )
        for row in range(3)
    )  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class CameraIntrinsics:
    focal_x_px: float
    focal_y_px: float
    principal_x_px: float
    principal_y_px: float
    skew: float = 0.0

    def __post_init__(self) -> None:
        values = (
            self.focal_x_px,
            self.focal_y_px,
            self.principal_x_px,
            self.principal_y_px,
            self.skew,
        )
        _finite(values, "camera intrinsics")
        if self.focal_x_px <= 0 or self.focal_y_px <= 0:
            raise ValueError("camera focal lengths must be positive")


@dataclass(frozen=True, slots=True)
class CameraExtrinsics:
    rotation_rows: Matrix3
    translation_mm: Point3

    def __post_init__(self) -> None:
        _finite(tuple(value for row in self.rotation_rows for value in row), "rotation")
        _finite(self.translation_mm, "translation")
        for row in self.rotation_rows:
            if abs(math.sqrt(sum(value * value for value in row)) - 1.0) > 1e-5:
                raise ValueError("camera rotation rows must be unit length")
        for first in range(3):
            for second in range(first + 1, 3):
                dot = sum(
                    self.rotation_rows[first][index] * self.rotation_rows[second][index]
                    for index in range(3)
                )
                if abs(dot) > 1e-5:
                    raise ValueError("camera rotation rows must be orthogonal")


@dataclass(frozen=True, slots=True)
class CameraUncertainty:
    focal_sigma_px: float
    principal_sigma_px: float
    pose_sigma_mm: float
    pixel_sigma_px: float

    def __post_init__(self) -> None:
        values = (
            self.focal_sigma_px,
            self.principal_sigma_px,
            self.pose_sigma_mm,
            self.pixel_sigma_px,
        )
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError(
                "camera uncertainty values must be finite and non-negative"
            )


@dataclass(frozen=True, slots=True)
class Transform2D:
    forward: Matrix3
    inverse: Matrix3

    def __post_init__(self) -> None:
        values = tuple(
            value
            for matrix in (self.forward, self.inverse)
            for row in matrix
            for value in row
        )
        _finite(values, "2D transform")
        product = _multiply(self.forward, self.inverse)
        identity: Matrix3 = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        maximum_error = max(
            abs(product[row][column] - identity[row][column])
            for row in range(3)
            for column in range(3)
        )
        if maximum_error > 1e-6:
            raise ValueError("forward and inverse transforms are inconsistent")

    def normalize(self, point: Point2) -> Point2:
        return _apply(self.forward, point)

    def denormalize(self, point: Point2) -> Point2:
        return _apply(self.inverse, point)


@dataclass(frozen=True, slots=True)
class LandmarkObservation:
    landmark_id: str
    source_point_px: Point2
    normalized_point_px: Point2
    confidence: float
    occluded: bool

    def __post_init__(self) -> None:
        if not self.landmark_id.strip():
            raise ValueError("landmark_id is required")
        _finite(self.source_point_px + self.normalized_point_px, "landmark point")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("landmark confidence must be between zero and one")
        if self.occluded and self.confidence > 0.5:
            raise ValueError("occluded landmarks cannot have high confidence")


@dataclass(frozen=True, slots=True)
class OcclusionMask:
    mask_id: str
    path: str
    sha256: str
    occluder: str

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (self.mask_id, self.path, self.sha256, self.occluder)
        ):
            raise ValueError("occlusion mask fields are required")


@dataclass(frozen=True, slots=True)
class NormalizedView:
    normalized_view_id: str
    source_asset_id: str
    transform: Transform2D
    intrinsics: CameraIntrinsics
    extrinsics: CameraExtrinsics
    uncertainty: CameraUncertainty
    landmarks: tuple[LandmarkObservation, ...]
    occlusion_masks: tuple[OcclusionMask, ...]
    pose_id: str
    mirrored: bool = False

    def __post_init__(self) -> None:
        if not self.normalized_view_id.strip() or not self.source_asset_id.strip():
            raise ValueError("normalized and source view IDs are required")
        if not self.pose_id.strip():
            raise ValueError("pose_id is required")
        landmark_ids = [item.landmark_id for item in self.landmarks]
        if len(landmark_ids) != len(set(landmark_ids)):
            raise ValueError("landmark observations must be unique")
        mask_ids = [item.mask_id for item in self.occlusion_masks]
        if len(mask_ids) != len(set(mask_ids)):
            raise ValueError("occlusion mask IDs must be unique")

    @property
    def reprojection_error_px(self) -> float:
        visible = [item for item in self.landmarks if not item.occluded]
        if not visible:
            raise ValueError("reprojection error requires visible landmarks")
        squared = []
        for item in visible:
            recovered = self.transform.denormalize(item.normalized_point_px)
            squared.append(
                (recovered[0] - item.source_point_px[0]) ** 2
                + (recovered[1] - item.source_point_px[1]) ** 2
            )
        return math.sqrt(sum(squared) / len(squared))

    def pattern_scale_uncertainty_mm(self, depth_mm: float) -> float:
        if not math.isfinite(depth_mm) or depth_mm <= 0:
            raise ValueError("depth_mm must be finite and positive")
        focal = min(self.intrinsics.focal_x_px, self.intrinsics.focal_y_px)
        pixel_component = depth_mm * self.uncertainty.pixel_sigma_px / focal
        focal_component = depth_mm * self.uncertainty.focal_sigma_px / max(focal, 1e-12)
        return math.sqrt(
            pixel_component**2 + focal_component**2 + self.uncertainty.pose_sigma_mm**2
        )


@dataclass(frozen=True, slots=True)
class NormalizedReferenceSet:
    normalized_set_id: str
    reference_set_id: str
    garment_id: str
    views: tuple[NormalizedView, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.normalized_set_id,
                self.reference_set_id,
                self.garment_id,
            )
        ):
            raise ValueError("normalized reference identity fields are required")
        if self.schema_version != 1:
            raise ValueError("unsupported NormalizedReferenceSet schema_version")
        if not self.views:
            raise ValueError("NormalizedReferenceSet requires views")
        identifiers = [item.normalized_view_id for item in self.views]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("normalized view IDs must be unique")

    def validate_sources(self, references: ReferenceSet) -> None:
        if references.reference_set_id != self.reference_set_id:
            raise ValueError("normalized set references another ReferenceSet")
        if references.garment_id != self.garment_id:
            raise ValueError("normalized set references another garment")
        available = set(references.downstream_reference_ids)
        unknown = sorted(
            {item.source_asset_id for item in self.views}.difference(available)
        )
        if unknown:
            raise ValueError(f"normalized views reference unknown assets: {unknown}")

    def reject_mirror_ambiguity(self, expected_mirrored: Mapping[str, bool]) -> None:
        for view in self.views:
            expected = expected_mirrored.get(view.source_asset_id)
            if expected is None:
                raise ValueError(
                    f"mirror expectation missing for {view.source_asset_id!r}"
                )
            if expected != view.mirrored:
                raise ValueError(f"mirror state mismatch for {view.source_asset_id!r}")
