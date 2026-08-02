from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import audit_tool_ownership  # noqa: E402


class ToolOwnershipTest(unittest.TestCase):
    def test_all_tools_and_payloads_are_owned(self) -> None:
        result = audit_tool_ownership.audit(ROOT)
        failures = {
            name: result[name]
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
            if result[name]
        }
        self.assertTrue(result["passed"], failures)

    def test_manage_is_the_taskfile_entrypoint(self) -> None:
        result = audit_tool_ownership.audit(ROOT)
        manage = next(
            item for item in result["inventory"] if item["path"] == "tools/manage.py"
        )
        self.assertIn("Taskfile.yml", manage["references"])
        self.assertFalse(manage["unreferenced"])


if __name__ == "__main__":
    unittest.main()
