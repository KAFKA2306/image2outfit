from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

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
    PatternDart,
    PatternEdge,
    PatternEdgeRole,
    PatternPiece,
    Stitch,
    StitchEdge,
    SurfaceOrientation,
)


class PatternIntermediateRepresentationTests(unittest.TestCase):
    def test_location_edge_notch_dart_and_correspondence_are_explicit(self) -> None:
        part = GarmentPart(
            part_id="left-front-bodice",
            kind=GarmentPartKind.FRONT_BODICE_PANEL,
            body_regions=(BodyRegion.CHEST, BodyRegion.ABDOMEN),
            construction_role=ConstructionRole.STRUCTURAL_PANEL,
            layer=LayerPosition.BASE,
            material_behavior=MaterialBehavior.STRETCH,
            fit_profile=FitProfile.FITTED,
            locations=(
                GarmentLocation(
                    BodyRegion.CHEST,
                    Laterality.LEFT,
                    SurfaceOrientation.FRONT,
                ),
            ),
        )
        first_edge = PatternEdge(
            edge_id="left-princess-seam",
            piece_id="left-front-piece",
            start_vertex=0,
            end_vertex=1,
            role=PatternEdgeRole.SEAM,
            seam_allowance_m=0.01,
            notch_positions=(0.25, 0.75),
        )
        second_edge = PatternEdge(
            edge_id="left-side-seam",
            piece_id="left-front-piece",
            start_vertex=2,
            end_vertex=3,
            role=PatternEdgeRole.SEAM,
            seam_allowance_m=0.01,
            notch_positions=(0.25, 0.75),
        )
        piece = PatternPiece(
            piece_id="left-front-piece",
            part_id=part.part_id,
            boundary=((0.0, 0.0), (1.0, 0.0), (0.8, 1.0), (0.0, 1.0)),
            edges=(first_edge, second_edge),
            darts=(
                PatternDart(
                    dart_id="left-waist-dart",
                    piece_id="left-front-piece",
                    apex=(0.5, 0.7),
                    first_leg_vertex=0,
                    second_leg_vertex=1,
                    intake_m=0.02,
                ),
            ),
            correspondence_ids={"imageRegion": "mask-left-front"},
        )
        specification = GarmentSpecification(
            product_id="test-garment",
            target_avatar="SiroinoSotai_PC",
            source_reference="private-reference://sha256/test",
            parts=(part,),
            pattern_pieces=(piece,),
            stitches=(
                Stitch(
                    stitch_id="left-front-seam",
                    first=StitchEdge(
                        piece_id=piece.piece_id,
                        start_vertex=0,
                        end_vertex=1,
                        edge_id=first_edge.edge_id,
                    ),
                    second=StitchEdge(
                        piece_id=piece.piece_id,
                        start_vertex=2,
                        end_vertex=3,
                        edge_id=second_edge.edge_id,
                    ),
                ),
            ),
        )
        location = specification.parts[0].resolved_locations[0]
        self.assertEqual(location.laterality, Laterality.LEFT)
        self.assertEqual(location.surface, SurfaceOrientation.FRONT)
        self.assertEqual(piece.edges[0].role, PatternEdgeRole.SEAM)
        self.assertEqual(piece.correspondence_ids["imageRegion"], "mask-left-front")

    def test_zero_area_pattern_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "zero signed area"):
            PatternPiece(
                piece_id="invalid-piece",
                part_id="invalid-part",
                boundary=((0.0, 0.0), (1.0, 0.0), (2.0, 0.0)),
            )

    def test_explicit_pattern_edges_must_be_used_by_stitches(self) -> None:
        part = GarmentPart(
            part_id="front-bodice",
            kind=GarmentPartKind.FRONT_BODICE_PANEL,
            body_regions=(BodyRegion.CHEST,),
            construction_role=ConstructionRole.STRUCTURAL_PANEL,
            layer=LayerPosition.BASE,
            material_behavior=MaterialBehavior.WOVEN,
            fit_profile=FitProfile.FITTED,
        )
        piece = PatternPiece(
            piece_id="front-piece",
            part_id=part.part_id,
            boundary=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
            edges=(
                PatternEdge(
                    edge_id="front-side-seam",
                    piece_id="front-piece",
                    start_vertex=0,
                    end_vertex=1,
                    role=PatternEdgeRole.SEAM,
                ),
            ),
        )
        with self.assertRaisesRegex(ValueError, "must reference an explicit edge"):
            GarmentSpecification(
                product_id="test-garment",
                target_avatar="SiroinoSotai_PC",
                source_reference="private-reference://sha256/test",
                parts=(part,),
                pattern_pieces=(piece,),
                stitches=(
                    Stitch(
                        stitch_id="invalid-seam",
                        first=StitchEdge("front-piece", 0, 1),
                        second=StitchEdge("front-piece", 1, 2),
                    ),
                ),
            )
