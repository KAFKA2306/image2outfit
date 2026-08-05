"""Region- and pose-aware garment fit metrics and failure routing."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from .domain import BodyRegion
from .pipeline import PipelineStage


class FitCause(StrEnum):
    PATTERN = "pattern"
    MATERIAL = "material"
    ARRANGEMENT = "arrangement"
    SIMULATION = "simulation"
    SKINNING = "skinning"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class EaseTarget:
    body_region: BodyRegion
    minimum_mm: float
    target_mm: float
    maximum_mm: float
    front_bias_mm: float = 0.0
    back_bias_mm: float = 0.0

    def __post_init__(self) -> None:
        values = (
            self.minimum_mm,
            self.target_mm,
            self.maximum_mm,
            self.front_bias_mm,
            self.back_bias_mm,
        )
        if any(not math.isfinite(value) for value in values):
            raise ValueError("ease values must be finite")
        if not self.minimum_mm <= self.target_mm <= self.maximum_mm:
            raise ValueError("ease target must be within minimum and maximum")


@dataclass(frozen=True, slots=True)
class DirectionalStrain:
    warp: float
    weft: float
    bias: float

    def __post_init__(self) -> None:
        if any(
            not math.isfinite(value) or value < 0
            for value in (self.warp, self.weft, self.bias)
        ):
            raise ValueError("strain values must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class ContactMetrics:
    minimum_clearance_mm: float
    maximum_clearance_mm: float
    pressure_kpa: float
    contact_area_mm2: float
    penetration_depth_mm: float

    def __post_init__(self) -> None:
        values = (
            self.minimum_clearance_mm,
            self.maximum_clearance_mm,
            self.pressure_kpa,
            self.contact_area_mm2,
            self.penetration_depth_mm,
        )
        if any(not math.isfinite(value) for value in values):
            raise ValueError("contact metrics must be finite")
        if self.maximum_clearance_mm < self.minimum_clearance_mm:
            raise ValueError("maximum clearance must not be below minimum")
        if any(
            value < 0
            for value in (
                self.pressure_kpa,
                self.contact_area_mm2,
                self.penetration_depth_mm,
            )
        ):
            raise ValueError("pressure, area, and penetration must be non-negative")


@dataclass(frozen=True, slots=True)
class PoseFitReport:
    pose_id: str
    body_region: BodyRegion
    strain: DirectionalStrain
    contact: ContactMetrics
    silhouette_error_mm: float
    cause: FitCause
    recommended_stage: PipelineStage

    def __post_init__(self) -> None:
        if not self.pose_id.strip():
            raise ValueError("pose_id is required")
        if not math.isfinite(self.silhouette_error_mm) or self.silhouette_error_mm < 0:
            raise ValueError("silhouette_error_mm must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class FitDefect:
    code: str
    pose_id: str
    body_region: BodyRegion
    cause: FitCause
    recommended_stage: PipelineStage
    measured_value: float
    threshold: float


@dataclass(frozen=True, slots=True)
class FitSpec:
    ease_targets: tuple[EaseTarget, ...]
    reports: tuple[PoseFitReport, ...]
    maximum_strain: float = 0.15
    maximum_pressure_kpa: float = 4.0
    maximum_penetration_mm: float = 0.0
    maximum_silhouette_error_mm: float = 10.0
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported FitSpec schema_version")
        target_regions = [item.body_region for item in self.ease_targets]
        if len(target_regions) != len(set(target_regions)):
            raise ValueError("ease target body regions must be unique")
        report_keys = [(item.pose_id, item.body_region) for item in self.reports]
        if len(report_keys) != len(set(report_keys)):
            raise ValueError("pose and body-region reports must be unique")
        limits = (
            self.maximum_strain,
            self.maximum_pressure_kpa,
            self.maximum_penetration_mm,
            self.maximum_silhouette_error_mm,
        )
        if any(not math.isfinite(value) or value < 0 for value in limits):
            raise ValueError("fit thresholds must be finite and non-negative")

    def require_poses(self, required: tuple[str, ...]) -> None:
        available = {item.pose_id for item in self.reports}
        missing = sorted(set(required).difference(available))
        if missing:
            raise ValueError(f"fit reports are missing required poses: {missing}")

    def defects(self) -> tuple[FitDefect, ...]:
        defects: list[FitDefect] = []
        for report in self.reports:
            for direction, value in (
                ("warp", report.strain.warp),
                ("weft", report.strain.weft),
                ("bias", report.strain.bias),
            ):
                if value > self.maximum_strain:
                    defects.append(
                        FitDefect(
                            code=f"strain-{direction}",
                            pose_id=report.pose_id,
                            body_region=report.body_region,
                            cause=report.cause,
                            recommended_stage=report.recommended_stage,
                            measured_value=value,
                            threshold=self.maximum_strain,
                        )
                    )
            for code, value, threshold in (
                (
                    "pressure",
                    report.contact.pressure_kpa,
                    self.maximum_pressure_kpa,
                ),
                (
                    "penetration",
                    report.contact.penetration_depth_mm,
                    self.maximum_penetration_mm,
                ),
                (
                    "silhouette",
                    report.silhouette_error_mm,
                    self.maximum_silhouette_error_mm,
                ),
            ):
                if value > threshold:
                    defects.append(
                        FitDefect(
                            code=code,
                            pose_id=report.pose_id,
                            body_region=report.body_region,
                            cause=report.cause,
                            recommended_stage=report.recommended_stage,
                            measured_value=value,
                            threshold=threshold,
                        )
                    )
            target = next(
                (
                    item
                    for item in self.ease_targets
                    if item.body_region is report.body_region
                ),
                None,
            )
            if target is not None and (
                report.contact.minimum_clearance_mm < target.minimum_mm
                or report.contact.maximum_clearance_mm > target.maximum_mm
            ):
                measured = (
                    report.contact.minimum_clearance_mm
                    if report.contact.minimum_clearance_mm < target.minimum_mm
                    else report.contact.maximum_clearance_mm
                )
                threshold = (
                    target.minimum_mm
                    if measured < target.minimum_mm
                    else target.maximum_mm
                )
                defects.append(
                    FitDefect(
                        code="clearance",
                        pose_id=report.pose_id,
                        body_region=report.body_region,
                        cause=report.cause,
                        recommended_stage=report.recommended_stage,
                        measured_value=measured,
                        threshold=threshold,
                    )
                )
        return tuple(defects)
