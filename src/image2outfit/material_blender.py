"""Explicit, auditable projection of measured fabric data into Blender cloth.

Blender 4.4 exposes scalar surface spring settings.  Real woven fabrics are
orthotropic, so this module never pretends that a scalar Blender setting is an
exact unit conversion.  It preserves the source axes, reports projection loss,
and keeps through-thickness compression separate from in-plane compression.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .material import MaterialSpec


@dataclass(frozen=True, slots=True)
class ContactHypothesis:
    hypothesis_id: str
    static_friction: float
    dynamic_friction: float
    method: str
    source: str
    confidence: float
    measured: bool = False

    def __post_init__(self) -> None:
        if (
            not self.hypothesis_id.strip()
            or not self.method.strip()
            or not self.source.strip()
        ):
            raise ValueError(
                "contact hypothesis identity, method, and source are required"
            )
        if not 0 <= self.dynamic_friction <= self.static_friction <= 1:
            raise ValueError(
                "contact friction must satisfy 0 <= dynamic <= static <= 1"
            )
        if not 0 <= self.confidence <= 1:
            raise ValueError(
                "contact hypothesis confidence must be between zero and one"
            )


@dataclass(frozen=True, slots=True)
class BlenderCalibrationProfile:
    profile_id: str
    blender_version: str
    source_library: str
    tension_range: tuple[float, float]
    shear_range: tuple[float, float]
    bending_range: tuple[float, float]
    buckling_compression_ratio: float
    tension_damping: float
    compression_damping: float
    shear_damping: float
    bending_damping: float
    air_damping: float
    quality: int
    collision_quality: int
    self_collision_scale: float
    contact: ContactHypothesis

    def __post_init__(self) -> None:
        for label, limits in (
            ("tension_range", self.tension_range),
            ("shear_range", self.shear_range),
            ("bending_range", self.bending_range),
        ):
            if len(limits) != 2 or not 0 < limits[0] < limits[1]:
                raise ValueError(f"{label} must be a positive increasing pair")
        if not 0 < self.buckling_compression_ratio <= 1:
            raise ValueError("buckling_compression_ratio must be in (0, 1]")
        for label, value in (
            ("tension_damping", self.tension_damping),
            ("compression_damping", self.compression_damping),
            ("shear_damping", self.shear_damping),
            ("bending_damping", self.bending_damping),
            ("air_damping", self.air_damping),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{label} must be finite and non-negative")
        if self.quality < 1 or self.collision_quality < 1:
            raise ValueError("solver quality values must be positive")
        if not 0 < self.self_collision_scale:
            raise ValueError("self_collision_scale must be positive")


@dataclass(frozen=True, slots=True)
class AxisProjection:
    warp: float
    weft: float
    scalar_proxy: float
    anisotropy_ratio: float
    maximum_relative_error: float


@dataclass(frozen=True, slots=True)
class BlenderMaterialProjection:
    schema_version: int
    mapping_id: str
    material_id: str
    blender_version: str
    source_library: str
    source_url: str
    source_license: str
    grain_angle_degrees: float
    surface_density_kg_m2: float
    physical_thickness_m: float
    collision_thickness_m: float
    render_thickness_m: float
    cloth_settings: Mapping[str, float | int | bool]
    cloth_collision_settings: Mapping[str, float | int | bool]
    collider_settings: Mapping[str, float]
    render_settings: Mapping[str, float]
    stretch_projection: AxisProjection
    bending_projection: AxisProjection
    source_axes: Mapping[str, float]
    unmapped_source_properties: Mapping[str, float | None]
    conversion_error: Mapping[str, float]
    contact_hypothesis: ContactHypothesis
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported BlenderMaterialProjection schema version")
        if not math.isfinite(self.grain_angle_degrees):
            raise ValueError("grain_angle_degrees must be finite")
        for label, value in (
            ("surface_density_kg_m2", self.surface_density_kg_m2),
            ("physical_thickness_m", self.physical_thickness_m),
            ("collision_thickness_m", self.collision_thickness_m),
            ("render_thickness_m", self.render_thickness_m),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{label} must be finite and positive")

    def vertex_mass_kg(self, surface_area_m2: float, vertex_count: int) -> float:
        if not math.isfinite(surface_area_m2) or surface_area_m2 <= 0:
            raise ValueError("surface_area_m2 must be finite and positive")
        if vertex_count <= 0:
            raise ValueError("vertex_count must be positive")
        return self.surface_density_kg_m2 * surface_area_m2 / vertex_count

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def fingerprint(self) -> str:
        payload = json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def load_blender_calibration_profile(path: str | Path) -> BlenderCalibrationProfile:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != 1:
        raise ValueError("unsupported Blender calibration profile schemaVersion")
    ranges = payload["scalarProjectionRanges"]
    contact = payload["contactHypothesis"]
    return BlenderCalibrationProfile(
        profile_id=str(payload["profileId"]),
        blender_version=str(payload["blenderVersion"]),
        source_library=str(payload["sourceLibrary"]),
        tension_range=tuple(float(value) for value in ranges["tensionStiffness"]),
        shear_range=tuple(float(value) for value in ranges["shearStiffness"]),
        bending_range=tuple(float(value) for value in ranges["bendingStiffness"]),
        buckling_compression_ratio=float(payload["bucklingCompressionRatio"]),
        tension_damping=float(payload["damping"]["tension"]),
        compression_damping=float(payload["damping"]["compression"]),
        shear_damping=float(payload["damping"]["shear"]),
        bending_damping=float(payload["damping"]["bending"]),
        air_damping=float(payload["airDamping"]),
        quality=int(payload["quality"]),
        collision_quality=int(payload["collisionQuality"]),
        self_collision_scale=float(payload["selfCollisionScale"]),
        contact=ContactHypothesis(
            hypothesis_id=str(contact["hypothesisId"]),
            static_friction=float(contact["staticFriction"]),
            dynamic_friction=float(contact["dynamicFriction"]),
            method=str(contact["method"]),
            source=str(contact["source"]),
            confidence=float(contact["confidence"]),
            measured=bool(contact.get("measured", False)),
        ),
    )


def _geometric_mean(first: float, second: float) -> float:
    return math.sqrt(first * second)


def _axis_projection(warp: float, weft: float) -> AxisProjection:
    scalar = _geometric_mean(warp, weft)
    ratio = max(warp, weft) / min(warp, weft)
    error = max(abs(scalar - warp) / warp, abs(scalar - weft) / weft)
    return AxisProjection(
        warp=warp,
        weft=weft,
        scalar_proxy=scalar,
        anisotropy_ratio=ratio,
        maximum_relative_error=error,
    )


def _log_normalize(value: float, population: Sequence[float]) -> float:
    if value <= 0 or any(item <= 0 for item in population):
        raise ValueError("log-normalized properties must be positive")
    lower = min(math.log(item) for item in population)
    upper = max(math.log(item) for item in population)
    if math.isclose(lower, upper):
        return 0.5
    return (math.log(value) - lower) / (upper - lower)


def _range_map(normalized: float, limits: tuple[float, float]) -> float:
    if not 0 <= normalized <= 1:
        raise ValueError("normalized value must be between zero and one")
    return limits[0] + normalized * (limits[1] - limits[0])


def blender_collider_friction_percent(coefficient: float) -> float:
    """Map a Coulomb coefficient to Blender's collider percentage scale."""

    if not math.isfinite(coefficient) or not 0 <= coefficient <= 0.8:
        raise ValueError("Blender collider friction requires a coefficient in [0, 0.8]")
    return coefficient * 100.0


def project_material_library_to_blender(
    materials: Sequence[MaterialSpec],
    profile: BlenderCalibrationProfile,
    *,
    grain_angles_degrees: Mapping[str, float] | None = None,
) -> tuple[BlenderMaterialProjection, ...]:
    """Project one measured library while preserving all lossy mapping evidence."""

    if len(materials) < 2:
        raise ValueError("relative Blender calibration requires at least two materials")
    identifiers = [item.material_id for item in materials]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("material IDs must be unique")
    grain_angles_degrees = grain_angles_degrees or {}

    stretch_scalars = [
        _geometric_mean(
            item.properties.stretch_warp_g_s2,
            item.properties.stretch_weft_g_s2,
        )
        for item in materials
    ]
    shear_values = [item.properties.shear_g_s2 for item in materials]
    bending_scalars = [
        _geometric_mean(
            item.properties.bending_warp_g_mm2_s2,
            item.properties.bending_weft_g_mm2_s2,
        )
        for item in materials
    ]

    projections: list[BlenderMaterialProjection] = []
    for material, stretch_scalar, bending_scalar in zip(
        materials, stretch_scalars, bending_scalars, strict=True
    ):
        properties = material.properties
        stretch = _axis_projection(
            properties.stretch_warp_g_s2, properties.stretch_weft_g_s2
        )
        bending = _axis_projection(
            properties.bending_warp_g_mm2_s2,
            properties.bending_weft_g_mm2_s2,
        )
        tension = _range_map(
            _log_normalize(stretch_scalar, stretch_scalars), profile.tension_range
        )
        shear = _range_map(
            _log_normalize(properties.shear_g_s2, shear_values), profile.shear_range
        )
        bend = _range_map(
            _log_normalize(bending_scalar, bending_scalars), profile.bending_range
        )
        compression = tension * profile.buckling_compression_ratio
        collision_distance = properties.collision_thickness_mm / 1000.0
        render_thickness = properties.render_thickness_mm / 1000.0
        warnings = [
            "Blender 4.4 surface spring stiffness is scalar; warp/weft axes are retained but projected with a geometric-mean proxy.",
            "compression_stiffness is an in-plane buckling proxy derived from stretch stiffness; through-thickness compressionKpa is not mapped.",
            "CollisionSettings.cloth_friction uses Blender's 0-80 percentage scale, so the stored Coulomb coefficient is multiplied by 100 explicitly.",
        ]
        if not properties.simulation_ready:
            warnings.append(
                "Measured contact friction and/or through-thickness compression are absent; the declared low-confidence contact hypothesis is used only for Blender calibration."
            )
        mapping_id = f"{profile.profile_id}:{material.material_id}"
        projections.append(
            BlenderMaterialProjection(
                schema_version=1,
                mapping_id=mapping_id,
                material_id=material.material_id,
                blender_version=profile.blender_version,
                source_library=profile.source_library,
                source_url=material.source_url,
                source_license=material.source_license,
                grain_angle_degrees=float(
                    grain_angles_degrees.get(material.material_id, 0.0)
                ),
                surface_density_kg_m2=properties.areal_mass_g_m2 / 1000.0,
                physical_thickness_m=properties.physical_thickness_mm / 1000.0,
                collision_thickness_m=collision_distance,
                render_thickness_m=render_thickness,
                cloth_settings={
                    "tension_stiffness": tension,
                    "compression_stiffness": compression,
                    "shear_stiffness": shear,
                    "bending_stiffness": bend,
                    "tension_damping": profile.tension_damping,
                    "compression_damping": profile.compression_damping,
                    "shear_damping": profile.shear_damping,
                    "bending_damping": profile.bending_damping,
                    "air_damping": profile.air_damping,
                    "quality": profile.quality,
                    "collider_friction": profile.contact.dynamic_friction,
                },
                cloth_collision_settings={
                    "use_collision": True,
                    "collision_quality": profile.collision_quality,
                    "distance_min": collision_distance,
                    "use_self_collision": True,
                    "self_distance_min": collision_distance
                    * profile.self_collision_scale,
                },
                collider_settings={
                    "cloth_friction": blender_collider_friction_percent(
                        profile.contact.static_friction
                    ),
                    "thickness_outer": collision_distance,
                },
                render_settings={"solidify_thickness": render_thickness},
                stretch_projection=stretch,
                bending_projection=bending,
                source_axes={
                    "stretchWarpGs2": properties.stretch_warp_g_s2,
                    "stretchWeftGs2": properties.stretch_weft_g_s2,
                    "shearGs2": properties.shear_g_s2,
                    "bendingWarpGmm2s2": properties.bending_warp_g_mm2_s2,
                    "bendingWeftGmm2s2": properties.bending_weft_g_mm2_s2,
                },
                unmapped_source_properties={
                    "throughThicknessCompressionKpa": properties.compression_kpa,
                    "measuredStaticFriction": properties.static_friction,
                    "measuredDynamicFriction": properties.dynamic_friction,
                },
                conversion_error={
                    "stretchScalarMaximumRelativeError": stretch.maximum_relative_error,
                    "bendingScalarMaximumRelativeError": bending.maximum_relative_error,
                    "contactHypothesisUncertainty": 1.0 - profile.contact.confidence,
                },
                contact_hypothesis=profile.contact,
                warnings=tuple(warnings),
            )
        )
    return tuple(projections)
