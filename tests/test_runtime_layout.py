from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import audit_runtime_layout  # noqa: E402


class RuntimeLayoutContractTest(unittest.TestCase):
    def test_repository_uses_single_internal_runtime_layout(self) -> None:
        result = audit_runtime_layout.audit(ROOT)
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(
            result["runtimePattern"],
            ".image2outfit/products/<product-id>/{reports,candidate,release}",
        )


if __name__ == "__main__":
    unittest.main()
