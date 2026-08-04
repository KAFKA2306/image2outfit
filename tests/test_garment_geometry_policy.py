from __future__ import annotations

import ast
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "pyproject.toml"
PATTERN_PATH = ROOT / "tools" / "siroino_heather_hooded_pattern_v13.py"
BUILD_PATH = ROOT / "tools" / "siroino_heather_hooded_bodysuit_build.py"


class GarmentGeometryPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = tomllib.loads(POLICY_PATH.read_text(encoding="utf-8"))["tool"][
            "image2outfit"
        ]["garment-geometry"]
        cls.source = PATTERN_PATH.read_text(encoding="utf-8")
        cls.build_source = BUILD_PATH.read_text(encoding="utf-8")
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

    def test_pattern_builds_one_primary_body_shell(self) -> None:
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
        self.assertIn("_body_shell_predicate(refined)", create_source)
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
        self.assertNotIn("shoulder_bridge", self.source)
        self.assertNotIn(
            'modifiers.new("Finished edge", "BEVEL")',
            self.body_panel_source,
        )
        self.assertNotIn(
            'modifiers.new("Fabric thickness", "SOLIDIFY")',
            self.body_panel_source,
        )

    def test_primary_shell_bakes_and_refines_the_evaluated_target(self) -> None:
        self.assertIn("body.data.polygons", self.selection_source)
        required_fragments = (
            "bpy.context.evaluated_depsgraph_get()",
            "body.evaluated_get(depsgraph)",
            "bpy.data.meshes.new_from_object",
            "preserve_all_data_layers=True",
            "len(mesh.vertices) != len(body.data.vertices)",
            "mesh.shape_keys is not None",
            "subdivision.levels = 2",
            "body.data.vertices[source_index].groups",
            "body.data.uv_layers.active",
            "modifier.use_deform_preserve_volume = preserve_volume",
        )
        for fragment in required_fragments:
            self.assertIn(fragment, self.source)
        self.assertNotIn("source.shape_key_clear()", self.source)
        self.assertIn("_purge_orphan_shape_keys()", self.source)

    def test_openings_are_smoothed_and_reprojected(self) -> None:
        required_fragments = (
            "def _boundary_vertex_weights",
            "Temporary_Boundary_Smoothing",
            "Opening boundary smoothing",
            "smooth.iterations = 7",
            "Evaluated target reprojection",
            'shrinkwrap.wrap_method = "NEAREST_SURFACEPOINT"',
            "shrinkwrap.offset = offset",
        )
        for fragment in required_fragments:
            self.assertIn(fragment, self.source)

    def test_sleeves_use_interpolated_arm_weights(self) -> None:
        required_fragments = (
            "_polygon_average_weight(body, polygon, (upper,))",
            "_polygon_average_weight(body, polygon, (lower,))",
            "_polygon_average_weight(body, polygon, (hand,))",
            "arm_weight >= 0.008",
            "upper_weight >= 0.002",
        )
        for fragment in required_fragments:
            self.assertIn(fragment, self.source)

    def test_highcut_uses_a_short_broad_smooth_transition(self) -> None:
        self.assertIn("def _smoothstep", self.source)
        self.assertIn("0.695 <= center.z <= 0.885", self.source)
        self.assertIn("0.090 + 0.085 * _smoothstep(t)", self.source)

    def test_rejected_drape_is_replaced_by_a_surface_sampled_roll(self) -> None:
        self.assertIn("Heather_Hood_Folded_Roll", self.source)
        self.assertIn("sampler.point(x, z, front=False", self.source)
        self.assertNotIn("Heather_Hood_Folded_Back_Drape", self.source)
        self.assertNotIn("Heather_Hood_Down_Cowl", self.source)
        self.assertNotIn("Heather_Hood_Shell", self.source)

    def test_build_gate_uses_required_objects_not_legacy_object_count(self) -> None:
        self.assertIn('"Heather_Hood_Folded_Roll"', self.build_source)
        self.assertIn("required_objects - garment_names", self.build_source)
        self.assertIn("not missing_objects", self.build_source)
        self.assertNotIn('measured["meshObjects"] >= 14', self.build_source)


if __name__ == "__main__":
    unittest.main()
