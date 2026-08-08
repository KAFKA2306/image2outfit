from __future__ import annotations

import ast
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "pyproject.toml"
GENERATOR_PATH = ROOT / "tools" / "siroino_heather_manifold_yoke_v29.py"
BASE_PATH = ROOT / "tools" / "siroino_heather_closed_components_v27.py"
BUILD_PATH = ROOT / "tools" / "siroino_heather_hooded_bodysuit_build.py"


class GarmentGeometryPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = tomllib.loads(POLICY_PATH.read_text(encoding="utf-8"))["tool"][
            "image2outfit"
        ]["garment-geometry"]
        cls.source = GENERATOR_PATH.read_text(encoding="utf-8")
        cls.base_source = BASE_PATH.read_text(encoding="utf-8")
        cls.build_source = BUILD_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source, filename=str(GENERATOR_PATH))

    def test_bodycon_policy_still_requires_continuity(self) -> None:
        self.assertTrue(self.policy["require-source-topology-for-bodycon"])
        self.assertTrue(self.policy["require-continuous-torso-sleeve-shell"])
        self.assertTrue(self.policy["forbid-detached-planar-bodycon-panels"])

    def test_avatar_is_reference_not_garment_topology(self) -> None:
        self.assertIn('"bodyTopologyCopied": False', self.base_source)
        self.assertIn("BVHTree.FromPolygons", self.base_source)
        self.assertIn("mesh.from_pydata(vertices, [], faces)", self.base_source)
        self.assertNotIn("_selected_polygons", self.base_source)

    def test_pattern_builds_one_primary_body_shell(self) -> None:
        function = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_torso_and_saddle"
        )
        function_source = ast.get_source_segment(self.source, function) or ""
        self.assertEqual(function_source.count('"Heather_Body_Shell"'), 1)
        self.assertIn("seventeen-column shallow saddle", function_source)
        self.assertIn("yoke_rings = 5", function_source)
        self.assertNotIn("Heather_Highcut_Front_Panel", function_source)
        self.assertNotIn("Heather_Highcut_Back_Panel", function_source)
        self.assertNotIn("Heather_Crotch_Bridge", function_source)

    def test_clearance_projection_is_smoothed_and_bounded(self) -> None:
        required = (
            "maximum_step: float = 0.012",
            "for _ in range(4)",
            "0.55 * value + 0.45 * average",
            '"smoothingIterations": 4',
        )
        for fragment in required:
            self.assertIn(fragment, self.source)

    def test_shallow_saddle_does_not_converge_to_a_long_tip(self) -> None:
        required = (
            "return 0.710 + 0.055 * (side**2.0)",
            "offsets = tuple(range(-16, 17, 2))",
            "longitudinal_steps = 14",
            "point.z -= 0.004 * math.sin(math.pi * t)",
            'result["pelvicSaddleColumns"] = 17',
        )
        for fragment in required:
            self.assertIn(fragment, self.source)

    def test_sleeves_use_a_fitted_cap_profile(self) -> None:
        required = (
            "shoulder_inner = upper_head - direction * 0.018",
            "radius = 0.027 + 0.006",
            "radius = 0.033 - 0.001",
            "radius = 0.032 - 0.007",
        )
        for fragment in required:
            self.assertIn(fragment, self.source)
        self.assertNotIn("radius = 0.048 - 0.010", self.source)

    def test_compact_hood_is_a_surface_not_a_padded_tube(self) -> None:
        hood = self.source.split("def _folded_back_hood(", 1)[1].split(
            "def _validate(", 1
        )[0]
        self.assertIn("columns = 33", hood)
        self.assertIn("rows = 6", hood)
        self.assertIn("faces.append", hood)
        self.assertNotIn("curve_tube", hood)

    def test_build_gate_uses_required_objects_not_legacy_count(self) -> None:
        self.assertIn('"Heather_Hood_Folded_Roll"', self.build_source)
        self.assertIn("required_objects - garment_names", self.build_source)
        self.assertIn("not missing_objects", self.build_source)
        self.assertNotIn('measured["meshObjects"] >= 14', self.build_source)


if __name__ == "__main__":
    unittest.main()
