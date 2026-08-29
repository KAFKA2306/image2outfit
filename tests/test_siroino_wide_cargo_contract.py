from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "tools" / "siroino_wide_cargo_product.py"


class SiroinoWideCargoContractTests(unittest.TestCase):
    def test_builder_does_not_restore_legacy_human_review_gates(self) -> None:
        source = BUILDER.read_text(encoding="utf-8")
        self.assertNotIn("humanVisualReview", source)
        self.assertNotIn("humanPoseReview", source)


if __name__ == "__main__":
    unittest.main()
