from __future__ import annotations

import dataclasses
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.garment_bom import (  # noqa: E402
    AttachmentKind,
    AttachmentRelation,
    ClassInventory,
    Component,
    ComponentRole,
    GarmentBOM,
    GravityMode,
    Grainline,
    MaterialSpec,
    ObservationState,
    Presence,
    Stretch,
    StructuralRole,
    SupportSpec,
    Transparency,
    WorkKind,
    derive_work_plan,
)


def _material(name: str, stretch: Stretch = Stretch.WARP) -> MaterialSpec:
    return MaterialSpec(
        name=name,
        thickness_mm=0.4,
        grams_per_m2=120.0,
        stretch=stretch,
        transparency=Transparency.OPAQUE,
    )


def _observed(
    component_id: str,
    role: ComponentRole,
    layer_index: int,
    material: str,
    *,
    cut_count: int | None = None,
    structural_role: StructuralRole = StructuralRole.SUPPORT,
    support: SupportSpec | None = None,
) -> Component:
    return Component(
        component_id=component_id,
        role=role,
        structural_role=structural_role,
        layer_index=layer_index,
        material=_material(material),
        state=ObservationState.OBSERVED,
        confidence=1.0,
        cut_count=cut_count,
        grainline=Grainline.WARP,
        seam_allowance_mm=10.0,
        evidence_regions=(f"{component_id}-region",),
        support=support,
    )


def _inferred(
    component_id: str,
    role: ComponentRole,
    layer_index: int,
    material: str,
    *,
    cut_count: int | None = None,
    structural_role: StructuralRole = StructuralRole.SUPPORT,
    support: SupportSpec | None = None,
) -> Component:
    return Component(
        component_id=component_id,
        role=role,
        structural_role=structural_role,
        layer_index=layer_index,
        material=_material(material),
        state=ObservationState.INFERRED,
        confidence=0.6,
        cut_count=cut_count,
        grainline=Grainline.WARP,
        seam_allowance_mm=10.0,
        rationale="hidden under the visible shell; implied by the visible hem edge",
        support=support,
    )


def _hem_support() -> SupportSpec:
    return SupportSpec(
        support_component_id="skirt-shell",
        contact_surface="skirt hem edge",
        attachment_point="hem stitch row",
        gravity_mode=GravityMode.FIXED_TO_SUPPORT,
    )


def _components() -> tuple[Component, ...]:
    return (
        _observed(
            "chest-piece-shell",
            ComponentRole.SHELL,
            3,
            "white-satin",
            cut_count=2,
        ),
        _observed("vest-shell", ComponentRole.SHELL, 2, "red-crepe", cut_count=4),
        _observed("skirt-shell", ComponentRole.SHELL, 1, "black-chiffon", cut_count=6),
        _inferred(
            "lining-bodice",
            ComponentRole.LINING,
            0,
            "ivory-cupro",
            cut_count=2,
        ),
        _inferred(
            "facing-neckline",
            ComponentRole.FACING,
            1,
            "red-crepe",
            cut_count=2,
        ),
        _observed(
            "hem-trim",
            ComponentRole.TRIM,
            2,
            "black-lace",
            structural_role=StructuralRole.DECORATIVE,
            support=_hem_support(),
        ),
        _observed(
            "halter-ring",
            ComponentRole.HARDWARE,
            2,
            "brass",
            support=SupportSpec(
                support_component_id="vest-shell",
                contact_surface="vest neckline corner",
                attachment_point="ring post",
                gravity_mode=GravityMode.HUNG_FROM_SUPPORT,
            ),
        ),
        _inferred(
            "zipper-closure",
            ComponentRole.CLOSURE,
            0,
            "nylon-zipper",
            structural_role=StructuralRole.CLOSURE,
            support=SupportSpec(
                support_component_id="lining-bodice",
                contact_surface="lining back opening edge",
                attachment_point="zipper tape stitch line",
                gravity_mode=GravityMode.FIXED_TO_SUPPORT,
            ),
        ),
    )


def _relations() -> tuple[AttachmentRelation, ...]:
    return (
        AttachmentRelation(
            "chest-over-vest",
            AttachmentKind.LAYERED_OVER,
            "chest-piece-shell",
            "vest-shell",
        ),
        AttachmentRelation(
            "vest-over-lining",
            AttachmentKind.LAYERED_OVER,
            "vest-shell",
            "lining-bodice",
        ),
        AttachmentRelation(
            "facing-sewn-to-vest",
            AttachmentKind.SEWN_TO,
            "facing-neckline",
            "vest-shell",
        ),
        AttachmentRelation(
            "hem-trim-sewn-to-skirt",
            AttachmentKind.SEWN_TO,
            "hem-trim",
            "skirt-shell",
        ),
        AttachmentRelation(
            "ring-rigidly-on-vest",
            AttachmentKind.RIGIDLY_ATTACHED,
            "halter-ring",
            "vest-shell",
        ),
        AttachmentRelation(
            "zipper-sewn-to-lining",
            AttachmentKind.SEWN_TO,
            "zipper-closure",
            "lining-bodice",
        ),
    )


def _inventory(**overrides: ClassInventory) -> tuple[ClassInventory, ...]:
    defaults = {
        "shell": ClassInventory(
            ComponentRole.SHELL,
            Presence.PRESENT,
            ObservationState.OBSERVED,
            1.0,
            evidence_regions=("front-view",),
        ),
        "lining": ClassInventory(
            ComponentRole.LINING,
            Presence.PRESENT,
            ObservationState.INFERRED,
            0.6,
            rationale="hidden layer implied by the visible hem edge",
        ),
        "facing": ClassInventory(
            ComponentRole.FACING,
            Presence.PRESENT,
            ObservationState.INFERRED,
            0.5,
            rationale="neckline finish implied by the visible edge",
        ),
        "interfacing": ClassInventory(
            ComponentRole.INTERFACING,
            Presence.UNDETERMINED,
            ObservationState.UNKNOWN,
            0.0,
            rationale="no visible evidence of fusible interlining",
        ),
        "trim": ClassInventory(
            ComponentRole.TRIM,
            Presence.PRESENT,
            ObservationState.OBSERVED,
            1.0,
            evidence_regions=("hem-edge",),
        ),
        "hardware": ClassInventory(
            ComponentRole.HARDWARE,
            Presence.PRESENT,
            ObservationState.OBSERVED,
            1.0,
            evidence_regions=("neck-corner",),
        ),
        "closure": ClassInventory(
            ComponentRole.CLOSURE,
            Presence.PRESENT,
            ObservationState.INFERRED,
            0.7,
            rationale="back opening is not visible; closure implied by the bodice",
        ),
    }
    defaults.update(overrides)
    return tuple(defaults.values())


def _bom(**overrides: object) -> GarmentBOM:
    fields: dict[str, object] = {
        "bom_id": "halter-vest-skirt-bom",
        "garment_id": "halter-vest-skirt",
        "components": _components(),
        "relations": _relations(),
        "class_inventory": _inventory(),
    }
    fields.update(overrides)
    return GarmentBOM(**fields)  # type: ignore[arg-type]


class GarmentBomTests(unittest.TestCase):
    def test_valid_bom_orders_layers_and_derives_work(self) -> None:
        bom = _bom()

        self.assertEqual(
            bom.layer_order(),
            (
                "lining-bodice",
                "zipper-closure",
                "facing-neckline",
                "skirt-shell",
                "halter-ring",
                "hem-trim",
                "vest-shell",
                "chest-piece-shell",
            ),
        )

        plan = derive_work_plan(bom)
        kinds = [item.kind for item in plan]
        self.assertEqual(kinds.count(WorkKind.SEWING), 3)
        self.assertEqual(kinds.count(WorkKind.HARDWARE), 3)
        self.assertEqual(kinds.count(WorkKind.FABRIC), 7)
        self.assertEqual(kinds.count(WorkKind.PATTERN), 5)
        self.assertNotIn(WorkKind.FUSING, kinds)

        lining_review = [
            item
            for item in plan
            if item.kind is WorkKind.DESIGN_REVIEW
            and item.component_ids == ("lining-bodice",)
        ]
        self.assertEqual(len(lining_review), 1)
        self.assertTrue(lining_review[0].review_required)

        observed_pattern = [
            item
            for item in plan
            if item.kind is WorkKind.PATTERN and item.component_ids == ("vest-shell",)
        ]
        self.assertEqual(len(observed_pattern), 1)
        self.assertFalse(observed_pattern[0].review_required)

    def test_machine_readable_round_trip_is_lossless(self) -> None:
        bom = _bom()
        encoded = json.dumps(bom.to_dict(), ensure_ascii=False)

        restored = GarmentBOM.from_dict(json.loads(encoded))

        self.assertEqual(restored, bom)

    def test_floating_trim_without_support_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "support declaration"):
            _observed("hem-trim", ComponentRole.TRIM, 2, "black-lace")

    def test_decorative_support_requires_matching_attachment_relation(self) -> None:
        relations = tuple(
            item
            for item in _relations()
            if item.relation_id != "hem-trim-sewn-to-skirt"
        )
        with self.assertRaisesRegex(ValueError, "no sewn-to"):
            _bom(relations=relations)

    def test_support_must_reference_existing_component(self) -> None:
        broken = dataclasses.replace(
            _hem_support(), support_component_id="missing-skirt"
        )
        components = tuple(
            dataclasses.replace(item, support=broken)
            if item.component_id == "hem-trim"
            else item
            for item in _components()
        )
        with self.assertRaisesRegex(ValueError, "unknown component"):
            _bom(components=components)

    def test_every_role_must_be_declared_in_class_inventory(self) -> None:
        inventory = tuple(
            item for item in _inventory() if item.role is not ComponentRole.INTERFACING
        )
        with self.assertRaisesRegex(ValueError, "must declare every role"):
            _bom(class_inventory=inventory)

    def test_absence_requires_observed_evidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "absence requires observed"):
            ClassInventory(
                ComponentRole.INTERFACING,
                Presence.ABSENT,
                ObservationState.INFERRED,
                0.5,
                rationale="looks plain",
            )

    def test_undetermined_class_cannot_carry_component_entries(self) -> None:
        interfacing = _inferred(
            "chest-interfacing",
            ComponentRole.INTERFACING,
            3,
            "fusible-woven",
            cut_count=1,
        )
        with self.assertRaisesRegex(ValueError, "must not have component entries"):
            _bom(components=_components() + (interfacing,))

    def test_present_class_requires_a_component_entry(self) -> None:
        components = tuple(
            item
            for item in _components()
            if item.role not in (ComponentRole.LINING, ComponentRole.CLOSURE)
        )
        relations = tuple(
            item
            for item in _relations()
            if item.relation_id not in ("vest-over-lining", "zipper-sewn-to-lining")
        )
        with self.assertRaisesRegex(ValueError, "present class has no component"):
            _bom(components=components, relations=relations)

    def test_observed_component_requires_evidence_regions(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires evidence regions"):
            Component(
                component_id="vest-shell",
                role=ComponentRole.SHELL,
                structural_role=StructuralRole.SUPPORT,
                layer_index=2,
                material=_material("red-crepe"),
                state=ObservationState.OBSERVED,
                confidence=1.0,
                cut_count=4,
            )

    def test_inferred_component_requires_rationale_and_uncertainty(self) -> None:
        with self.assertRaisesRegex(ValueError, "rationale is required"):
            Component(
                component_id="lining-bodice",
                role=ComponentRole.LINING,
                structural_role=StructuralRole.SUPPORT,
                layer_index=0,
                material=_material("ivory-cupro"),
                state=ObservationState.INFERRED,
                confidence=0.6,
                cut_count=2,
            )
        with self.assertRaisesRegex(ValueError, "cannot be certain"):
            Component(
                component_id="lining-bodice",
                role=ComponentRole.LINING,
                structural_role=StructuralRole.SUPPORT,
                layer_index=0,
                material=_material("ivory-cupro"),
                state=ObservationState.INFERRED,
                confidence=1.0,
                cut_count=2,
                rationale="implied",
            )

    def test_unknown_component_must_have_zero_confidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "zero confidence"):
            Component(
                component_id="chest-interfacing",
                role=ComponentRole.INTERFACING,
                structural_role=StructuralRole.SUPPORT,
                layer_index=3,
                material=_material("fusible-woven"),
                state=ObservationState.UNKNOWN,
                confidence=0.2,
                cut_count=1,
            )

    def test_cut_component_requires_cut_count_unless_unknown(self) -> None:
        with self.assertRaisesRegex(ValueError, "require cut_count"):
            Component(
                component_id="vest-shell",
                role=ComponentRole.SHELL,
                structural_role=StructuralRole.SUPPORT,
                layer_index=2,
                material=_material("red-crepe"),
                state=ObservationState.OBSERVED,
                confidence=1.0,
                evidence_regions=("front-view",),
            )

    def test_layered_over_must_follow_layer_order(self) -> None:
        relations = tuple(
            dataclasses.replace(
                item, source_id=item.target_id, target_id=item.source_id
            )
            if item.relation_id == "vest-over-lining"
            else item
            for item in _relations()
        )
        with self.assertRaisesRegex(ValueError, "higher layer_index"):
            _bom(relations=relations)

    def test_relation_must_reference_known_components(self) -> None:
        relations = _relations() + (
            AttachmentRelation(
                "ghost-sewn", AttachmentKind.SEWN_TO, "ghost", "vest-shell"
            ),
        )
        with self.assertRaisesRegex(ValueError, "unknown components"):
            _bom(relations=relations)

    def test_schema_rejects_unknown_fields_and_bad_enum_values(self) -> None:
        data = _bom().to_dict()
        data["components"][0]["color_hex"] = "#ffffff"
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            GarmentBOM.from_dict(data)

        data = _bom().to_dict()
        data["relations"][0]["kind"] = "glued-somehow"
        with self.assertRaises(ValueError):
            GarmentBOM.from_dict(data)


if __name__ == "__main__":
    unittest.main()
