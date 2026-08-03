from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"


class NoDuplicateReleaseValidatorTest(unittest.TestCase):
    def test_only_customer_quality_defines_human_release_validation(self) -> None:
        definitions = []
        for path in TOOLS.glob("*.py"):
            source = path.read_text(encoding="utf-8-sig")
            if "def evidence_gate(" in source:
                definitions.append(path.name)
        self.assertEqual([], definitions)
        policy = (ROOT / "config/release-policy.json").read_text(encoding="utf-8")
        self.assertIn('"singleReleaseValidator": "tools/customer_quality.py"', policy)


if __name__ == "__main__":
    unittest.main()
