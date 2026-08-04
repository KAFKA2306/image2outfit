from __future__ import annotations

import ast
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "pyproject.toml"
PATTERN_PATH = ROOT / "tools" / "siroino_heather_hooded_pattern_v13.py"


class GarmentGeometryPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = tomllib.loads(POLICY_PATH.read_text(encoding="utf-8"))["tool"][
            "image2outfit"
        ]["garment-geometry"]
        cls.source = PATTERN_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source, filename=str(PATTERN_PATH))
        cls.body_panel = next(
            node
            for node in cls.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_body_panel"
        )
        cls.body_panel_source = ast.get_source_segment(cls.source, cls.body_panel) or ""
        cls.selection_helper = next(
            node
            for node in cls.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_selected_polygons"
        )
        cls.selection_source = (
            ast.get_source_segment(cls.source, cls.selection_helper) or ""
        )

    def test_bodycon_policy_requires_one_continuous_source_shell(self) -> None:
        self.assertTrue(self.policy["require-source-topology-for-bodycon"])
        self.assertTrue(self.policy["require-continuous-torso-sleeve-shell"])
        self.assertTrue(self.policy["forbid-detached-planar-bodycon-panels"])

    def test_safe_shell_offset_respects_policy(self) -> None:
        limit = float(self.policy["max-default-bodycon-surface-offset-m"])
        defaults = {
            argument.arg: default.value
            for argument, default in zip(
                self.body_panel.args.kwonlyargs,
                self.body_panel.args.kw_defaults,
                strict=True,
            )
            if isinstance(default, ast.Constant)
        }
        self.assertLessEqual(float(defaults["offset"]), limit)
        self.assertEqual(float(defaults["bevel_width"]), 0.0)

    def test_pattern_builds_one_refined_primary_body_shell(self) -> None:
        create_outfit = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "create_outfit"
        )
        create_source = ast.get_source_segment(self.source, create_outfit) or ""
        shell_calls = [
            node
            for node in ast.walk(create_outfit)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_body_panel"
        ]
        self.assertEqual(len(shell_calls), 1)
        self.assertIn("Heather_Body_Shell", create_source)
        self.assertIn("_refined_body_source", create_source)
        self.assertIn("_body_shell_predicate", create_source)
        self.assertNotIn("Heather_Rib_Cuff", create_source)
        self.assertNotIn("Heather_Highcut_Front_Panel", create_source)
        self.assertNotIn("Heather_Highcut_Back_Panel", create_source)
        self.assertNotIn("Heather_Crotch_Bridge", create_source)

    def test_safe_shell_has_topology_and_boundary_gates(self) -> None:
        required_fragments = (
            "The fitted source shell must not use a bevel modifier",
            "max_edge > 0.20",
            "disconnected source shell",
            "expected at most 5 garment openings",
            "Garment geometry sanity gate failed",
        )
        for fragment in required_fragments:
            self.assertIn(fragment, self.source)
        self.assertNotIn(
            'modifiers.new("Finished edge", "BEVEL")',
            self.body_panel_source,
        )
        self.assertNotIn(
            'modifiers.new("Fabric thickness", "SOLIDIFY")',
            self.body_panel_source,
        )

    def test_primary_shell_copies_refined_topology_uvs_and_weights(self) -> None:
        self.assertIn("body.data.polygons", self.selection_source)
        required_body_panel_fragments = (
            "body.data.vertices[source_index].groups",
            "body.data.uv_layers.active",
            "modifier.use_deform_preserve_volume = preserve_volume",
        )
        for fragment in required_body_panel_fragments:
            self.assertIn(fragment, self.body_panel_source)
        self.assertIn('subdivision.levels = 1', self.source)
        self.assertIn('source.shape_key_clear()', self.source)

    def test_rejected_inflated_hood_is_replaced_by_folded_cowl(self) -> None:
        self.assertIn("Heather_Hood_Down_Cowl", self.source)
        self.assertNotIn("Heather_Hood_Shell", self.source)
        self.assertNotIn("Heather_Hood_Neck_Band", self.source)


if __name__ == "__main__":
    unittest.main()
