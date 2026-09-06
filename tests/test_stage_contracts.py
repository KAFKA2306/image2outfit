from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.pattern_projection import project_pattern_piece
from image2outfit.stage_contracts import (
    normalize_observed_variants,
    resolve_private_reference,
    validate_pattern_contract,
    validate_stitch_contract,
)

PRODUCT_ID = "test-garment"


def pattern_fixture() -> dict:
    return {
        "schemaVersion": 1,
        "productId": PRODUCT_ID,
        "units": "meter",
        "pieces": [
            {
                "pieceId": "front",
                "boundary": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
                "seamAllowanceM": 0.01,
                "edges": [
                    {
                        "edgeId": "side",
                        "startVertex": 1,
                        "endVertex": 2,
                        "role": "seam",
                        "maxConnections": 1,
                    },
                    {
                        "edgeId": "hem",
                        "startVertex": 2,
                        "endVertex": 3,
                        "role": "hem",
                        "maxConnections": 0,
                    },
                ],
            },
            {
                "pieceId": "back",
                "boundary": [[1.0, 0.0], [2.0, 0.0], [2.0, 1.0], [1.0, 1.0]],
                "seamAllowanceM": 0.01,
                "edges": [
                    {
                        "edgeId": "side",
                        "startVertex": 3,
                        "endVertex": 0,
                        "role": "seam",
                        "maxConnections": 1,
                    }
                ],
            },
        ],
    }


def stitch_fixture() -> dict:
    return {
        "schemaVersion": 1,
        "productId": PRODUCT_ID,
        "stitches": [
            {
                "stitchId": "side-seam",
                "first": {"pieceId": "front", "edgeId": "side"},
                "second": {"pieceId": "back", "edgeId": "side"},
                "direction": "reversed",
                "easingRatio": 1.0,
            }
        ],
    }


class ObservedReferenceContractTests(unittest.TestCase):
    def test_normalization_uses_source_pixels_and_invertible_transform(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "reference.png"
            image = Image.new("RGB", (100, 80), (20, 30, 40))
            for x in range(10, 50):
                for y in range(10, 70):
                    image.putpixel((x, y), (180, 40, 70))
            image.save(source)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            audit = {
                "productId": PRODUCT_ID,
                "source": {
                    "originalSha256": digest,
                    "originalFileName": source.name,
                    "widthPx": 100,
                    "heightPx": 80,
                },
                "variants": [
                    {
                        "variantId": "red",
                        "label": "red",
                        "boundingBoxPx": [10, 10, 50, 70],
                        "dominantColors": [],
                    }
                ],
            }

            outputs, manifest = normalize_observed_variants(
                source,
                audit,
                root / "normalized",
            )

            self.assertEqual("original-image", manifest["observationSource"])
            self.assertLessEqual(manifest["roundTripMaxErrorPx"], 1.0)
            self.assertEqual("OBSERVED", manifest["variants"][0]["observationState"])
            self.assertEqual([], manifest["designHypotheses"])
            with Image.open(outputs[0]) as normalized:
                self.assertEqual((180, 40, 70), normalized.getpixel((384, 384)))

    def test_private_reference_rejects_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / "private"
            private.mkdir()
            source = private / "reference.png"
            source.write_bytes(b"wrong")
            audit = {
                "source": {
                    "originalSha256": "a" * 64,
                    "originalFileName": source.name,
                }
            }
            job = {"privateSourceRoots": ["private"]}

            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                resolve_private_reference(root, job, audit)


class PatternProjectionTests(unittest.TestCase):
    def test_width_perturbation_changes_generated_geometry_fingerprint(self) -> None:
        piece = pattern_fixture()["pieces"][0]
        baseline = project_pattern_piece(
            piece,
            x_scale=1.0,
            z_scale=1.0,
            z_offset=0.0,
        )
        widened = project_pattern_piece(
            piece,
            x_scale=1.0,
            z_scale=1.0,
            z_offset=0.0,
            width_scale=1.1,
        )

        self.assertNotEqual(baseline["fingerprint"], widened["fingerprint"])
        self.assertAlmostEqual(
            baseline["bounds"]["width"] * 1.1,
            widened["bounds"]["width"],
        )
        self.assertEqual(
            baseline["edgeVertexMap"],
            widened["edgeVertexMap"],
        )


class SemanticPatternBoundaryTests(unittest.TestCase):
    def test_valid_pattern_and_stitch_share_addressable_edges(self) -> None:
        pattern = pattern_fixture()
        stitch = stitch_fixture()

        pattern_summary = validate_pattern_contract(
            pattern,
            expected_product_id=PRODUCT_ID,
        )
        stitch_summary = validate_stitch_contract(
            stitch,
            pattern,
            expected_product_id=PRODUCT_ID,
        )

        self.assertEqual(2, pattern_summary["pieceCount"])
        self.assertEqual(1, stitch_summary["stitchCount"])
        self.assertEqual(1, stitch_summary["orientationChecks"])

    def test_unknown_edge_is_rejected_before_consumer_runs(self) -> None:
        stitch = stitch_fixture()
        stitch["stitches"][0]["second"]["edgeId"] = "missing"

        with self.assertRaisesRegex(ValueError, "unknown edge"):
            validate_stitch_contract(
                stitch,
                pattern_fixture(),
                expected_product_id=PRODUCT_ID,
            )

    def test_wrong_edge_direction_is_rejected(self) -> None:
        stitch = stitch_fixture()
        stitch["stitches"][0]["direction"] = "same"

        with self.assertRaisesRegex(ValueError, "direction mismatch"):
            validate_stitch_contract(
                stitch,
                pattern_fixture(),
                expected_product_id=PRODUCT_ID,
            )

    def test_missing_units_and_other_product_are_rejected(self) -> None:
        pattern = pattern_fixture()
        del pattern["units"]
        with self.assertRaisesRegex(ValueError, "units"):
            validate_pattern_contract(pattern, expected_product_id=PRODUCT_ID)

        pattern = pattern_fixture()
        pattern["productId"] = "other-product"
        with self.assertRaisesRegex(ValueError, "product identity"):
            validate_pattern_contract(pattern, expected_product_id=PRODUCT_ID)

    def test_tuxedo_contract_is_migrated_and_semantically_valid(self) -> None:
        product = ROOT / "config" / "products" / "siroino-tuxedo-halter-dress-large"
        job = json.loads((product / "job.json").read_text(encoding="utf-8"))
        pattern = json.loads((product / "pattern-draft.json").read_text(encoding="utf-8"))
        stitch = json.loads((product / "stitch-graph.json").read_text(encoding="utf-8"))

        self.assertEqual(2, job["garmentPipeline"]["stageContractVersion"])
        pattern_summary = validate_pattern_contract(
            pattern,
            expected_product_id=job["id"],
        )
        stitch_summary = validate_stitch_contract(
            stitch,
            pattern,
            expected_product_id=job["id"],
        )
        self.assertGreaterEqual(pattern_summary["edgeCount"], 20)
        self.assertEqual(len(stitch["stitches"]), stitch_summary["stitchCount"])


if __name__ == "__main__":
    unittest.main()
