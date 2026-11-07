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
    GarmentPart,
    GarmentPartKind,
    GarmentSpecification,
    LayerPosition,
    MaterialBehavior,
    PatternPiece,
    Stitch,
    StitchEdge,
)


class GarmentDomainTests(unittest.TestCase):
    def test_pattern_first_specification_validates_references(self) -> None:
        part = GarmentPart(
            part_id="front-bodice",
            kind=GarmentPartKind.FRONT_BODICE_PANEL,
            body_regions=(BodyRegion.CHEST, BodyRegion.ABDOMEN),
            construction_role=ConstructionRole.STRUCTURAL_PANEL,
            layer=LayerPosition.BASE,
            material_behavior=MaterialBehavior.STRETCH,
            fit_profile=FitProfile.FITTED,
        )
        piece = PatternPiece(
            piece_id="front-bodice-piece",
            part_id=part.part_id,
            boundary=((0.0, 0.0), (1.0, 0.0), (0.5, 1.0)),
        )
        stitch = Stitch(
            stitch_id="front-dart",
            first=StitchEdge(piece.piece_id, 0, 1),
            second=StitchEdge(piece.piece_id, 1, 2),
        )
        specification = GarmentSpecification(
            product_id="test-garment",
            target_avatar="SiroinoSotai_PC",
            source_reference="private-reference://sha256/test",
            parts=(part,),
            pattern_pieces=(piece,),
            stitches=(stitch,),
        )
        self.assertEqual(specification.parts[0].body_regions[0], BodyRegion.CHEST)

    def test_stitch_cannot_reference_unknown_piece(self) -> None:
        part = GarmentPart(
            part_id="left-sleeve",
            kind=GarmentPartKind.SLEEVE,
            body_regions=(BodyRegion.UPPER_ARM, BodyRegion.FOREARM),
            construction_role=ConstructionRole.STRUCTURAL_PANEL,
            layer=LayerPosition.BASE,
            material_behavior=MaterialBehavior.KNIT,
            fit_profile=FitProfile.FITTED,
        )
        with self.assertRaisesRegex(ValueError, "unknown piece"):
            GarmentSpecification(
                product_id="test-garment",
                target_avatar="SiroinoSotai_PC",
                source_reference="private-reference://sha256/test",
                parts=(part,),
                stitches=(
                    Stitch(
                        stitch_id="sleeve-seam",
                        first=StitchEdge("missing-piece", 0, 1),
                        second=StitchEdge("missing-piece", 1, 2),
                    ),
                ),
            )
