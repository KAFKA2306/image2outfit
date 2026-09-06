from __future__ import annotations

import copy
import unittest

from image2outfit.cloth_evidence import validate_reopened_cloth_evidence


def required_report() -> dict:
    return {
        "schemaVersion": 1,
        "productId": "garment",
        "applicability": "REQUIRED",
        "cacheSnapshotSha256": "a" * 64,
        "contracts": [
            {
                "object": "Skirt",
                "frameMeshSha256": {
                    "1": "b" * 64,
                    "12": "c" * 64,
                    "24": "d" * 64,
                },
            }
        ],
    }


def reopened_evidence() -> dict:
    return {
        "schemaVersion": 1,
        "productId": "garment",
        "applicability": "REQUIRED",
        "cacheSnapshotSha256": "a" * 64,
        "objects": [
            {
                "object": "Skirt",
                "cacheBakedActual": True,
                "finiteGeometry": True,
                "maximumExtentM": 0.7,
                "frameMeshSha256": {
                    "1": "b" * 64,
                    "12": "c" * 64,
                    "24": "d" * 64,
                },
            }
        ],
    }


class ClothEvidenceTests(unittest.TestCase):
    def test_reopened_required_cache_matches_all_frames(self) -> None:
        result = validate_reopened_cloth_evidence(
            required_report(),
            reopened_evidence(),
        )
        self.assertTrue(result["reopenValidated"])
        self.assertEqual(result["objectCount"], 1)

    def test_stale_snapshot_hash_is_rejected(self) -> None:
        evidence = reopened_evidence()
        evidence["cacheSnapshotSha256"] = "e" * 64
        with self.assertRaisesRegex(ValueError, "snapshot hash mismatch"):
            validate_reopened_cloth_evidence(required_report(), evidence)

    def test_missing_object_is_rejected(self) -> None:
        evidence = reopened_evidence()
        evidence["objects"] = []
        with self.assertRaisesRegex(ValueError, "objects are missing"):
            validate_reopened_cloth_evidence(required_report(), evidence)

    def test_stale_frame_hash_is_rejected(self) -> None:
        evidence = reopened_evidence()
        evidence["objects"][0]["frameMeshSha256"]["12"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "frame hash mismatch"):
            validate_reopened_cloth_evidence(required_report(), evidence)

    def test_not_required_construction_has_no_simulated_objects(self) -> None:
        report = {
            "schemaVersion": 1,
            "productId": "fitted-garment",
            "applicability": "NOT_REQUIRED",
            "contracts": [],
        }
        reopened = {
            "schemaVersion": 1,
            "productId": "fitted-garment",
            "applicability": "NOT_REQUIRED",
            "objects": [],
        }
        result = validate_reopened_cloth_evidence(report, reopened)
        self.assertEqual(result["objectCount"], 0)
        self.assertTrue(result["reopenValidated"])


if __name__ == "__main__":
    unittest.main()
