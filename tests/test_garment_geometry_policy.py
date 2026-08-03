from __future__ import annotations

import ast
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "pyproject.toml"
BASE_PATTERN_PATH = ROOT / "tools" / "siroino_heather_hooded_pattern_v10.py"
SAFE_PATTERN_PATH = ROOT / "tools" / "siroino_heather_hooded_pattern_v13.py"


class GarmentGeometryPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = tomllib.loads(POLICY_PATH.read_text(encoding="utf-8"))["tool"][
            "image2outfit"
        ]["garment-geometry"]
        cls.base_source = BASE_PATTERN_PATH.read_text(encoding="utf-8")
        cls.safe_source = SAFE_PATTERN_PATH.read_text(encoding="utf-8")
        cls.safe_tree = ast.parse(cls.safe_source, filename=str(SAFE_PATTERN_PATH))

    def test_bodycon_policy_requires_one_continuous_source_shell(self) -> None:
        self.assertTrue(self.policy["require-source-topology-for-bodycon"])
        self.assertTrue(self.policy["require-continuous-torso-sleeve-shell"])
        self.assertTrue(self.policy["forbid-detached-planar-bodycon-panels"])

    def test_safe_shell_offset_respects_policy(self) -> None:
        limit = float(self.policy["max-default-bodycon-surface-offset-m"])
        body_panel = next(
            node
            for node in self.safe_tree.body
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
        self.assertLessEqual(float(defaults["offset"]), limit)
        self.assertEqual(float(defaults["bevel_width"]), 0.0)

    def test_base_construction_builds_one_primary_body_shell(self) -> None:
        base_tree = ast.parse(self.base_source, filename=str(BASE_PATTERN_PATH))
        create_outfit = next(
            node
            for node in base_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "create_outfit"
        )
        shell_calls = [
            node
            for node in ast.walk(create_outfit)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_body_panel"
        ]
        self.assertEqual(len(shell_calls), 1)
        self.assertIn("Heather_Body_Shell", self.base_source)
        self.assertIn("_body_shell_predicate", self.base_source)

    def test_safe_patch_replaces_bevel_and_adds_edge_guard(self) -> None:
        required_fragments = (
            "v12._body_panel = _body_panel",
            "The fitted source shell must not use a bevel modifier",
            "solidify.offset = 0.0",
            "max_edge > 0.20",
            "Garment geometry sanity gate failed",
        )
        for fragment in required_fragments:
            self.assertIn(fragment, self.safe_source)
        self.assertNotIn('modifiers.new("Finished edge", "BEVEL")', self.safe_source)

    def test_primary_shell_copies_target_topology_and_weights(self) -> None:
        required_fragments = (
            "body.data.polygons",
            "body.data.vertices[source_index].groups",
            "body.data.uv_layers.active",
            "modifier.use_deform_preserve_volume = True",
        )
        for fragment in required_fragments:
            self.assertIn(fragment, self.safe_source)


if __name__ == "__main__":
    unittest.main()
