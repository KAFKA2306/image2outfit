from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import audit_repository_hygiene  # noqa: E402


class RepositoryHygieneTest(unittest.TestCase):
    def test_repository_has_no_committed_operational_residue(self) -> None:
        result = audit_repository_hygiene.audit(ROOT)
        self.assertTrue(
            result["passed"],
            "\n".join(
                f"{item['code']}: {item['path']} — {item['message']}"
                for item in result["findings"]
            ),
        )


if __name__ == "__main__":
    unittest.main()
