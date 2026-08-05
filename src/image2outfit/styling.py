"""Declarative, reversible garment styling operations and constraints."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Mapping


class StylingOperationKind(StrEnum):
    POINT_ANCHOR = "point-anchor"
    LINE_ANCHOR = "line-anchor"
    REGION_ANCHOR = "region-anchor"
    FOLD = "fold"
    WRAP = "wrap"
    TUCK = "tuck"
    CLOSURE = "closure"
    LAYER_ORDER = "layer-order"
    ASYMMETRIC_OFFSET = "asymmetric-offset"


class ConstraintTargetKind(StrEnum):
    AVATAR_LANDMARK = "avatar-landmark"
    AVATAR_REGION = "avatar-region"
    GARMENT_EDGE = "garment-edge"
    GARMENT_REGION = "garment-region"
    GARMENT_COMPONENT = "garment-component"


class StylingPhase(StrEnum):
    INITIALIZATION = "initialization"
    SIMULATION = "simulation"
    POST_SIMULATION = "post-simulation"


@dataclass(frozen=True, slots=True)
class StylingOperation:
    operation_id: str
    kind: StylingOperationKind
    target_kind: ConstraintTargetKind
    target_ids: tuple[str, ...]
    anchor_target_ids: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    phase: StylingPhase = StylingPhase.INITIALIZATION
    order: int = 0
    strength: float = 1.0
    friction: float = 0.0
    release_condition: str = "never"
    reversible: bool = True
    parameters: Mapping[str, str | int | float | bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.operation_id.strip() or not self.target_ids:
            raise ValueError("styling operation ID and targets are required")
        if len(self.target_ids) != len(set(self.target_ids)):
            raise ValueError("styling target IDs must be unique")
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError("styling dependencies must be unique")
        if self.operation_id in self.depends_on:
            raise ValueError("styling operation cannot depend on itself")
        if self.order < 0:
            raise ValueError("styling operation order must be non-negative")
        if not math.isfinite(self.strength) or self.strength < 0:
            raise ValueError("styling strength must be finite and non-negative")
        if not math.isfinite(self.friction) or self.friction < 0:
            raise ValueError("styling friction must be finite and non-negative")
        if not self.release_condition.strip():
            raise ValueError("styling release_condition is required")
        for key, value in self.parameters.items():
            if not key.strip() or not isinstance(value, (str, int, float, bool)):
                raise ValueError("styling parameters must be scalar JSON values")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("styling parameters must be finite")


@dataclass(frozen=True, slots=True)
class StylingConflict:
    first_operation_id: str
    second_operation_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class StylingSpec:
    operations: tuple[StylingOperation, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported StylingSpec schema_version")
        identifiers = [item.operation_id for item in self.operations]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("styling operation IDs must be unique")
        known = set(identifiers)
        for operation in self.operations:
            unknown = sorted(set(operation.depends_on).difference(known))
            if unknown:
                raise ValueError(
                    f"operation {operation.operation_id!r} depends on unknown operations: {unknown}"
                )
        self.application_order()

    def application_order(self) -> tuple[StylingOperation, ...]:
        by_id = {item.operation_id: item for item in self.operations}
        remaining = {
            item.operation_id: set(item.depends_on) for item in self.operations
        }
        result: list[StylingOperation] = []
        while remaining:
            ready = sorted(
                (
                    by_id[operation_id]
                    for operation_id, dependencies in remaining.items()
                    if not dependencies
                ),
                key=lambda item: (item.phase.value, item.order, item.operation_id),
            )
            if not ready:
                raise ValueError("styling operation dependency cycle detected")
            for operation in ready:
                result.append(operation)
                remaining.pop(operation.operation_id)
                for dependencies in remaining.values():
                    dependencies.discard(operation.operation_id)
        return tuple(result)

    def conflicts(self) -> tuple[StylingConflict, ...]:
        conflicts: list[StylingConflict] = []
        operations = self.application_order()
        incompatible = {
            frozenset({StylingOperationKind.TUCK, StylingOperationKind.WRAP}),
            frozenset(
                {StylingOperationKind.CLOSURE, StylingOperationKind.REGION_ANCHOR}
            ),
            frozenset(
                {StylingOperationKind.LAYER_ORDER, StylingOperationKind.POINT_ANCHOR}
            ),
        }
        for index, first in enumerate(operations):
            for second in operations[index + 1 :]:
                shared = set(first.target_ids).intersection(second.target_ids)
                if not shared:
                    continue
                if first.phase is second.phase and first.order == second.order:
                    conflicts.append(
                        StylingConflict(
                            first.operation_id,
                            second.operation_id,
                            "same target, phase, and order",
                        )
                    )
                if frozenset({first.kind, second.kind}) in incompatible:
                    conflicts.append(
                        StylingConflict(
                            first.operation_id,
                            second.operation_id,
                            "incompatible operation kinds on the same target",
                        )
                    )
        return tuple(conflicts)

    def without(self, *operation_ids: str) -> "StylingSpec":
        removed = set(operation_ids)
        remaining = []
        for operation in self.operations:
            if operation.operation_id in removed:
                if not operation.reversible:
                    raise ValueError(
                        f"operation {operation.operation_id!r} is not reversible"
                    )
                continue
            remaining.append(
                replace(
                    operation,
                    depends_on=tuple(
                        item for item in operation.depends_on if item not in removed
                    ),
                )
            )
        return StylingSpec(tuple(remaining), schema_version=self.schema_version)
