from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CanonicalProductRootsTest(unittest.TestCase):
    def test_no_job_uses_removed_products_intermediate_root(self) -> None:
        violations = []
        for path in (ROOT / "config/products").glob("*/job.json"):
            job = json.loads(path.read_text(encoding="utf-8-sig"))
            if "/Products/" in str(job.get("productRoot", "")):
                violations.append(path.parent.name)
        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()
