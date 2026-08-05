from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.arrangement import (
    InitialIntersection,
    IntersectionKind,
    PanelPlacement,
    WrapDirection,
    build_arrangement_plan,
)
from image2outfit.avatar import derive_avatar_spec
from image2outfit.construction import (
    ConstructionComponent,
    ConstructionComponentKind,
    ConstructionSpec,
)
from image2outfit.decomposition import (
    DecompositionHypothesis,
    GarmentDecomposition,
    ObservationState,
    PartObservation,
)
from image2outfit.domain import (
    BodyRegion,
    ConstructionRole,
    FitProfile,
    GarmentLocation,
    GarmentPart,
    GarmentPartKind,
    GarmentSpecification,
    Laterality,
    LayerPosition,
    MaterialBehavior,
    PatternEdge,
    PatternEdgeRole,
    PatternPiece,
    Stitch,
    StitchEdge,
    SurfaceOrientation,
)
from image2outfit.pattern_stage import (
    DimensionSource,
    PatternHypothesis,
    PatternHypothesisSet,
    PatternReprojectionEvidence,
)
from image2outfit.seam_stage import (
    EaseDistribution,
    SeamConnection,
    SeamHypothesis,
    SeamHypothesisSet,
    SeamType,
)
from image2outfit.styling import (
    ConstraintTargetKind,
    StylingOperation,
    StylingOperationKind,
    StylingSpec,
)

HASH_A = "a" * 64


def construction_fixture(
    *,
    right_height: float = 1.0,
    self_crossing: bool = False,
) -> ConstructionSpec:
    left_part = GarmentPart(
        part_id="left-skirt-panel",
        kind=GarmentPartKind.SKIRT_PANEL,
        body_regions=(BodyRegion.WAIST, BodyRegion.PELVIS),
        construction_role=ConstructionRole.STRUCTURAL_PANEL,
        layer=LayerPosition.OUTER,
        material_behavior=MaterialBehavior.WOVEN,
        fit_profile=FitProfile.REGULAR,
        locations=(
            GarmentLocation(
                BodyRegion.PELVIS,
                Laterality.LEFT,
                SurfaceOrientation.FRONT,
            ),
        ),
    )
    right_part = GarmentPart(
        part_id="right-skirt-panel",
        kind=GarmentPartKind.SKIRT_PANEL,
        body_regions=(BodyRegion.WAIST, BodyRegion.PELVIS),
        construction_role=ConstructionRole.STRUCTURAL_PANEL,
        layer=LayerPosition.OUTER,
        material_behavior=MaterialBehavior.WOVEN,
        fit_profile=FitProfile.REGULAR,
        locations=(
            GarmentLocation(
                BodyRegion.PELVIS,
                Laterality.RIGHT,
                SurfaceOrientation.FRONT,
            ),
        ),
    )
    left_boundary = (
        ((0.0, 0.0), (2.0, 0.0), (0.0, 2.0), (2.0, 2.0), (1.0, 3.0))
        if self_crossing
        else ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    )
    left_edge = PatternEdge(
        edge_id="left-side-seam",
        piece_id="left-skirt",
        start_vertex=1,
        end_vertex=2,
        role=PatternEdgeRole.SEAM,
        seam_allowance_m=0.01,
        notch_positions=(0.5,),
    )
    right_edge = PatternEdge(
        edge_id="right-side-seam",
        piece_id="right-skirt",
        start_vertex=3,
        end_vertex=0,
        role=PatternEdgeRole.SEAM,
        seam_allowance_m=0.01,
        notch_positions=(0.5,),
    )
    left_piece = PatternPiece(
        piece_id="left-skirt",
        part_id="left-skirt-panel",
        boundary=left_boundary,
        grain_angle_degrees=90.0,
        edges=(left_edge,),
        correspondence_ids={"image": "left-mask", "mesh": "left-panel-group"},
    )
    right_piece = PatternPiece(
        piece_id="right-skirt",
        part_id="right-skirt-panel",
        boundary=(
            (1.0, 0.0),
            (2.0, 0.0),
            (2.0, right_height),
            (1.0, right_height),
        ),
        grain_angle_degrees=90.0,
        edges=(right_edge,),
        correspondence_ids={"image": "right-mask", "mesh": "right-panel-group"},
    )
    garment = GarmentSpecification(
        product_id="test-garment",
        target_avatar="SiroinoSotai_PC",
        source_reference="reference://test-garment",
        parts=(left_part, right_part),
        pattern_pieces=(left_piece, right_piece),
        stitches=(
            Stitch(
                stitch_id="side-seam",
                first=StitchEdge("left-skirt", 1, 2, edge_id="left-side-seam"),
                second=StitchEdge("right-skirt", 3, 0, edge_id="right-side-seam"),
            ),
        ),
    )
    components = tuple(
        ConstructionComponent(
            component_id=component_id,
            kind=kind,
            layer=layer,
            piece_ids=("left-skirt", "right-skirt"),
            material_id=material_id,
        )
        for component_id, kind, layer, material_id in (
            (
                "plaid-shell",
                ConstructionComponentKind.SHELL,
                LayerPosition.OUTER,
                "plaid",
            ),
            (
                "white-ruffle",
                ConstructionComponentKind.LINING,
                LayerPosition.MID,
                "white",
            ),
            (
                "pink-hem",
                ConstructionComponentKind.FACING,
                LayerPosition.ATTACHED,
                "pink",
            ),
            (
                "waistband",
                ConstructionComponentKind.INTERFACING,
                LayerPosition.ATTACHED,
                "black",
            ),
        )
    )
    return ConstructionSpec(garment=garment, components=components)


def pattern_fixture(
    *,
    hypothesis_id: str = "front-back-pattern",
    decomposition_hypothesis_id: str = "visible-structure",
    right_height: float = 1.0,
    self_crossing: bool = False,
) -> PatternHypothesis:
    construction = construction_fixture(
        right_height=right_height,
        self_crossing=self_crossing,
    )
    dimensions = tuple(
        DimensionSource(
            dimension_id=f"{piece_id}-length",
            piece_id=piece_id,
            value_mm=1000.0,
            avatar_measurement_id="waist-to-hem",
            ease_target_id="pelvis-regular-ease",
        )
        for piece_id in ("left-skirt", "right-skirt")
    )
    evidence = tuple(
        PatternReprojectionEvidence(
            source_view_id="normalized-front",
            piece_id=piece_id,
            mean_error_px=2.0,
            maximum_error_px=5.0,
            evidence_path=f"evidence/{piece_id}-reprojection.png",
            evidence_sha256=HASH_A,
        )
        for piece_id in ("left-skirt", "right-skirt")
    )
    return PatternHypothesis(
        hypothesis_id=hypothesis_id,
        decomposition_hypothesis_id=decomposition_hypothesis_id,
        construction=construction,
        dimensions=dimensions,
        reprojection=evidence,
        hidden_fields=("back-waist-dart",),
        confidence=0.7,
    )


def decomposition_fixture() -> GarmentDecomposition:
    part = PartObservation(
        part_id="skirt-body",
        kind=GarmentPartKind.SKIRT_PANEL,
        locations=(
            GarmentLocation(
                BodyRegion.PELVIS,
                Laterality.BILATERAL,
                SurfaceOrientation.FULL,
            ),
        ),
        construction_role=ConstructionRole.STRUCTURAL_PANEL,
        layer=LayerPosition.OUTER,
        state=ObservationState.INFERRED,
        confidence=0.7,
        source_view_ids=("normalized-front",),
    )
    return GarmentDecomposition(
        decomposition_id="decomposition-set",
        normalized_set_id="normalized-reference-set",
        garment_id="test-garment",
        hypotheses=(
            DecompositionHypothesis(
                hypothesis_id="visible-structure",
                parts=(part,),
                relations=(),
                confidence=0.7,
            ),
            DecompositionHypothesis(
                hypothesis_id="hidden-back",
                parent_hypothesis_id="visible-structure",
                parts=(part,),
                relations=(),
                confidence=0.4,
            ),
        ),
    )


def seam_fixture(
    pattern: PatternHypothesis,
    *,
    hypothesis_id: str = "base-seams",
    gather_ratio: float = 1.0,
    hidden: bool = False,
) -> SeamHypothesis:
    return SeamHypothesis(
        hypothesis_id=hypothesis_id,
        pattern_hypothesis_id=pattern.hypothesis_id,
        connections=(
            SeamConnection(
                connection_id="side-seam",
                first_edge_id="left-side-seam",
                second_edge_id="right-side-seam",
                seam_type=SeamType.PLAIN,
                ease_ratio=1.0,
                ease_distribution=EaseDistribution.UNIFORM,
                gather_ratio=gather_ratio,
                first_start_matches_second_start=False,
                hidden=hidden,
            ),
        ),
        intentional_open_edge_ids=(),
        confidence=0.8,
    )


def avatar_fixture():
    neutral = (
        (-100.0, 0.0, 100.0),
        (100.0, 0.0, 100.0),
        (-100.0, 0.0, 0.0),
        (100.0, 0.0, 0.0),
    )
    return derive_avatar_spec(
        avatar_id="siroino-test",
        mesh_sha256=HASH_A,
        neutral_vertices_mm=neutral,
        landmark_definitions={
            "left-waist-front": (
                BodyRegion.WAIST,
                Laterality.LEFT,
                SurfaceOrientation.FRONT,
                0,
            ),
            "right-waist-front": (
                BodyRegion.WAIST,
                Laterality.RIGHT,
                SurfaceOrientation.FRONT,
                1,
            ),
            "left-hem-front": (
                BodyRegion.UPPER_LEG,
                Laterality.LEFT,
                SurfaceOrientation.FRONT,
                2,
            ),
            "right-hem-front": (
                BodyRegion.UPPER_LEG,
                Laterality.RIGHT,
                SurfaceOrientation.FRONT,
                3,
            ),
        },
        measurement_paths={"waist-to-hem": (0, 2)},
        posed_vertices_mm={"neutral": neutral},
    )


class PatternHypothesisTests(unittest.TestCase):
    def test_multiple_hypotheses_preserve_provenance_and_export_cad_previews(
        self,
    ) -> None:
        first = pattern_fixture()
        second = pattern_fixture(
            hypothesis_id="hidden-back-pattern",
            decomposition_hypothesis_id="hidden-back",
        )
        patterns = PatternHypothesisSet(
            pattern_set_id="pattern-set",
            decomposition_id="decomposition-set",
            garment_id="test-garment",
            hypotheses=(first, second),
        )
        patterns.validate_decomposition(decomposition_fixture())
        self.assertEqual((), first.geometry_defects())
        self.assertIn("<svg", first.preview_svg())
        self.assertIn("LWPOLYLINE", first.preview_dxf())
        self.assertIn("waist-to-hem", first.preview_json())
        self.assertEqual(
            "front-back-pattern", patterns.ranked_hypotheses()[0].hypothesis_id
        )

    def test_self_intersection_is_detected_before_blender(self) -> None:
        invalid = pattern_fixture(self_crossing=True)
        self.assertIn(
            "self-intersection",
            {item.code for item in invalid.geometry_defects()},
        )


class SeamHypothesisTests(unittest.TestCase):
    def test_edge_addressed_graph_supports_hidden_alternatives_and_four_layers(
        self,
    ) -> None:
        pattern = pattern_fixture()
        base = seam_fixture(pattern)
        hidden = seam_fixture(
            pattern,
            hypothesis_id="hidden-seams",
            hidden=True,
        )
        patterns = PatternHypothesisSet(
            pattern_set_id="pattern-set",
            decomposition_id="decomposition-set",
            garment_id="test-garment",
            hypotheses=(pattern,),
        )
        seams = SeamHypothesisSet(
            seam_set_id="seam-set",
            pattern_set_id="pattern-set",
            garment_id="test-garment",
            hypotheses=(base, hidden),
        )
        seams.validate_patterns(patterns)
        self.assertEqual((), base.audit(pattern))
        self.assertEqual(4, len(pattern.construction.components))
        self.assertIn("left-side-seam", base.preview_json())

    def test_gather_ratio_is_not_reduced_to_one_to_one_sewing(self) -> None:
        pattern = pattern_fixture(right_height=0.5)
        gathered = seam_fixture(pattern, gather_ratio=2.0)
        self.assertNotIn(
            "edge-length",
            {item.code for item in gathered.audit(pattern)},
        )


class ArrangementPlanTests(unittest.TestCase):
    @staticmethod
    def placements() -> tuple[PanelPlacement, ...]:
        return (
            PanelPlacement(
                piece_id="left-skirt",
                anchor_landmark_ids=("left-waist-front", "left-hem-front"),
                position_mm=(-50.0, 10.0, 50.0),
                rotation_degrees_xyz=(0.0, 0.0, 0.0),
                body_offset_mm=10.0,
                wrap_direction=WrapDirection.FRONT_TO_BACK,
                layer_order=0,
                outward_facing=True,
                bounds_minimum_mm=(-100.0, 5.0, 0.0),
                bounds_maximum_mm=(-1.0, 15.0, 100.0),
            ),
            PanelPlacement(
                piece_id="right-skirt",
                anchor_landmark_ids=("right-waist-front", "right-hem-front"),
                position_mm=(50.0, 10.0, 50.0),
                rotation_degrees_xyz=(0.0, 0.0, 0.0),
                body_offset_mm=10.0,
                wrap_direction=WrapDirection.FRONT_TO_BACK,
                layer_order=0,
                outward_facing=True,
                bounds_minimum_mm=(1.0, 5.0, 0.0),
                bounds_maximum_mm=(100.0, 15.0, 100.0),
            ),
        )

    def test_plan_is_deterministic_explicitly_layered_and_reversible(self) -> None:
        pattern = pattern_fixture()
        seam = seam_fixture(pattern)
        styling = StylingSpec(
            (
                StylingOperation(
                    operation_id="front-waist-anchor",
                    kind=StylingOperationKind.REGION_ANCHOR,
                    target_kind=ConstraintTargetKind.GARMENT_REGION,
                    target_ids=("left-skirt", "right-skirt"),
                    anchor_target_ids=(
                        "left-waist-front",
                        "right-waist-front",
                    ),
                    strength=0.8,
                    friction=0.3,
                    release_condition="after-settle",
                ),
            )
        )
        arguments = {
            "arrangement_id": "base-arrangement",
            "avatar": avatar_fixture(),
            "pattern": pattern,
            "seam": seam,
            "styling": styling,
            "placements": self.placements(),
        }
        first = build_arrangement_plan(**arguments)
        second = build_arrangement_plan(**arguments)
        first.validate_ready_for_solver()
        self.assertEqual(first.fingerprint(), second.fingerprint())
        self.assertEqual((0, 0), tuple(item.layer_order for item in first.placements))
        self.assertEqual(
            (), first.without_styling("front-waist-anchor").styling_constraints
        )

    def test_intersection_wrong_face_and_unknown_landmark_are_rejected(self) -> None:
        pattern = pattern_fixture()
        seam = seam_fixture(pattern)
        styling = StylingSpec(())
        with self.assertRaisesRegex(ValueError, "unknown avatar landmarks"):
            build_arrangement_plan(
                arrangement_id="unknown-anchor",
                avatar=avatar_fixture(),
                pattern=pattern,
                seam=seam,
                styling=styling,
                placements=(
                    replace(
                        self.placements()[0],
                        anchor_landmark_ids=("unknown-landmark",),
                    ),
                    self.placements()[1],
                ),
            )
        plan = build_arrangement_plan(
            arrangement_id="intersecting-arrangement",
            avatar=avatar_fixture(),
            pattern=pattern,
            seam=seam,
            styling=styling,
            placements=self.placements(),
            intersections=(
                InitialIntersection(
                    intersection_id="body-intersection",
                    kind=IntersectionKind.BODY,
                    first_id="left-skirt",
                    second_id="avatar-body",
                    penetration_mm=2.0,
                ),
            ),
        )
        with self.assertRaisesRegex(ValueError, "unresolved initial intersections"):
            plan.validate_ready_for_solver()
        wrong_face = replace(
            plan,
            intersections=(),
            placements=(
                replace(plan.placements[0], outward_facing=False),
                plan.placements[1],
            ),
        )
        with self.assertRaisesRegex(ValueError, "face orientation"):
            wrong_face.validate_ready_for_solver()


if __name__ == "__main__":
    unittest.main()
