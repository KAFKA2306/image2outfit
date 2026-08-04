from __future__ import annotations

import ast
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "pyproject.toml"
GENERATOR_PATH = ROOT / "tools" / "siroino_heather_fused_roll_v28.py"
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
        self.assertIn("_enforce_clearance", self.base_source)
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
        self.assertIn("fifteen-column flat pelvic saddle", function_source)
        self.assertNotIn("Heather_Highcut_Front_Panel", function_source)
        self.assertNotIn("Heather_Highcut_Back_Panel", function_source)
        self.assertNotIn("Heather_Crotch_Bridge", function_source)

    def test_flat_saddle_does_not_converge_to_a_long_tip(self) -> None:
        required = (
            "return 0.665 + 0.105 * (side**1.80)",
            "offsets = tuple(range(-14, 15, 2))",
            "longitudinal_steps = 16",
            "point.z -= 0.012 * math.sin(math.pi * t)",
            "subdivision_levels=0",
            'result["pelvicSaddleColumns"] = 15',
        )
        for fragment in required:
            self.assertIn(fragment, self.source)

    def test_sleeves_use_a_contoured_cap_profile(self) -> None:
        required = (
            "shoulder_inner = upper_head - direction * 0.038",
            "radius = 0.034 + 0.014",
            "radius = 0.048 - 0.010",
            "radius = 0.038 - 0.012",
        )
        for fragment in required:
            self.assertIn(fragment, self.source)
        self.assertNotIn("radius = 0.058 - 0.019", self.source)

    def test_rejected_hood_sheet_is_replaced_by_a_roll(self) -> None:
        hood = self.source.split("def _folded_back_hood(", 1)[1].split(
            "def _validate(", 1
        )[0]
        self.assertIn("pattern.v9.base.curve_tube", hood)
        self.assertIn("samples = 33", hood)
        self.assertIn("0.019,", hood)
        self.assertNotIn("faces.append", hood)
        self.assertNotIn("columns = 40", hood)

    def test_build_gate_uses_required_objects_not_legacy_count(self) -> None:
        self.assertIn('"Heather_Hood_Folded_Roll"', self.build_source)
        self.assertIn("required_objects - garment_names", self.build_source)
        self.assertIn("not missing_objects", self.build_source)
        self.assertNotIn('measured["meshObjects"] >= 14', self.build_source)


if __name__ == "__main__":
    unittest.main()
