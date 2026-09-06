from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.garment_flow import (
    ring_dimensions_from_pattern,
    validate_pattern_contract,
    validate_reference_observations,
    validate_stitch_graph,
    variant_invalidation,
)

PRODUCT_ID = "siroino-tuxedo-halter-dress-large"
CONFIG = ROOT / "config" / "products" / PRODUCT_ID


def read(name: str) -> dict:
    payload = json.loads((CONFIG / name).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(name)
    return payload


class StandardGarmentFlowTests(unittest.TestCase):
    def test_observations_are_source_bound_and_round_trip(self) -> None:
        observations = read("reference-observations.json")
        result = validate_reference_observations(
            observations,
            product_id=PRODUCT_ID,
            source_sha256=observations["sourceSha256"],
            source_size=tuple(observations["sourceSizePx"]),
        )
        self.assertLessEqual(result["roundTripMaxErrorPx"], 1.0)
        self.assertTrue(
            all(record["evidenceClass"] == "OBSERVED" for record in result["records"])
        )
        self.assertEqual(
            observations["derivedDesignHypotheses"][0]["evidenceClass"],
            "INFERRED",
        )

    def test_observation_hash_and_unobserved_view_fail_closed(self) -> None:
        observations = read("reference-observations.json")
        with self.assertRaisesRegex(ValueError, "source hash mismatch"):
            validate_reference_observations(
                observations,
                product_id=PRODUCT_ID,
                source_sha256="0" * 64,
                source_size=tuple(observations["sourceSizePx"]),
            )
        bad = copy.deepcopy(observations)
        bad["observations"][0]["view"] = "back"
        with self.assertRaisesRegex(ValueError, "unobserved views"):
            validate_reference_observations(
                bad,
                product_id=PRODUCT_ID,
                source_sha256=bad["sourceSha256"],
                source_size=tuple(bad["sourceSizePx"]),
            )

    def test_pattern_edges_and_stitches_resolve_semantically(self) -> None:
        pattern = read("pattern-draft.json")
        stitches = read("stitch-graph.json")
        pieces = validate_pattern_contract(pattern, product_id=PRODUCT_ID)
        resolved = validate_stitch_graph(
            stitches, product_id=PRODUCT_ID, pieces=pieces
        )
        self.assertEqual(len(resolved), len(stitches["stitches"]))
        self.assertIn("hem", pieces["lower-skirt-ring"]["edges"])

        bad_pattern = copy.deepcopy(pattern)
        bad_pattern["units"] = ""
        with self.assertRaisesRegex(ValueError, "units"):
            validate_pattern_contract(bad_pattern, product_id=PRODUCT_ID)

        bad_stitches = copy.deepcopy(stitches)
        bad_stitches["stitches"][0]["first"]["edge"] = "does-not-exist"
        with self.assertRaisesRegex(ValueError, "missing edge"):
            validate_stitch_graph(
                bad_stitches, product_id=PRODUCT_ID, pieces=pieces
            )

        bad_orientation = copy.deepcopy(stitches)
        bad_orientation["stitches"][0]["orientation"] = "unknown"
        with self.assertRaisesRegex(ValueError, "orientation"):
            validate_stitch_graph(
                bad_orientation,
                product_id=PRODUCT_ID,
                pieces=pieces,
            )

    def test_size_change_propagates_to_pattern_driven_ring(self) -> None:
        pieces = validate_pattern_contract(
            read("pattern-draft.json"), product_id=PRODUCT_ID
        )
        piece = pieces["lower-skirt-ring"]
        mapping = piece["raw"]["construction3d"]
        base = ring_dimensions_from_pattern(
            piece,
            waist_edge=mapping["waistEdge"],
            hem_edge=mapping["hemEdge"],
            aspect_ratio_y=mapping["aspectRatioY"],
        )
        larger = ring_dimensions_from_pattern(
            piece,
            waist_edge=mapping["waistEdge"],
            hem_edge=mapping["hemEdge"],
            aspect_ratio_y=mapping["aspectRatioY"],
            width_scale=1.1,
        )
        self.assertAlmostEqual(
            larger["topCircumferenceM"] / base["topCircumferenceM"], 1.1
        )
        self.assertAlmostEqual(larger["topRxM"] / base["topRxM"], 1.1)
        self.assertAlmostEqual(larger["bottomRxM"] / base["bottomRxM"], 1.1)

    def test_variant_invalidation_separates_material_and_shape(self) -> None:
        variants = read("variants.json")["variants"]
        color = next(item for item in variants if item["kind"] == "color")
        size = next(item for item in variants if item["kind"] == "size")
        color_plan = variant_invalidation(color)
        size_plan = variant_invalidation(size)
        self.assertTrue(color_plan["reuseGeometry"])
        self.assertFalse(size_plan["reuseGeometry"])
        self.assertNotIn("simulate-cloth", color_plan["invalidateStages"])
        self.assertIn("simulate-cloth", size_plan["invalidateStages"])

    def test_material_recipe_and_job_are_canonical_inputs(self) -> None:
        job = read("job.json")
        recipe = read("material-recipe.json")
        pipeline = job["garmentPipeline"]
        self.assertEqual(
            pipeline["materialRecipePath"],
            f"config/products/{PRODUCT_ID}/material-recipe.json",
        )
        self.assertEqual(
            pipeline["referenceObservationsPath"],
            f"config/products/{PRODUCT_ID}/reference-observations.json",
        )
        self.assertEqual(
            pipeline["variantSpecPath"],
            f"config/products/{PRODUCT_ID}/variants.json",
        )
        self.assertEqual(recipe["regions"]["lower-skirt"], "sheer")
        self.assertEqual(recipe["controlExperiment"]["invariant"], "geometryDigest")


if __name__ == "__main__":
    unittest.main()
