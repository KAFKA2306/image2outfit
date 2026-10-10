"""Versioned registry and common compiler for garment styling presets.

Every styling preset (tuck, sleeve roll, collar fold, neckline offset, closure,
shoulder drape, gather distribution, asymmetric hem, layer order) is one entry
in ``PRESETS``. ``compile_styling_requests`` is the single path that turns
explicit requests into a ``StylingSpec``, which remains the only input consumed
by ``arrangement.build_arrangement_plan``.

The compiler never expands a request into extra targets, never mirrors an
intentionally asymmetric operation, and fails closed on unknown presets,
out-of-range parameters, conflicts, and dependency cycles. Presets carry no
Blender/Unity API names and no product-specific coordinates.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .styling import (
    ConstraintTargetKind,
    StylingOperation,
    StylingOperationKind,
    StylingPhase,
    StylingSpec,
)

REGISTRY_VERSION = 1

SIDE_NONE = "none"
SIDE_LEFT = "left"
SIDE_RIGHT = "right"
SIDE_BOTH = "both"
SIDES = (SIDE_NONE, SIDE_LEFT, SIDE_RIGHT, SIDE_BOTH)

WHOLE_GARMENT_TARGET_ID = "whole-garment"
GATHER_DISTRIBUTIONS = ("uniform", "front-weighted", "back-weighted")

# Keys written by the compiler itself; preset parameters may not reuse them.
_RESERVED_PARAMETER_NAMES = frozenset(
    {
        "family",
        "open_state",
        "preset_id",
        "preset_revision",
        "registry_version",
        "segment_count",
        "side",
    }
)

ParameterValue = str | int | float | bool


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    name: str
    unit: str
    default: ParameterValue
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip() or self.name in _RESERVED_PARAMETER_NAMES:
            raise ValueError(f"invalid styling parameter name {self.name!r}")
        if self.choices:
            if self.minimum is not None or self.maximum is not None:
                raise ValueError("choice parameters cannot declare numeric bounds")
            if len(self.choices) != len(set(self.choices)) or not all(
                isinstance(item, str) and item for item in self.choices
            ):
                raise ValueError(f"parameter {self.name!r} has invalid choices")
            if self.default not in self.choices:
                raise ValueError(f"parameter {self.name!r} default is not a choice")
            return
        if self.minimum is None or self.maximum is None:
            raise ValueError(f"parameter {self.name!r} requires numeric bounds")
        if not math.isfinite(self.minimum) or not math.isfinite(self.maximum):
            raise ValueError(f"parameter {self.name!r} bounds must be finite")
        if self.minimum > self.maximum:
            raise ValueError(f"parameter {self.name!r} bounds are inverted")
        self.resolve(self.default)

    def resolve(self, value: ParameterValue) -> ParameterValue:
        """Validate ``value`` and return its canonical scalar form."""

        if self.choices:
            if not isinstance(value, str) or value not in self.choices:
                raise ValueError(
                    f"parameter {self.name!r} must be one of {list(self.choices)}"
                )
            return value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"parameter {self.name!r} must be numeric")
        if not math.isfinite(value):
            raise ValueError(f"parameter {self.name!r} must be finite")
        if self.unit == "count" and not float(value).is_integer():
            raise ValueError(f"parameter {self.name!r} must be an integer count")
        assert self.minimum is not None and self.maximum is not None
        if not self.minimum <= value <= self.maximum:
            raise ValueError(
                f"parameter {self.name!r} must be within "
                f"[{self.minimum}, {self.maximum}] {self.unit}"
            )
        return int(value) if self.unit == "count" else float(value)


@dataclass(frozen=True, slots=True)
class OperationPreset:
    preset_id: str
    family: str
    kind: StylingOperationKind
    target_kind: ConstraintTargetKind
    sides: tuple[str, ...]
    parameters: tuple[ParameterSpec, ...] = ()
    min_targets: int = 1
    min_anchors: int = 0
    revision: int = 1

    def __post_init__(self) -> None:
        if not self.preset_id.strip() or not self.family.strip():
            raise ValueError("styling preset identity is required")
        if not self.sides or any(item not in SIDES for item in self.sides):
            raise ValueError(f"preset {self.preset_id!r} has invalid sides")
        if len(self.sides) != len(set(self.sides)):
            raise ValueError(f"preset {self.preset_id!r} repeats a side")
        names = [item.name for item in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError(f"preset {self.preset_id!r} repeats a parameter")
        if self.min_targets < 1 or self.min_anchors < 0 or self.revision < 1:
            raise ValueError(f"preset {self.preset_id!r} has invalid limits")

    def parameter(self, name: str) -> ParameterSpec | None:
        return next((item for item in self.parameters if item.name == name), None)


def _mm(name: str, default: float, minimum: float, maximum: float) -> ParameterSpec:
    return ParameterSpec(name, "mm", default, minimum, maximum)


def _count(name: str, default: int, minimum: int, maximum: int) -> ParameterSpec:
    return ParameterSpec(name, "count", default, minimum, maximum)


def _fraction(name: str, default: float) -> ParameterSpec:
    return ParameterSpec(name, "fraction", default, 0.0, 1.0)


def _gather_parameters() -> tuple[ParameterSpec, ...]:
    return (
        ParameterSpec("excess_mm", "mm", 100.0, 1.0, 2000.0),
        ParameterSpec(
            "distribution",
            "choice",
            "uniform",
            choices=GATHER_DISTRIBUTIONS,
        ),
    )


def _build_presets() -> tuple[OperationPreset, ...]:
    garment_region = ConstraintTargetKind.GARMENT_REGION
    garment_edge = ConstraintTargetKind.GARMENT_EDGE
    presets: list[OperationPreset] = [
        # Tuck: only the declared targets are constrained, never the back hem.
        OperationPreset(
            "front-tuck",
            "tuck",
            StylingOperationKind.TUCK,
            garment_region,
            (SIDE_NONE,),
            (_mm("depth_mm", 35.0, 0.0, 200.0), _mm("width_mm", 120.0, 10.0, 400.0)),
            min_anchors=1,
        ),
        OperationPreset(
            "half-tuck",
            "tuck",
            StylingOperationKind.TUCK,
            garment_region,
            (SIDE_NONE,),
            (
                _mm("depth_mm", 35.0, 0.0, 200.0),
                _mm("width_mm", 120.0, 10.0, 400.0),
                _fraction("coverage_fraction", 0.5),
            ),
            min_anchors=1,
        ),
        OperationPreset(
            "side-tuck",
            "tuck",
            StylingOperationKind.TUCK,
            garment_region,
            (SIDE_LEFT, SIDE_RIGHT),
            (_mm("depth_mm", 35.0, 0.0, 200.0), _mm("width_mm", 120.0, 10.0, 400.0)),
            min_anchors=1,
        ),
        OperationPreset(
            "rolled-cuff",
            "sleeve-roll",
            StylingOperationKind.FOLD,
            garment_edge,
            (SIDE_LEFT, SIDE_RIGHT),
            (_count("turns", 2, 1, 6), _mm("width_mm", 40.0, 5.0, 200.0)),
        ),
        OperationPreset(
            "scrunched-sleeve",
            "sleeve-roll",
            StylingOperationKind.FOLD,
            garment_region,
            (SIDE_LEFT, SIDE_RIGHT),
            (_count("turns", 4, 1, 12), _mm("width_mm", 80.0, 20.0, 300.0)),
        ),
        # Collar fold: fold line (targets) and seam (anchors) must stay distinct.
        OperationPreset(
            "popped-collar",
            "collar-fold",
            StylingOperationKind.FOLD,
            garment_edge,
            (SIDE_NONE,),
            (ParameterSpec("angle_deg", "deg", 90.0, 0.0, 180.0),),
            min_anchors=1,
        ),
        OperationPreset(
            "folded-collar",
            "collar-fold",
            StylingOperationKind.FOLD,
            garment_edge,
            (SIDE_NONE,),
            (_mm("fold_depth_mm", 15.0, 0.0, 60.0),),
            min_anchors=1,
        ),
        OperationPreset(
            "lapel-fold",
            "collar-fold",
            StylingOperationKind.FOLD,
            garment_edge,
            (SIDE_LEFT, SIDE_RIGHT),
            (_mm("fold_depth_mm", 25.0, 0.0, 80.0),),
            min_anchors=1,
        ),
        # Neckline offset: must target a neckline region, never the whole garment.
        OperationPreset(
            "neckline-rear-offset",
            "neckline-offset",
            StylingOperationKind.ASYMMETRIC_OFFSET,
            garment_region,
            (SIDE_NONE,),
            (_mm("offset_mm", 30.0, 0.0, 200.0),),
            min_anchors=1,
        ),
        OperationPreset(
            "off-shoulder-one-side",
            "neckline-offset",
            StylingOperationKind.ASYMMETRIC_OFFSET,
            garment_region,
            (SIDE_LEFT, SIDE_RIGHT),
            (_mm("offset_mm", 60.0, 0.0, 200.0),),
            min_anchors=1,
        ),
        OperationPreset(
            "off-shoulder-both",
            "neckline-offset",
            StylingOperationKind.ASYMMETRIC_OFFSET,
            garment_region,
            (SIDE_BOTH,),
            (_mm("offset_mm", 60.0, 0.0, 200.0),),
            min_anchors=1,
        ),
        # Closure: one topology; partial-open states differ only by open_fraction.
        OperationPreset(
            "closure",
            "closure",
            StylingOperationKind.CLOSURE,
            garment_edge,
            (SIDE_NONE,),
            (
                ParameterSpec(
                    "fastener",
                    "choice",
                    "zipper",
                    choices=("button", "zipper", "snap", "buckle"),
                ),
                _fraction("open_fraction", 0.0),
            ),
            min_targets=2,
        ),
        # Shoulder drape: one-arm operations must not reference the unworn arm.
        OperationPreset(
            "both-arms",
            "shoulder-drape",
            StylingOperationKind.REGION_ANCHOR,
            garment_region,
            (SIDE_BOTH,),
            (_mm("slack_mm", 0.0, 0.0, 200.0),),
            min_anchors=1,
        ),
        OperationPreset(
            "one-arm",
            "shoulder-drape",
            StylingOperationKind.REGION_ANCHOR,
            garment_region,
            (SIDE_LEFT, SIDE_RIGHT),
            (_mm("slack_mm", 0.0, 0.0, 200.0),),
            min_anchors=1,
        ),
        OperationPreset(
            "shoulder-drape",
            "shoulder-drape",
            StylingOperationKind.WRAP,
            garment_region,
            (SIDE_NONE,),
            (_mm("drop_mm", 80.0, 0.0, 300.0),),
            min_anchors=1,
        ),
        OperationPreset(
            "cape-drape",
            "shoulder-drape",
            StylingOperationKind.WRAP,
            garment_region,
            (SIDE_NONE,),
            (_mm("drop_mm", 150.0, 0.0, 400.0),),
            min_anchors=1,
        ),
        # Asymmetric hem: sides are declared per operation and never mirrored.
        OperationPreset(
            "asymmetric-hem",
            "asymmetric-hem",
            StylingOperationKind.ASYMMETRIC_OFFSET,
            garment_edge,
            (SIDE_LEFT, SIDE_RIGHT),
            (_mm("drop_mm", 40.0, 0.0, 400.0),),
        ),
        OperationPreset(
            "side-ruche",
            "asymmetric-hem",
            StylingOperationKind.ASYMMETRIC_OFFSET,
            garment_region,
            (SIDE_LEFT, SIDE_RIGHT),
            (_mm("ruche_width_mm", 120.0, 10.0, 400.0),),
        ),
        OperationPreset(
            "side-knot",
            "asymmetric-hem",
            StylingOperationKind.POINT_ANCHOR,
            garment_region,
            (SIDE_LEFT, SIDE_RIGHT),
            (_mm("knot_offset_mm", 50.0, 0.0, 300.0),),
            min_anchors=1,
        ),
        OperationPreset(
            "one-side-drape",
            "asymmetric-hem",
            StylingOperationKind.ASYMMETRIC_OFFSET,
            garment_edge,
            (SIDE_LEFT, SIDE_RIGHT),
            (_mm("drop_mm", 200.0, 0.0, 600.0),),
        ),
        # Layer order: order must equal layer_index; contacts must go inner to outer.
        OperationPreset(
            "layer-order",
            "layer-order",
            StylingOperationKind.LAYER_ORDER,
            ConstraintTargetKind.GARMENT_COMPONENT,
            (SIDE_NONE,),
            (_count("layer_index", 0, 0, 31),),
        ),
    ]
    for preset_id, kind in (
        ("blouse-gather", StylingOperationKind.FOLD),
        ("gather", StylingOperationKind.FOLD),
        ("drawstring", StylingOperationKind.FOLD),
        ("belt", StylingOperationKind.REGION_ANCHOR),
        ("elastic", StylingOperationKind.REGION_ANCHOR),
    ):
        presets.append(
            OperationPreset(
                preset_id,
                "gather",
                kind,
                garment_region,
                (SIDE_NONE,),
                _gather_parameters(),
                min_targets=2,
            )
        )
    return tuple(presets)


PRESETS: Mapping[str, OperationPreset] = {
    item.preset_id: item for item in _build_presets()
}

FAMILIES = tuple(sorted({item.family for item in PRESETS.values()}))


@dataclass(frozen=True, slots=True)
class StylingRequest:
    operation_id: str
    preset_id: str
    target_ids: tuple[str, ...]
    anchor_target_ids: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    order: int = 0
    side: str = SIDE_NONE
    parameters: Mapping[str, ParameterValue] = field(default_factory=dict)


def _laterality(identifier: str) -> str | None:
    if identifier.endswith(".left"):
        return SIDE_LEFT
    if identifier.endswith(".right"):
        return SIDE_RIGHT
    return None


def gather_allocation(
    excess_mm: float,
    segment_count: int,
    distribution: str,
) -> tuple[float, ...]:
    """Split a gathered excess length across segments, conserving the total."""

    if not math.isfinite(excess_mm) or excess_mm <= 0:
        raise ValueError("gather excess_mm must be positive and finite")
    if segment_count < 2:
        raise ValueError("gather requires at least two segments")
    if distribution == "uniform":
        weights = [1.0] * segment_count
    elif distribution == "front-weighted":
        weights = [float(segment_count - index) for index in range(segment_count)]
    elif distribution == "back-weighted":
        weights = [float(index + 1) for index in range(segment_count)]
    else:
        raise ValueError(f"unknown gather distribution {distribution!r}")
    total = sum(weights)
    shares = [excess_mm * weight / total for weight in weights[:-1]]
    shares.append(excess_mm - sum(shares))
    return tuple(shares)


def _check_family(
    preset: OperationPreset,
    request: StylingRequest,
    resolved: Mapping[str, ParameterValue],
) -> dict[str, ParameterValue]:
    extras: dict[str, ParameterValue] = {}
    if preset.family == "collar-fold":
        if set(request.target_ids).intersection(request.anchor_target_ids):
            raise ValueError("collar fold line and seam must be distinct targets")
    elif preset.family == "neckline-offset":
        if WHOLE_GARMENT_TARGET_ID in request.target_ids:
            raise ValueError("neckline offset must target a neckline region only")
    elif preset.family == "closure":
        fraction = float(resolved["open_fraction"])
        if fraction == 0.0:
            extras["open_state"] = "closed"
        elif fraction == 1.0:
            extras["open_state"] = "open"
        else:
            extras["open_state"] = "partial"
    elif preset.preset_id == "one-arm":
        for identifier in (*request.target_ids, *request.anchor_target_ids):
            laterality = _laterality(identifier)
            if laterality is not None and laterality != request.side:
                raise ValueError(
                    f"one-arm operation references unworn arm {identifier!r}"
                )
    elif preset.family == "gather":
        excess = float(resolved["excess_mm"])
        allocation = gather_allocation(
            excess,
            len(request.target_ids),
            str(resolved["distribution"]),
        )
        if not math.isclose(sum(allocation), excess, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("gather allocation does not conserve excess_mm")
        extras["segment_count"] = len(request.target_ids)
    elif preset.family == "layer-order":
        if request.order != resolved["layer_index"]:
            raise ValueError("layer-order operation order must equal layer_index")
    return extras


def _compile_one(request: StylingRequest) -> StylingOperation:
    preset = PRESETS.get(request.preset_id)
    if preset is None:
        raise ValueError(f"unknown styling preset {request.preset_id!r}")
    if request.side not in preset.sides:
        raise ValueError(
            f"preset {preset.preset_id!r} does not accept side {request.side!r}"
        )
    declared = {item.name for item in preset.parameters}
    unknown = sorted(set(request.parameters).difference(declared))
    if unknown:
        raise ValueError(
            f"preset {preset.preset_id!r} received unknown parameters: {unknown}"
        )
    if len(request.target_ids) < preset.min_targets:
        raise ValueError(
            f"preset {preset.preset_id!r} requires at least "
            f"{preset.min_targets} target(s)"
        )
    if len(request.anchor_target_ids) < preset.min_anchors:
        raise ValueError(
            f"preset {preset.preset_id!r} requires at least "
            f"{preset.min_anchors} anchor(s)"
        )
    resolved: dict[str, ParameterValue] = {}
    for spec in preset.parameters:
        value = request.parameters.get(spec.name, spec.default)
        resolved[spec.name] = spec.resolve(value)
    extras = _check_family(preset, request, resolved)
    parameters: dict[str, ParameterValue] = {
        "family": preset.family,
        "preset_id": preset.preset_id,
        "preset_revision": preset.revision,
        "registry_version": REGISTRY_VERSION,
        "side": request.side,
        **resolved,
        **extras,
    }
    return StylingOperation(
        operation_id=request.operation_id,
        kind=preset.kind,
        target_kind=preset.target_kind,
        target_ids=request.target_ids,
        anchor_target_ids=request.anchor_target_ids,
        depends_on=request.depends_on,
        phase=StylingPhase.INITIALIZATION,
        order=request.order,
        reversible=True,
        parameters=parameters,
    )


def _check_layer_contacts(operations: Sequence[StylingOperation]) -> None:
    by_id = {item.operation_id: item for item in operations}
    for operation in operations:
        if operation.parameters.get("family") != "layer-order":
            continue
        for dependency_id in operation.depends_on:
            dependency = by_id[dependency_id]
            if dependency.parameters.get("family") != "layer-order":
                raise ValueError(
                    f"layer operation {operation.operation_id!r} depends on a "
                    "non-layer operation"
                )
            if int(dependency.parameters["layer_index"]) >= int(
                operation.parameters["layer_index"]
            ):
                raise ValueError(
                    f"layer contact {dependency_id!r} -> {operation.operation_id!r} "
                    "must go from inner to outer layer"
                )


def compile_styling_requests(requests: Sequence[StylingRequest]) -> StylingSpec:
    """Compile explicit requests into one deterministic, conflict-free spec.

    The result does not depend on the order of ``requests``: operations are
    canonicalized by ``operation_id`` and applied by ``StylingSpec`` ordering.
    """

    operations = tuple(
        _compile_one(item) for item in sorted(requests, key=lambda r: r.operation_id)
    )
    _check_layer_contacts(operations)
    spec = StylingSpec(operations)
    conflicts = spec.conflicts()
    if conflicts:
        details = "; ".join(
            f"{item.first_operation_id} vs {item.second_operation_id}: {item.reason}"
            for item in conflicts
        )
        raise ValueError(f"styling requests conflict: {details}")
    return spec


def registry_manifest() -> dict[str, object]:
    """Return the machine-readable registry description."""

    presets = []
    for preset in sorted(PRESETS.values(), key=lambda item: item.preset_id):
        presets.append(
            {
                "preset_id": preset.preset_id,
                "family": preset.family,
                "revision": preset.revision,
                "kind": preset.kind.value,
                "target_kind": preset.target_kind.value,
                "sides": list(preset.sides),
                "min_targets": preset.min_targets,
                "min_anchors": preset.min_anchors,
                "parameters": [
                    {
                        "name": item.name,
                        "unit": item.unit,
                        "default": item.default,
                        "minimum": item.minimum,
                        "maximum": item.maximum,
                        "choices": list(item.choices),
                    }
                    for item in preset.parameters
                ],
            }
        )
    return {"registry_version": REGISTRY_VERSION, "presets": presets}


def registry_sha256() -> str:
    encoded = json.dumps(
        registry_manifest(),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
