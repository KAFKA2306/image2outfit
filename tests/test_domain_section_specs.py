from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.avatar import derive_avatar_spec
from image2outfit.construction import (
    ConstructionComponent,
    ConstructionComponentKind,
    ConstructionSpec,
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
from image2outfit.fit import (
    ContactMetrics,
    DirectionalStrain,
    EaseTarget,
    FitCause,
    FitSpec,
    PoseFitReport,
)
from image2outfit.material import CalibrationStatus, load_material_library
from image2outfit.pipeline import PipelineStage
from image2outfit.styling import (
    ConstraintTargetKind,
    StylingOperation,
    StylingOperationKind,
    StylingSpec,
)

HASH_A = "a" * 64


class AvatarSpecTests(unittest.TestCase):
    def test_same_mesh_and_definitions_are_deterministic_across_three_poses(
        self,
    ) -> None:
        neutral = (
            (-10.0, 0.0, 100.0),
            (10.0, 0.0, 100.0),
            (-10.0, 0.0, 0.0),
            (10.0, 0.0, 0.0),
        )
        landmarks = {
            "left-shoulder-front": (
                BodyRegion.SHOULDER,
                Laterality.LEFT,
                SurfaceOrientation.FRONT,
                0,
            ),
            "right-shoulder-front": (
                BodyRegion.SHOULDER,
                Laterality.RIGHT,
                SurfaceOrientation.FRONT,
                1,
            ),
            "left-ankle-outer": (
                BodyRegion.ANKLE,
                Laterality.LEFT,
                SurfaceOrientation.OUTER,
                2,
            ),
            "right-ankle-outer": (
                BodyRegion.ANKLE,
                Laterality.RIGHT,
                SurfaceOrientation.OUTER,
                3,
            ),
        }
        poses = {
            "neutral": neutral,
            "crouch": tuple((x, y + 5.0, z - 10.0) for x, y, z in neutral),
            "sit": tuple((x, y + 20.0, z - 20.0) for x, y, z in neutral),
        }
        arguments = {
            "avatar_id": "siroino-test",
            "mesh_sha256": HASH_A,
            "neutral_vertices_mm": neutral,
            "landmark_definitions": landmarks,
            "measurement_paths": {"body-height": (2, 0)},
            "posed_vertices_mm": poses,
            "shape_keys": {"large": 0.0},
        }
        first = derive_avatar_spec(**arguments)
        second = derive_avatar_spec(**arguments)
        self.assertEqual(first.fingerprint(), second.fingerprint())
        self.assertEqual(3, len(first.poses))
        self.assertEqual(
            (0.0, 5.0, -10.0),
            first.landmark_displacements_mm("crouch")["left-shoulder-front"],
        )
        self.assertEqual("large", first.shape_keys[0].name)
        self.assertEqual(SurfaceOrientation.OUTER, first.landmarks[2].surface)


class ConstructionSpecTests(unittest.TestCase):
    @staticmethod
    def fixture(second_height: float = 1.0) -> ConstructionSpec:
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
            boundary=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
            grain_angle_degrees=90.0,
            edges=(left_edge,),
            correspondence_ids={"image": "region-left", "mesh": "group-left"},
        )
        right_piece = PatternPiece(
            piece_id="right-skirt",
            part_id="right-skirt-panel",
            boundary=(
                (1.0, 0.0),
                (2.0, 0.0),
                (2.0, second_height),
                (1.0, second_height),
            ),
            grain_angle_degrees=90.0,
            edges=(right_edge,),
            correspondence_ids={"image": "region-right", "mesh": "group-right"},
        )
        garment = GarmentSpecification(
            product_id="layered-skirt",
            target_avatar="SiroinoSotai_PC",
            source_reference="reference://skirt",
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
                component_id=identifier,
                kind=kind,
                layer=layer,
                piece_ids=("left-skirt", "right-skirt"),
                material_id=material,
            )
            for identifier, kind, layer, material in (
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

    def test_multilayer_skirt_is_representable_and_preview_is_deterministic(
        self,
    ) -> None:
        spec = self.fixture()
        self.assertTrue(spec.audit().passed)
        self.assertEqual(4, len(spec.components))
        self.assertEqual(spec.preview_svg(), spec.preview_svg())
        self.assertIn("region-left", spec.preview_json())

    def test_edge_length_and_orientation_are_audited(self) -> None:
        audit = self.fixture(second_height=1.5).audit()
        self.assertEqual(("side-seam",), audit.edge_length_mismatches)


class FitSpecTests(unittest.TestCase):
    def test_pose_reports_keep_failure_causes_separate(self) -> None:
        reports = []
        for pose in ("neutral", "crouch", "sit", "twist"):
            reports.append(
                PoseFitReport(
                    pose_id=pose,
                    body_region=BodyRegion.PELVIS,
                    strain=DirectionalStrain(0.05, 0.06, 0.07),
                    contact=ContactMetrics(
                        minimum_clearance_mm=2.0,
                        maximum_clearance_mm=20.0,
                        pressure_kpa=6.0 if pose == "sit" else 1.0,
                        contact_area_mm2=100.0,
                        penetration_depth_mm=1.0 if pose == "crouch" else 0.0,
                    ),
                    silhouette_error_mm=15.0 if pose == "twist" else 2.0,
                    cause=FitCause.PATTERN,
                    recommended_stage=PipelineStage.DRAFT_PATTERNS,
                )
            )
        spec = FitSpec(
            ease_targets=(EaseTarget(BodyRegion.PELVIS, 1.0, 10.0, 25.0),),
            reports=tuple(reports),
        )
        spec.require_poses(("neutral", "crouch", "sit", "twist"))
        self.assertEqual(
            {"penetration", "pressure", "silhouette"},
            {item.code for item in spec.defects()},
        )


class MaterialSpecTests(unittest.TestCase):
    def test_measured_library_has_six_anisotropic_fabrics(self) -> None:
        materials = load_material_library(
            ROOT / "config/materials/kes-woven-fabrics-2025.v1.json"
        )
        self.assertEqual(6, len(materials))
        self.assertTrue(
            all(
                item.calibration_status is CalibrationStatus.MEASURED_AND_CONVERTED
                for item in materials
            )
        )
        self.assertTrue(
            all(
                item.properties.stretch_warp_g_s2 != item.properties.stretch_weft_g_s2
                for item in materials
            )
        )
        self.assertTrue(all(item.mapping_for("clo3d") for item in materials))
        self.assertTrue(
            all(item.drape_absolute_error is not None for item in materials)
        )
        self.assertTrue(all(not item.properties.simulation_ready for item in materials))


class StylingSpecTests(unittest.TestCase):
    def test_order_conflict_and_reversal_are_explicit(self) -> None:
        anchor = StylingOperation(
            operation_id="waist-anchor",
            kind=StylingOperationKind.REGION_ANCHOR,
            target_kind=ConstraintTargetKind.GARMENT_REGION,
            target_ids=("front-hem",),
            anchor_target_ids=("waist-front",),
            order=0,
        )
        tuck = StylingOperation(
            operation_id="front-tuck",
            kind=StylingOperationKind.TUCK,
            target_kind=ConstraintTargetKind.GARMENT_REGION,
            target_ids=("front-hem",),
            anchor_target_ids=("waistband-inside",),
            depends_on=("waist-anchor",),
            order=1,
            parameters={"depthMm": 35.0, "widthMm": 120.0},
        )
        spec = StylingSpec((tuck, anchor))
        self.assertEqual(
            ("waist-anchor", "front-tuck"),
            tuple(item.operation_id for item in spec.application_order()),
        )
        self.assertEqual((), spec.conflicts())
        self.assertEqual(
            ("waist-anchor",),
            tuple(item.operation_id for item in spec.without("front-tuck").operations),
        )

    def test_dependency_cycle_is_rejected(self) -> None:
        first = StylingOperation(
            operation_id="first",
            kind=StylingOperationKind.FOLD,
            target_kind=ConstraintTargetKind.GARMENT_EDGE,
            target_ids=("edge-a",),
            depends_on=("second",),
        )
        second = StylingOperation(
            operation_id="second",
            kind=StylingOperationKind.FOLD,
            target_kind=ConstraintTargetKind.GARMENT_EDGE,
            target_ids=("edge-b",),
            depends_on=("first",),
        )
        with self.assertRaisesRegex(ValueError, "cycle"):
            StylingSpec((first, second))


if __name__ == "__main__":
    unittest.main()
