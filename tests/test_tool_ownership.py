from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import audit_tool_ownership  # noqa: E402


class ToolOwnershipTest(unittest.TestCase):
    def test_every_tool_and_payload_has_one_active_reason_to_exist(self) -> None:
        result = audit_tool_ownership.audit(ROOT)
        failures = {
            "unreferenced": result["unreferenced"],
            "duplicateGroups": result["duplicateGroups"],
            "semanticDuplicateGroups": result["semanticDuplicateGroups"],
            "invalidOpaqueLoaders": result["invalidOpaqueLoaders"],
            "unreferencedResources": result["unreferencedResources"],
            "duplicateResourceGroups": result["duplicateResourceGroups"],
            "excessiveProductImportChains": result["excessiveProductImportChains"],
            "productImportCycles": result["productImportCycles"],
            "versionedNonProductScripts": result["versionedNonProductScripts"],
        }
        self.assertTrue(
            result["passed"],
            "\n".join(
                f"{name}: {value}" for name, value in failures.items() if value
            ),
        )

    def test_single_operator_entrypoint_is_tracked(self) -> None:
        result = audit_tool_ownership.audit(ROOT)
        manage = next(
            item for item in result["inventory"] if item["path"] == "tools/manage.py"
        )
        self.assertTrue(manage["categories"]["taskfile"])
        self.assertFalse(manage["unreferenced"])


if __name__ == "__main__":
    unittest.main()
