from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = ROOT / "tools" / "siroino_heather_template_cage_v24.py"
PRODUCT_PATH = ROOT / "tools" / "siroino_heather_hooded_product.py"
RETIRED_BODY_ANCHOR_PATH = ROOT / "tools" / "siroino_heather_hooded_v21_patch.py"
RETIRED_LOBOMAP_PATH = ROOT / "tools" / "siroino_heather_lobomap_fit.py"


class GarmentGeometryStructuredTemplateCageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generator = GENERATOR_PATH.read_text(encoding="utf-8")
        cls.product = PRODUCT_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.generator, filename=str(GENERATOR_PATH))

    def test_active_product_installs_structured_template_cage(self) -> None:
        self.assertIn(
            "import siroino_heather_template_cage_v24 as template_cage",
            self.product,
        )
        self.assertLess(
            self.product.index("template_cage.install(pattern)"),
            self.product.index("DESIGN_REVISION = pattern.DESIGN_REVISION"),
        )
        self.assertNotIn("v21.install(pattern)", self.product)
        self.assertNotIn("lobomap.install(pattern)", self.product)

    def test_superseded_fit_modules_are_removed(self) -> None:
        self.assertFalse(RETIRED_BODY_ANCHOR_PATH.exists())
        self.assertFalse(RETIRED_LOBOMAP_PATH.exists())

    def test_generator_has_one_internal_pattern_parameter(self) -> None:
        imports = {
            alias.name
            for node in self.tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertFalse(
            any(name.startswith("siroino_") for name in imports),
            "The template-cage module must not add another internal import level",
        )
        self.assertIn("pattern: ModuleType", self.generator)

    def test_torso_has_analytic_high_cut_boundary(self) -> None:
        self.assertIn("TORSO_COLUMNS = 64", self.generator)
        self.assertIn("TORSO_ROWS = 20", self.generator)
        self.assertIn("def _bottom_z(theta: float)", self.generator)
        self.assertIn("0.565 + 0.275 * (side**1.65)", self.generator)
        self.assertIn("for row in range(TORSO_ROWS)", self.generator)

    def test_underbody_is_a_shared_edge_u_gusset(self) -> None:
        self.assertIn("Explicit shared-edge U-shaped gusset", self.generator)
        self.assertIn("pair_rows: list[tuple[int, int]]", self.generator)
        self.assertIn("pairwise(pair_rows)", self.generator)
        self.assertNotIn(
            "zip(pair_rows, pair_rows[1:], strict=True)",
            self.generator,
        )
        self.assertIn(
            "faces.append((current[0], current[1], following[1], following[0]))",
            self.generator,
        )

    def test_sleeves_are_regular_tubes_along_bone_centerlines(self) -> None:
        self.assertIn('f"UpperArm_{side}"', self.generator)
        self.assertIn('f"LowerArm_{side}"', self.generator)
        self.assertIn("def _tube_component(", self.generator)
        self.assertIn('f"Heather_Long_Sleeve_{side}"', self.generator)
        self.assertIn('f"Heather_Rib_Cuff_{side}"', self.generator)

    def test_hood_is_attached_cowl_not_detached_roll_primitive(self) -> None:
        self.assertIn("def _attached_hood_roll(", self.generator)
        self.assertIn('"Heather_Hood_Folded_Roll"', self.generator)
        self.assertIn(
            '"attached three-ring cowl; no detached tube primitive"',
            self.generator,
        )

    def test_body_is_reference_not_topology_source(self) -> None:
        self.assertIn('obj["bodyTopologyCopied"] = False', self.generator)
        self.assertIn(
            '"bodyRole": "surface and skin-weight reference only"',
            self.generator,
        )
        self.assertNotIn("BVHTree.FromPolygons", self.generator)
        self.assertNotIn("_selected_polygons", self.generator)


if __name__ == "__main__":
    unittest.main()
