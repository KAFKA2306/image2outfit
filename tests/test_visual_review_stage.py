from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location(
    "run_visual_review_stage", TOOLS / "run_visual_review_stage.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
validate_review = MODULE.validate_review


class VisualReviewStageTests(unittest.TestCase):
    def base_review(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "productId": "garment",
            "status": "PASS",
            "reviewMethod": "direct-image-inspection",
            "reviewedRevision": "v1",
            "decision": "ACCEPT",
        }

    def test_pass_review_is_valid(self) -> None:
        self.assertEqual(
            validate_review(self.base_review(), product_id="garment", revision="v1"),
            "PASS",
        )

    def test_fail_review_is_valid_completed_review(self) -> None:
        review = self.base_review()
        review["status"] = "FAIL"
        review["decision"] = "REJECT"
        self.assertEqual(
            validate_review(review, product_id="garment", revision="v1"),
            "FAIL",
        )

    def test_failed_review_cannot_accept(self) -> None:
        review = self.base_review()
        review["status"] = "FAIL"
        with self.assertRaisesRegex(ValueError, "cannot record decision ACCEPT"):
            validate_review(review, product_id="garment", revision="v1")

    def test_unknown_status_is_rejected(self) -> None:
        review = self.base_review()
        review["status"] = "UNKNOWN"
        with self.assertRaisesRegex(ValueError, "status must be PASS or FAIL"):
            validate_review(review, product_id="garment", revision="v1")


if __name__ == "__main__":
    unittest.main()
