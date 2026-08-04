from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATTERN_PATH = ROOT / "tools" / "siroino_heather_hooded_pattern_v14.py"
PRODUCT_PATH = ROOT / "tools" / "siroino_heather_hooded_product_v20.py"
JOB_PATH = (
    ROOT
    / "config"
    / "products"
    / "siroino-heather-hooded-bodysuit"
    / "job.json"
)


class GarmentGeometryV20Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = PATTERN_PATH.read_text(encoding="utf-8")
        cls.product_source = PRODUCT_PATH.read_text(encoding="utf-8")
        cls.job_source = JOB_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source, filename=str(PATTERN_PATH))

    def test_active_job_uses_v20_entrypoint(self) -> None:
        self.assertIn(
            '"buildRevision": "v20-semantic-five-opening-highcut-shell"',
            self.job_source,
        )
        self.assertIn(
            '"buildScript": "tools/siroino_heather_hooded_product_v20.py"',
            self.job_source,
        )
        self.assertIn(
            '"productBuildScript": "tools/siroino_heather_hooded_product_v20.py"',
            self.job_source,
        )

    def test_product_entrypoint_rebinds_active_pattern(self) -> None:
        self.assertIn("product.pattern = pattern", self.product_source)
        self.assertIn(
            "product.DESIGN_REVISION = pattern.DESIGN_REVISION",
            self.product_source,
        )
        self.assertIn('"v19-topology-healed-weighted-shell"', self.product_source)

    def test_openings_are_selected_by_anatomical_role(self) -> None:
        required = (
            "Semantic opening classification",
            'role="wrist"',
            'role="leg"',
            "center.z >= 0.95",
            "center.z <= 0.72",
            "selected_indices.update(restored_indices)",
        )
        for fragment in required:
            self.assertIn(fragment, self.source)
        self.assertNotIn("opening_components[:intended_openings]", self.source)

    def test_highcut_reaches_crotch_and_joins_torso(self) -> None:
        self.assertIn("0.600 <= center.z <= 0.850", self.source)
        self.assertIn("0.032 + 0.133 * _smoothstep(t)", self.source)
        self.assertIn("0.815 <= center.z", self.source)

    def test_exactly_five_openings_are_executable_gate(self) -> None:
        self.assertIn("boundary_loops != 5", self.source)
        self.assertIn("exactly five anatomical openings", self.source)

    def test_default_surface_offset_remains_within_policy(self) -> None:
        body_panel = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_body_panel"
        )
        defaults = {
            argument.arg: default.value
            for argument, default in zip(
                body_panel.args.kwonlyargs,
                body_panel.args.kw_defaults,
                strict=True,
            )
            if isinstance(default, ast.Constant)
        }
        self.assertEqual(float(defaults["offset"]), 0.012)
        self.assertEqual(float(defaults["bevel_width"]), 0.0)

    def test_hood_roll_is_moved_clear_of_the_body(self) -> None:
        self.assertIn("0.046 + 0.010 * center_weight", self.source)
        self.assertIn("0.0095", self.source)


if __name__ == "__main__":
    unittest.main()
