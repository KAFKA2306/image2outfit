from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import audit_tool_ownership  # noqa: E402


class ToolOwnershipTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = audit_tool_ownership.audit(ROOT)

    def test_all_tools_and_payloads_are_owned(self) -> None:
        failures = {
            name: self.result[name]
            for name in (
                "unreferenced",
                "duplicateGroups",
                "semanticDuplicateGroups",
                "invalidOpaqueLoaders",
                "unreferencedResources",
                "duplicateResourceGroups",
                "excessiveProductImportChains",
                "productImportCycles",
            )
            if self.result[name]
        }
        self.assertTrue(self.result["passed"], failures)

    def test_manage_is_the_taskfile_entrypoint(self) -> None:
        manage = next(
            item
            for item in self.result["inventory"]
            if item["path"] == "tools/manage.py"
        )
        self.assertIn("Taskfile.yml", manage["references"])
        self.assertFalse(manage["unreferenced"])


if __name__ == "__main__":
    unittest.main()
