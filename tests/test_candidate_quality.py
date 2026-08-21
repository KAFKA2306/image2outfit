from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from candidate_quality import (
    QUALITY_PASS,
    QUALITY_PENDING,
    QUALITY_REJECT,
    candidate_status,
    geometry_quality,
    validate_visual_review,
    verify_inspected_images,
)


class CandidateQualityTests(unittest.TestCase):
    def test_geometry_reject_is_a_quality_decision_not_an_exception(self) -> None:
        decision = geometry_quality(
            {
                "passed": False,
                "metrics": {
                    "unweightedVertices": 0,
                    "degenerateTriangles": 116,
                },
                "geometryGate": {
                    "passed": False,
                    "checks": {
                        "unweightedVertices==0": True,
                        "degenerateTriangles==0": False,
                    },
                },
            }
        )
        self.assertEqual(decision["decision"], QUALITY_REJECT)
        self.assertFalse(decision["passed"])
        self.assertIn("degenerateTriangles==0", decision["failedChecks"])

    def test_geometry_pass_requires_all_declared_checks(self) -> None:
        decision = geometry_quality(
            {
                "passed": True,
                "metrics": {
                    "unweightedVertices": 0,
                    "degenerateTriangles": 0,
                },
                "geometryGate": {
                    "passed": True,
                    "checks": {
                        "unweightedVertices==0": True,
                        "degenerateTriangles==0": True,
                    },
                },
            }
        )
        self.assertEqual(decision["decision"], QUALITY_PASS)
        self.assertTrue(decision["passed"])
        self.assertEqual(decision["failedChecks"], [])

    def test_direct_review_accepts_explicit_rejection(self) -> None:
        review = validate_visual_review(
            {
                "schemaVersion": 1,
                "productId": "ghost-gown",
                "status": "REJECTED",
                "decision": "REJECT",
                "reviewMethod": "direct-image-inspection",
                "reviewedRevision": "v1",
                "inspectedImages": {"front.png": "a" * 64},
                "findings": [{"code": "silhouette"}],
            },
            product_id="ghost-gown",
            revision_id="v1",
        )
        self.assertEqual(review["decision"], QUALITY_REJECT)

    def test_direct_review_rejects_inconsistent_status_and_decision(self) -> None:
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            validate_visual_review(
                {
                    "schemaVersion": 1,
                    "productId": "ghost-gown",
                    "status": "REJECTED",
                    "decision": "PASS",
                    "reviewMethod": "direct-image-inspection",
                    "reviewedRevision": "v1",
                    "inspectedImages": {"front.png": "a" * 64},
                    "findings": [{"code": "silhouette"}],
                },
                product_id="ghost-gown",
                revision_id="v1",
            )

    def test_review_is_bound_to_exact_render_hashes(self) -> None:
        inspected = {"front.png": "a" * 64, "back.png": "b" * 64}
        verify_inspected_images(inspected, dict(inspected))
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            verify_inspected_images(
                inspected,
                {"front.png": "c" * 64, "back.png": "b" * 64},
            )

    def test_candidate_status_distinguishes_rejected_from_working(self) -> None:
        passing = {"geometry": True, "visual": True, "artifact": True}
        self.assertEqual(
            candidate_status(
                passing,
                geometry_decision=QUALITY_PASS,
                visual_decision=QUALITY_PASS,
            ),
            "COMPLETE",
        )
        self.assertEqual(
            candidate_status(
                {**passing, "geometry": False},
                geometry_decision=QUALITY_REJECT,
                visual_decision=QUALITY_PASS,
            ),
            "REJECTED",
        )
        self.assertEqual(
            candidate_status(
                {**passing, "visual": False},
                geometry_decision=QUALITY_PASS,
                visual_decision=QUALITY_PENDING,
            ),
            "WORKING",
        )


if __name__ == "__main__":
    unittest.main()
