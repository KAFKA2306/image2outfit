from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.construction import ConstructionSpec
from image2outfit.domain import (
    BodyRegion,
    ConstructionRole,
    FitProfile,
    GarmentPart,
    GarmentPartKind,
    GarmentSpecification,
    LayerPosition,
    MaterialBehavior,
    PatternEdge,
    PatternEdgeRole,
    PatternPiece,
    Stitch,
    StitchEdge,
)
from image2outfit.garmentcode import (
    GARMENTCODE_RUNTIME,
    garmentcode_json,
    pattern_hypothesis_to_garmentcode,
)
from image2outfit.pattern_stage import DimensionSource, PatternHypothesis


def _part(part_id: str) -> GarmentPart:
    return GarmentPart(
        part_id=part_id,
        kind=GarmentPartKind.SKIRT_PANEL,
        body_regions=(BodyRegion.PELVIS,),
        construction_role=ConstructionRole.STRUCTURAL_PANEL,
        layer=LayerPosition.OUTER,
        material_behavior=MaterialBehavior.WOVEN,
        fit_profile=FitProfile.REGULAR,
    )


def pattern_fixture(*, diagonal_named_edge: bool = False) -> PatternHypothesis:
    left_edge = PatternEdge(
        edge_id="left-seam",
        piece_id="left-panel",
        start_vertex=0 if diagonal_named_edge else 1,
        end_vertex=2,
        role=PatternEdgeRole.SEAM,
    )
    right_edge = PatternEdge(
        edge_id="right-seam",
        piece_id="right-panel",
        start_vertex=3,
        end_vertex=0,
        role=PatternEdgeRole.SEAM,
    )
    left_piece = PatternPiece(
        piece_id="left-panel",
        part_id="left-part",
        boundary=((0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0)),
        edges=(left_edge,),
    )
    right_piece = PatternPiece(
        piece_id="right-panel",
        part_id="right-part",
        boundary=((0.5, 0.0), (1.0, 0.0), (1.0, 1.0), (0.5, 1.0)),
        edges=(right_edge,),
    )
    stitches = ()
    if not diagonal_named_edge:
        stitches = (
            Stitch(
                stitch_id="side-seam",
                first=StitchEdge("left-panel", 1, 2, edge_id="left-seam"),
                second=StitchEdge("right-panel", 3, 0, edge_id="right-seam"),
            ),
        )
    garment = GarmentSpecification(
        product_id="adapter-fixture",
        target_avatar="SiroinoSotai_PC",
        source_reference="reference://adapter-fixture",
        parts=(_part("left-part"), _part("right-part")),
        pattern_pieces=(left_piece, right_piece),
        stitches=stitches,
    )
    construction = ConstructionSpec(garment=garment, components=())
    return PatternHypothesis(
        hypothesis_id="adapter-pattern",
        decomposition_hypothesis_id="adapter-decomposition",
        construction=construction,
        dimensions=(
            DimensionSource(
                dimension_id="left-length",
                piece_id="left-panel",
                value_mm=1000.0,
                avatar_measurement_id="waist-to-hem",
                ease_target_id="regular-ease",
            ),
            DimensionSource(
                dimension_id="right-length",
                piece_id="right-panel",
                value_mm=1000.0,
                avatar_measurement_id="waist-to-hem",
                ease_target_id="regular-ease",
            ),
        ),
        reprojection=(),
        hidden_fields=(),
        confidence=0.8,
    )


class GarmentCodeAdapterTests(unittest.TestCase):
    def test_runtime_is_external_and_pinned(self) -> None:
        self.assertEqual(GARMENTCODE_RUNTIME.execution_mode, "external-isolated")
        self.assertEqual(GARMENTCODE_RUNTIME.upstream_python, "3.9")
        self.assertEqual(len(GARMENTCODE_RUNTIME.upstream_revision), 40)

    def test_converts_metres_to_basicpattern_centimetres(self) -> None:
        payload = pattern_hypothesis_to_garmentcode(pattern_fixture())
        left = payload["pattern"]["panels"]["left-panel"]

        self.assertEqual(left["vertices"][2], [50.0, 100.0])
        self.assertEqual(len(left["edges"]), 4)
        self.assertEqual(left["translation"], [0.0, 0.0, 0.0])
        self.assertEqual(left["rotation"], [0.0, 0.0, 0.0])
        self.assertEqual(payload["properties"]["units_in_meter"], 100)

    def test_maps_named_edges_and_stitches_to_edge_indices(self) -> None:
        payload = pattern_hypothesis_to_garmentcode(pattern_fixture())

        self.assertEqual(
            payload["parameters"]["image2outfit"]["named_edge_indices"],
            {"left-panel": {"left-seam": 1}, "right-panel": {"right-seam": 3}},
        )
        self.assertEqual(
            payload["pattern"]["stitches"],
            [[{"panel": "left-panel", "edge": 1}, {"panel": "right-panel", "edge": 3}]],
        )

    def test_serialization_is_deterministic(self) -> None:
        first = garmentcode_json(pattern_fixture())
        second = garmentcode_json(pattern_fixture())
        self.assertEqual(first, second)
        self.assertEqual(
            json.loads(first)["pattern"]["panel_order"], ["left-panel", "right-panel"]
        )

    def test_rejects_named_edge_that_is_not_boundary_loop(self) -> None:
        with self.assertRaisesRegex(ValueError, "not a boundary-loop edge"):
            pattern_hypothesis_to_garmentcode(pattern_fixture(diagonal_named_edge=True))


if __name__ == "__main__":
    unittest.main()
