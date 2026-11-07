from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/blender_weight_transfer.py"


class BlenderWeightTransferContractTests(unittest.TestCase):
    def test_bpy_is_not_imported_at_module_scope(self) -> None:
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        top_level_imports: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                top_level_imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_level_imports.add(node.module)
        self.assertNotIn("bpy", top_level_imports)

    def test_uses_blender_data_transfer_vertex_groups(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        for required in (
            '"DATA_TRANSFER"',
            '"VGROUP_WEIGHTS"',
            '"POLYINTERP_NEAREST"',
            '"skin-and-export"',
            '"--max-influences"',
            "constrain_vertex_weights",
        ):
            with self.subTest(required=required):
                self.assertIn(required, source)


if __name__ == "__main__":
    unittest.main()
