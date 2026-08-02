from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class HygieneDocumentationTest(unittest.TestCase):
    def test_documentation_matches_enforced_boundaries(self) -> None:
        text = (ROOT / "docs" / "REPOSITORY_HYGIENE.md").read_text(encoding="utf-8")
        for required in (
            "config/products/<product-id>/",
            "Assets/GenWorks/",
            "contents: write",
            "task audit:repo",
            "tools/audit_repository_hygiene.py",
        ):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
