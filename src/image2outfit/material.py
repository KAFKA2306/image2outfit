"""Measured anisotropic fabric properties and explicit solver mappings."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping


class CalibrationStatus(StrEnum):
    MEASURED = "measured"
    MEASURED_AND_CONVERTED = "measured-and-converted"
    ESTIMATED = "estimated"
    UNVERIFIED = "unverified"


@dataclass(frozen=True, slots=True)
class AnisotropicFabricProperties:
    areal_mass_g_m2: float
    physical_thickness_mm: float
    collision_thickness_mm: float
    render_thickness_mm: float
    stretch_warp_g_s2: float
    stretch_weft_g_s2: float
    shear_g_s2: float
    bending_warp_g_mm2_s2: float
    bending_weft_g_mm2_s2: float
    static_friction: float | None = None
    dynamic_friction: float | None = None
    compression_kpa: float | None = None

    def __post_init__(self) -> None:
        required = (
            self.areal_mass_g_m2,
            self.physical_thickness_mm,
            self.collision_thickness_mm,
            self.render_thickness_mm,
            self.stretch_warp_g_s2,
            self.stretch_weft_g_s2,
            self.shear_g_s2,
            self.bending_warp_g_mm2_s2,
            self.bending_weft_g_mm2_s2,
        )
        if any(not math.isfinite(value) or value <= 0 for value in required):
            raise ValueError("required fabric properties must be finite and positive")
        for label, value in (
            ("static_friction", self.static_friction),
            ("dynamic_friction", self.dynamic_friction),
            ("compression_kpa", self.compression_kpa),
        ):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError(f"{label} must be finite and non-negative")
        if (
            self.static_friction is not None
            and self.dynamic_friction is not None
            and self.dynamic_friction > self.static_friction
        ):
            raise ValueError("dynamic friction must not exceed static friction")

    @property
    def simulation_ready(self) -> bool:
        return all(
            value is not None
            for value in (
                self.static_friction,
                self.dynamic_friction,
                self.compression_kpa,
            )
        )


@dataclass(frozen=True, slots=True)
class SolverMapping:
    solver_id: str
    solver_version: str
    source_parameterization: str
    parameters: Mapping[str, float]
    conversion_error: Mapping[str, float]

    def __post_init__(self) -> None:
        if (
            not self.solver_id
            or not self.solver_version
            or not self.source_parameterization
        ):
            raise ValueError("solver mapping identity fields are required")
        if not self.parameters:
            raise ValueError("solver mapping parameters are required")
        for collection in (self.parameters, self.conversion_error):
            if any(
                not math.isfinite(value) or value < 0 for value in collection.values()
            ):
                raise ValueError(
                    "solver mapping values must be finite and non-negative"
                )


@dataclass(frozen=True, slots=True)
class MaterialSpec:
    material_id: str
    composition: str
    weave: str
    calibration_status: CalibrationStatus
    calibration_method: str
    source_url: str
    source_license: str
    properties: AnisotropicFabricProperties
    solver_mappings: tuple[SolverMapping, ...]
    real_drape_coefficient: float | None = None
    simulated_drape_coefficient: float | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported MaterialSpec schema_version")
        for label, value in (
            ("material_id", self.material_id),
            ("composition", self.composition),
            ("weave", self.weave),
            ("calibration_method", self.calibration_method),
            ("source_url", self.source_url),
            ("source_license", self.source_license),
        ):
            if not value.strip():
                raise ValueError(f"{label} is required")
        if len({item.solver_id for item in self.solver_mappings}) != len(
            self.solver_mappings
        ):
            raise ValueError("solver IDs must be unique within a material")
        for label, value in (
            ("real_drape_coefficient", self.real_drape_coefficient),
            ("simulated_drape_coefficient", self.simulated_drape_coefficient),
        ):
            if value is not None and (not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError(f"{label} must be between zero and one")

    def mapping_for(self, solver_id: str) -> SolverMapping:
        mapping = next(
            (item for item in self.solver_mappings if item.solver_id == solver_id),
            None,
        )
        if mapping is None:
            raise KeyError(solver_id)
        return mapping

    @property
    def drape_absolute_error(self) -> float | None:
        if (
            self.real_drape_coefficient is None
            or self.simulated_drape_coefficient is None
        ):
            return None
        return abs(self.real_drape_coefficient - self.simulated_drape_coefficient)


def material_spec_from_dict(value: Mapping[str, Any]) -> MaterialSpec:
    physical = value["properties"]
    mappings = value.get("solverMappings", [])
    return MaterialSpec(
        material_id=str(value["materialId"]),
        composition=str(value["composition"]),
        weave=str(value["weave"]),
        calibration_status=CalibrationStatus(value["calibrationStatus"]),
        calibration_method=str(value["calibrationMethod"]),
        source_url=str(value["sourceUrl"]),
        source_license=str(value["sourceLicense"]),
        properties=AnisotropicFabricProperties(
            areal_mass_g_m2=float(physical["arealMassGm2"]),
            physical_thickness_mm=float(physical["physicalThicknessMm"]),
            collision_thickness_mm=float(physical["collisionThicknessMm"]),
            render_thickness_mm=float(physical["renderThicknessMm"]),
            stretch_warp_g_s2=float(physical["stretchWarpGs2"]),
            stretch_weft_g_s2=float(physical["stretchWeftGs2"]),
            shear_g_s2=float(physical["shearGs2"]),
            bending_warp_g_mm2_s2=float(physical["bendingWarpGmm2s2"]),
            bending_weft_g_mm2_s2=float(physical["bendingWeftGmm2s2"]),
            static_friction=(
                None
                if physical.get("staticFriction") is None
                else float(physical["staticFriction"])
            ),
            dynamic_friction=(
                None
                if physical.get("dynamicFriction") is None
                else float(physical["dynamicFriction"])
            ),
            compression_kpa=(
                None
                if physical.get("compressionKpa") is None
                else float(physical["compressionKpa"])
            ),
        ),
        solver_mappings=tuple(
            SolverMapping(
                solver_id=str(item["solverId"]),
                solver_version=str(item["solverVersion"]),
                source_parameterization=str(item["sourceParameterization"]),
                parameters={
                    str(key): float(number)
                    for key, number in item["parameters"].items()
                },
                conversion_error={
                    str(key): float(number)
                    for key, number in item.get("conversionError", {}).items()
                },
            )
            for item in mappings
        ),
        real_drape_coefficient=(
            None
            if value.get("realDrapeCoefficient") is None
            else float(value["realDrapeCoefficient"])
        ),
        simulated_drape_coefficient=(
            None
            if value.get("simulatedDrapeCoefficient") is None
            else float(value["simulatedDrapeCoefficient"])
        ),
    )


def load_material_library(path: str | Path) -> tuple[MaterialSpec, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != 1:
        raise ValueError("unsupported material library schemaVersion")
    materials = tuple(material_spec_from_dict(item) for item in payload["materials"])
    identifiers = [item.material_id for item in materials]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("material library IDs must be unique")
    return materials
