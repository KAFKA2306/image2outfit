from __future__ import annotations

import ast
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "pyproject.toml"
PATTERN_PATH = ROOT / "tools" / "siroino_heather_hooded_pattern_v10.py"


class GarmentGeometryPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = tomllib.loads(POLICY_PATH.read_text(encoding="utf-8"))[
            "tool"
        ]["image2outfit"]["garment-geometry"]
        cls.source = PATTERN_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source, filename=str(PATTERN_PATH))

    def test_bodycon_policy_requires_source_topology(self) -> None:
        self.assertTrue(self.policy["require-source-topology-for-bodycon"])
        self.assertTrue(self.policy["forbid-sampled-grid-as-bodycon-shell"])

    def test_default_body_surface_offset_respects_policy(self) -> None:
        limit = float(self.policy["max-default-bodycon-surface-offset-m"])
        offsets: list[float] = []
        for node in ast.walk(self.tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name != "_body_panel":
                continue
            for argument, default in zip(
                node.args.kwonlyargs,
                node.args.kw_defaults,
                strict=True,
            ):
                if argument.arg == "offset" and isinstance(default, ast.Constant):
                    offsets.append(float(default.value))
        self.assertEqual(len(offsets), 1, "_body_panel must define one offset default")
        self.assertLessEqual(offsets[0], limit)

    def test_bodycon_shell_does_not_use_sampled_panel_grid(self) -> None:
        create_outfit = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "create_outfit"
        )
        calls = {
            node.func.attr
            for node in ast.walk(create_outfit)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertNotIn("_sampled_panel", calls)
        self.assertNotIn("_torso_panels", calls)
        self.assertNotIn("_highcut_panels", calls)

    def test_bodycon_shell_copies_target_topology_and_weights(self) -> None:
        required_fragments = (
            "body.data.polygons",
            "body.data.vertices[source_index].groups",
            "body.data.uv_layers.active",
            "modifier.use_deform_preserve_volume = True",
        )
        for fragment in required_fragments:
            self.assertIn(fragment, self.source)


if __name__ == "__main__":
    unittest.main()
