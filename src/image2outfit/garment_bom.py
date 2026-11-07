"""Industrial garment BOM, layer stack, and attachment contracts (issue #182).

The visible part enumeration of decompose-garment does not say how a garment
is made or supported. This module is the machine-readable schema for the
missing facts: shell, lining, facing, interfacing, trim, hardware, and closure
components, their material and cut specifications, the attachment relations
between them, and the production work those facts imply.

Invisible components are never treated as absent. Every component role must
be declared in the class inventory as present, absent, or undetermined.
Absence requires observed evidence, and undetermined classes cannot carry
component entries.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
SCHEMA_VERSION = 1


class ComponentRole(StrEnum):
    SHELL = "shell"
    LINING = "lining"
    FACING = "facing"
    INTERFACING = "interfacing"
    TRIM = "trim"
    HARDWARE = "hardware"
    CLOSURE = "closure"


CUT_ROLES = frozenset(
    {
        ComponentRole.SHELL,
        ComponentRole.LINING,
        ComponentRole.FACING,
        ComponentRole.INTERFACING,
    }
)


class StructuralRole(StrEnum):
    SUPPORT = "support"
    DECORATIVE = "decorative"
    CLOSURE = "closure"
    EDGE_FINISH = "edge-finish"
    REINFORCEMENT = "reinforcement"


class ObservationState(StrEnum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


class Presence(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNDETERMINED = "undetermined"


class AttachmentKind(StrEnum):
    SEWN_TO = "sewn-to"
    FUSED_TO = "fused-to"
    LAYERED_OVER = "layered-over"
    SUSPENDED_FROM = "suspended-from"
    RIGIDLY_ATTACHED = "rigidly-attached"


SUPPORTING_KINDS = frozenset(
    {
        AttachmentKind.SEWN_TO,
        AttachmentKind.FUSED_TO,
        AttachmentKind.SUSPENDED_FROM,
        AttachmentKind.RIGIDLY_ATTACHED,
    }
)


class Grainline(StrEnum):
    WARP = "warp"
    WEFT = "weft"
    BIAS = "bias"
    NONE = "none"


class Stretch(StrEnum):
    NONE = "none"
    WARP = "warp"
    WEFT = "weft"
    BIAS = "bias"
    MULTI = "multi"


class Transparency(StrEnum):
    OPAQUE = "opaque"
    SEMI_TRANSPARENT = "semi-transparent"
    SHEER = "sheer"


class GravityMode(StrEnum):
    FIXED_TO_SUPPORT = "fixed-to-support"
    HUNG_FROM_SUPPORT = "hung-from-support"
    TENSIONED_BY_SUPPORT = "tensioned-by-support"


class WorkKind(StrEnum):
    PATTERN = "pattern"
    SEWING = "sewing"
    FUSING = "fusing"
    FABRIC = "fabric"
    HARDWARE = "hardware"
    DESIGN_REVIEW = "design-review"


class Discipline(StrEnum):
    COSTUME_DESIGNER = "costume-designer"
    PATTERN_MAKER = "pattern-maker"
    SEWER = "sewer"
    FABRIC_SOURCING = "fabric-sourcing"
    HARDWARE_FITTER = "hardware-fitter"


def _identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must be kebab-case: {value!r}")


def _text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")


def _number(value: float, label: str, *, positive: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    if not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    if value < 0 or (positive and value == 0):
        raise ValueError(f"{label} must be {'positive' if positive else '>= 0'}")


def _unit_interval(value: float, label: str) -> None:
    _number(value, label)
    if not 0 <= value <= 1:
        raise ValueError(f"{label} must be between zero and one")


def _reject_unknown(data: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(data).difference(allowed))
    if unknown:
        raise ValueError(f"{label} contains unknown fields: {unknown}")


def _required(data: Mapping[str, Any], key: str, label: str) -> Any:
    if key not in data:
        raise ValueError(f"{label} is missing required field {key!r}")
    return data[key]


@dataclass(frozen=True, slots=True)
class MaterialSpec:
    name: str
    thickness_mm: float
    grams_per_m2: float
    stretch: Stretch
    transparency: Transparency

    def __post_init__(self) -> None:
        _text(self.name, "material name")
        _number(self.thickness_mm, "thickness_mm", positive=True)
        _number(self.grams_per_m2, "grams_per_m2", positive=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "thickness_mm": self.thickness_mm,
            "grams_per_m2": self.grams_per_m2,
            "stretch": self.stretch.value,
            "transparency": self.transparency.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MaterialSpec:
        _reject_unknown(
            data,
            {"name", "thickness_mm", "grams_per_m2", "stretch", "transparency"},
            "material",
        )
        return cls(
            name=_required(data, "name", "material"),
            thickness_mm=_required(data, "thickness_mm", "material"),
            grams_per_m2=_required(data, "grams_per_m2", "material"),
            stretch=Stretch(_required(data, "stretch", "material")),
            transparency=Transparency(_required(data, "transparency", "material")),
        )


@dataclass(frozen=True, slots=True)
class SupportSpec:
    """Required for decorative, trim, hardware, and closure components."""

    support_component_id: str
    contact_surface: str
    attachment_point: str
    gravity_mode: GravityMode

    def __post_init__(self) -> None:
        _identifier(self.support_component_id, "support_component_id")
        _text(self.contact_surface, "support contact_surface")
        _text(self.attachment_point, "support attachment_point")

    def to_dict(self) -> dict[str, Any]:
        return {
            "support_component_id": self.support_component_id,
            "contact_surface": self.contact_surface,
            "attachment_point": self.attachment_point,
            "gravity_mode": self.gravity_mode.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SupportSpec:
        _reject_unknown(
            data,
            {
                "support_component_id",
                "contact_surface",
                "attachment_point",
                "gravity_mode",
            },
            "support",
        )
        return cls(
            support_component_id=_required(data, "support_component_id", "support"),
            contact_surface=_required(data, "contact_surface", "support"),
            attachment_point=_required(data, "attachment_point", "support"),
            gravity_mode=GravityMode(_required(data, "gravity_mode", "support")),
        )


_COMPONENT_KEYS = {
    "component_id",
    "role",
    "structural_role",
    "layer_index",
    "material",
    "state",
    "confidence",
    "cut_count",
    "grainline",
    "mirror",
    "on_fold",
    "seam_allowance_mm",
    "edge_finish",
    "evidence_regions",
    "rationale",
    "support",
}


@dataclass(frozen=True, slots=True)
class Component:
    component_id: str
    role: ComponentRole
    structural_role: StructuralRole
    layer_index: int
    material: MaterialSpec
    state: ObservationState
    confidence: float
    cut_count: int | None = None
    grainline: Grainline = Grainline.NONE
    mirror: bool = False
    on_fold: bool = False
    seam_allowance_mm: float = 0.0
    edge_finish: str = "none"
    evidence_regions: tuple[str, ...] = ()
    rationale: str = ""
    support: SupportSpec | None = None

    def __post_init__(self) -> None:
        _identifier(self.component_id, "component_id")
        if (
            isinstance(self.layer_index, bool)
            or not isinstance(self.layer_index, int)
            or self.layer_index < 0
        ):
            raise ValueError(
                f"{self.component_id}: layer_index must be an integer >= 0"
            )
        _unit_interval(self.confidence, f"{self.component_id}: confidence")
        _number(self.seam_allowance_mm, f"{self.component_id}: seam_allowance_mm")
        _text(self.edge_finish, f"{self.component_id}: edge_finish")

        if self.state is ObservationState.OBSERVED:
            if not self.evidence_regions:
                raise ValueError(
                    f"{self.component_id}: observed component requires evidence regions"
                )
            if self.confidence <= 0:
                raise ValueError(
                    f"{self.component_id}: observed component needs positive confidence"
                )
        elif self.state is ObservationState.INFERRED:
            _text(self.rationale, f"{self.component_id}: inferred rationale")
            if self.confidence >= 1:
                raise ValueError(
                    f"{self.component_id}: inferred component cannot be certain"
                )
        else:
            if self.confidence != 0:
                raise ValueError(
                    f"{self.component_id}: unknown component must have zero confidence"
                )

        if self.role in CUT_ROLES:
            if self.cut_count is None:
                if self.state is not ObservationState.UNKNOWN:
                    raise ValueError(
                        f"{self.component_id}: cut components require cut_count "
                        "unless their state is unknown"
                    )
            elif isinstance(self.cut_count, bool) or self.cut_count < 1:
                raise ValueError(f"{self.component_id}: cut_count must be >= 1")
        elif self.cut_count is not None:
            raise ValueError(
                f"{self.component_id}: only cut components declare cut_count"
            )

        needs_support = self.role in (ComponentRole.TRIM, ComponentRole.HARDWARE) or (
            self.structural_role in (StructuralRole.DECORATIVE, StructuralRole.CLOSURE)
        )
        if needs_support and self.support is None:
            raise ValueError(
                f"{self.component_id}: trim, hardware, decorative, and closure "
                "components require a support declaration"
            )
        if self.support is not None and (
            self.support.support_component_id == self.component_id
        ):
            raise ValueError(f"{self.component_id}: component cannot support itself")

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "role": self.role.value,
            "structural_role": self.structural_role.value,
            "layer_index": self.layer_index,
            "material": self.material.to_dict(),
            "state": self.state.value,
            "confidence": self.confidence,
            "cut_count": self.cut_count,
            "grainline": self.grainline.value,
            "mirror": self.mirror,
            "on_fold": self.on_fold,
            "seam_allowance_mm": self.seam_allowance_mm,
            "edge_finish": self.edge_finish,
            "evidence_regions": list(self.evidence_regions),
            "rationale": self.rationale,
            "support": None if self.support is None else self.support.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Component:
        _reject_unknown(data, _COMPONENT_KEYS, "component")
        support = data.get("support")
        return cls(
            component_id=_required(data, "component_id", "component"),
            role=ComponentRole(_required(data, "role", "component")),
            structural_role=StructuralRole(
                _required(data, "structural_role", "component")
            ),
            layer_index=_required(data, "layer_index", "component"),
            material=MaterialSpec.from_dict(_required(data, "material", "component")),
            state=ObservationState(_required(data, "state", "component")),
            confidence=_required(data, "confidence", "component"),
            cut_count=data.get("cut_count"),
            grainline=Grainline(data.get("grainline", Grainline.NONE.value)),
            mirror=bool(data.get("mirror", False)),
            on_fold=bool(data.get("on_fold", False)),
            seam_allowance_mm=data.get("seam_allowance_mm", 0.0),
            edge_finish=data.get("edge_finish", "none"),
            evidence_regions=tuple(data.get("evidence_regions", ())),
            rationale=data.get("rationale", ""),
            support=None if support is None else SupportSpec.from_dict(support),
        )


@dataclass(frozen=True, slots=True)
class AttachmentRelation:
    """``source`` is attached to ``target``; for layered-over, source sits above."""

    relation_id: str
    kind: AttachmentKind
    source_id: str
    target_id: str

    def __post_init__(self) -> None:
        _identifier(self.relation_id, "relation_id")
        _identifier(self.source_id, "relation source_id")
        _identifier(self.target_id, "relation target_id")
        if self.source_id == self.target_id:
            raise ValueError(f"relation {self.relation_id!r} cannot target itself")

    def to_dict(self) -> dict[str, str]:
        return {
            "relation_id": self.relation_id,
            "kind": self.kind.value,
            "source_id": self.source_id,
            "target_id": self.target_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AttachmentRelation:
        _reject_unknown(
            data, {"relation_id", "kind", "source_id", "target_id"}, "relation"
        )
        return cls(
            relation_id=_required(data, "relation_id", "relation"),
            kind=AttachmentKind(_required(data, "kind", "relation")),
            source_id=_required(data, "source_id", "relation"),
            target_id=_required(data, "target_id", "relation"),
        )


@dataclass(frozen=True, slots=True)
class ClassInventory:
    """Explicit statement about one component role for the whole garment."""

    role: ComponentRole
    presence: Presence
    state: ObservationState
    confidence: float
    evidence_regions: tuple[str, ...] = ()
    rationale: str = ""

    def __post_init__(self) -> None:
        _unit_interval(self.confidence, f"{self.role.value} inventory confidence")
        if self.presence is Presence.ABSENT:
            if self.state is not ObservationState.OBSERVED or not self.evidence_regions:
                raise ValueError(
                    f"{self.role.value}: absence requires observed evidence regions"
                )
        elif self.presence is Presence.PRESENT:
            if self.state is ObservationState.UNKNOWN:
                raise ValueError(f"{self.role.value}: present class cannot be unknown")
            if self.state is ObservationState.OBSERVED and not self.evidence_regions:
                raise ValueError(f"{self.role.value}: observed class requires evidence")
            if self.state is ObservationState.INFERRED:
                _text(self.rationale, f"{self.role.value} inferred rationale")
        else:
            if self.state is not ObservationState.UNKNOWN:
                raise ValueError(
                    f"{self.role.value}: undetermined class must be unknown"
                )
            _text(self.rationale, f"{self.role.value} undetermined rationale")

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "presence": self.presence.value,
            "state": self.state.value,
            "confidence": self.confidence,
            "evidence_regions": list(self.evidence_regions),
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ClassInventory:
        _reject_unknown(
            data,
            {
                "role",
                "presence",
                "state",
                "confidence",
                "evidence_regions",
                "rationale",
            },
            "class inventory",
        )
        return cls(
            role=ComponentRole(_required(data, "role", "class inventory")),
            presence=Presence(_required(data, "presence", "class inventory")),
            state=ObservationState(_required(data, "state", "class inventory")),
            confidence=_required(data, "confidence", "class inventory"),
            evidence_regions=tuple(data.get("evidence_regions", ())),
            rationale=data.get("rationale", ""),
        )


@dataclass(frozen=True, slots=True)
class GarmentBOM:
    bom_id: str
    garment_id: str
    components: tuple[Component, ...]
    relations: tuple[AttachmentRelation, ...]
    class_inventory: tuple[ClassInventory, ...]
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported GarmentBOM schema_version")
        _identifier(self.bom_id, "bom_id")
        _identifier(self.garment_id, "garment_id")

        component_ids = [item.component_id for item in self.components]
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("component IDs must be unique")
        relation_ids = [item.relation_id for item in self.relations]
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("relation IDs must be unique")
        by_id = {item.component_id: item for item in self.components}

        for relation in self.relations:
            unknown = {relation.source_id, relation.target_id}.difference(by_id)
            if unknown:
                raise ValueError(
                    f"relation {relation.relation_id!r} references unknown "
                    f"components: {sorted(unknown)}"
                )
            if relation.kind is AttachmentKind.LAYERED_OVER and not (
                by_id[relation.source_id].layer_index
                > by_id[relation.target_id].layer_index
            ):
                raise ValueError(
                    f"relation {relation.relation_id!r}: layered-over source must "
                    "have a higher layer_index than its target"
                )

        supporting = {
            (relation.source_id, relation.target_id)
            for relation in self.relations
            if relation.kind in SUPPORTING_KINDS
        }
        for component in self.components:
            if component.support is None:
                continue
            support_id = component.support.support_component_id
            if support_id not in by_id:
                raise ValueError(
                    f"{component.component_id}: support references unknown component "
                    f"{support_id!r}"
                )
            if (component.component_id, support_id) not in supporting:
                raise ValueError(
                    f"{component.component_id}: declared support {support_id!r} has "
                    "no sewn-to, fused-to, suspended-from, or rigidly-attached relation"
                )

        self._validate_class_inventory()

    def _validate_class_inventory(self) -> None:
        roles = [item.role for item in self.class_inventory]
        if len(roles) != len(set(roles)):
            raise ValueError("class inventory roles must be unique")
        missing = sorted(role.value for role in ComponentRole if role not in roles)
        if missing:
            raise ValueError(f"class inventory must declare every role: {missing}")
        for entry in self.class_inventory:
            members = [item for item in self.components if item.role is entry.role]
            if entry.presence is Presence.PRESENT and not members:
                raise ValueError(
                    f"{entry.role.value}: present class has no component entry"
                )
            if entry.presence is not Presence.PRESENT and members:
                raise ValueError(
                    f"{entry.role.value}: {entry.presence.value} class must not "
                    "have component entries"
                )

    def component(self, component_id: str) -> Component:
        for item in self.components:
            if item.component_id == component_id:
                return item
        raise KeyError(component_id)

    def layer_order(self) -> tuple[str, ...]:
        """Component IDs from the innermost (lowest) to the outermost layer."""
        ordered = sorted(
            self.components, key=lambda item: (item.layer_index, item.component_id)
        )
        return tuple(item.component_id for item in ordered)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "bom_id": self.bom_id,
            "garment_id": self.garment_id,
            "components": [item.to_dict() for item in self.components],
            "relations": [item.to_dict() for item in self.relations],
            "class_inventory": [item.to_dict() for item in self.class_inventory],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GarmentBOM:
        _reject_unknown(
            data,
            {
                "schema_version",
                "bom_id",
                "garment_id",
                "components",
                "relations",
                "class_inventory",
            },
            "GarmentBOM",
        )
        return cls(
            schema_version=_required(data, "schema_version", "GarmentBOM"),
            bom_id=_required(data, "bom_id", "GarmentBOM"),
            garment_id=_required(data, "garment_id", "GarmentBOM"),
            components=tuple(
                Component.from_dict(item)
                for item in _required(data, "components", "GarmentBOM")
            ),
            relations=tuple(
                AttachmentRelation.from_dict(item)
                for item in _required(data, "relations", "GarmentBOM")
            ),
            class_inventory=tuple(
                ClassInventory.from_dict(item)
                for item in _required(data, "class_inventory", "GarmentBOM")
            ),
        )


@dataclass(frozen=True, slots=True)
class WorkItem:
    kind: WorkKind
    discipline: Discipline
    component_ids: tuple[str, ...]
    detail: str
    review_required: bool


def derive_work_plan(bom: GarmentBOM) -> tuple[WorkItem, ...]:
    """Derive Pattern, Sewing, Fusing, Fabric, Hardware, and review work.

    Work that depends on an observed-only fact is flagged ``review_required``
    when any referenced component is inferred or unknown. Layer order alone
    (layered-over) creates no separate production work.
    """
    by_id = {item.component_id: item for item in bom.components}
    items: list[WorkItem] = []

    for component in bom.components:
        uncertain = component.state is not ObservationState.OBSERVED
        if component.cut_count:
            items.append(
                WorkItem(
                    kind=WorkKind.PATTERN,
                    discipline=Discipline.PATTERN_MAKER,
                    component_ids=(component.component_id,),
                    detail=(
                        f"cut {component.cut_count}x; grainline="
                        f"{component.grainline.value}; mirror={component.mirror}; "
                        f"on-fold={component.on_fold}; seam-allowance-mm="
                        f"{component.seam_allowance_mm:g}"
                    ),
                    review_required=uncertain,
                )
            )
        if component.role in (ComponentRole.HARDWARE, ComponentRole.CLOSURE):
            items.append(
                WorkItem(
                    kind=WorkKind.HARDWARE,
                    discipline=Discipline.HARDWARE_FITTER,
                    component_ids=(component.component_id,),
                    detail=f"fit {component.role.value} ({component.material.name})",
                    review_required=uncertain,
                )
            )
        if uncertain:
            items.append(
                WorkItem(
                    kind=WorkKind.DESIGN_REVIEW,
                    discipline=Discipline.COSTUME_DESIGNER,
                    component_ids=(component.component_id,),
                    detail=(
                        f"confirm {component.state.value} {component.role.value} "
                        "presence and specification"
                    ),
                    review_required=True,
                )
            )

    by_material: dict[str, list[Component]] = {}
    for component in bom.components:
        by_material.setdefault(component.material.name, []).append(component)
    for name in sorted(by_material):
        members = sorted(by_material[name], key=lambda item: item.component_id)
        items.append(
            WorkItem(
                kind=WorkKind.FABRIC,
                discipline=Discipline.FABRIC_SOURCING,
                component_ids=tuple(item.component_id for item in members),
                detail=f"source material {name}",
                review_required=any(
                    item.state is not ObservationState.OBSERVED for item in members
                ),
            )
        )

    for relation in bom.relations:
        pair = (relation.source_id, relation.target_id)
        uncertain = any(
            by_id[item].state is not ObservationState.OBSERVED for item in pair
        )
        if relation.kind is AttachmentKind.SEWN_TO:
            kind, discipline = WorkKind.SEWING, Discipline.SEWER
        elif relation.kind is AttachmentKind.FUSED_TO:
            kind, discipline = WorkKind.FUSING, Discipline.SEWER
        elif relation.kind in (
            AttachmentKind.SUSPENDED_FROM,
            AttachmentKind.RIGIDLY_ATTACHED,
        ):
            kind, discipline = WorkKind.HARDWARE, Discipline.HARDWARE_FITTER
        else:
            continue
        items.append(
            WorkItem(
                kind=kind,
                discipline=discipline,
                component_ids=pair,
                detail=f"{relation.source_id} {relation.kind.value} {relation.target_id}",
                review_required=uncertain,
            )
        )

    return tuple(
        sorted(
            items, key=lambda item: (item.kind.value, item.component_ids, item.detail)
        )
    )
