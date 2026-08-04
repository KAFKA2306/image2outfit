from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = ROOT / "tools" / "siroino_heather_polar_yoke_v26.py"
PRODUCT_PATH = ROOT / "tools" / "siroino_heather_hooded_product.py"
RETIRED_PATHS = (
    ROOT / "tools" / "siroino_heather_hooded_v21_patch.py",
    ROOT / "tools" / "siroino_heather_lobomap_fit.py",
    ROOT / "tools" / "siroino_heather_template_cage_v24.py",
    ROOT / "tools" / "siroino_heather_cross_section_cage_v25.py",
)


class GarmentGeometryAngularPolarYokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generator = GENERATOR_PATH.read_text(encoding="utf-8")
        cls.product = PRODUCT_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.generator, filename=str(GENERATOR_PATH))

    def test_active_product_installs_angular_polar_yoke(self) -> None:
        self.assertIn(
            "import siroino_heather_polar_yoke_v26 as polar_yoke",
            self.product,
        )
        self.assertLess(
            self.product.index("polar_yoke.install(pattern)"),
            self.product.index("DESIGN_REVISION = pattern.DESIGN_REVISION"),
        )
        self.assertNotIn("cross_section_cage.install(pattern)", self.product)
        self.assertNotIn("template_cage.install(pattern)", self.product)
        self.assertNotIn("v21.install(pattern)", self.product)
        self.assertNotIn("lobomap.install(pattern)", self.product)

    def test_superseded_fit_modules_are_removed(self) -> None:
        for path in RETIRED_PATHS:
            self.assertFalse(path.exists(), str(path))

    def test_generator_has_one_internal_pattern_parameter(self) -> None:
        imports = {
            alias.name
            for node in self.tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertFalse(
            any(name.startswith("siroino_") for name in imports),
            "The polar-yoke module must not add another internal import level",
        )
        self.assertIn("pattern: ModuleType", self.generator)

    def test_primary_surface_uses_height_by_angle_radius_field(self) -> None:
        self.assertIn("class PolarBodyProfile", self.generator)
        self.assertIn("HEIGHT_SAMPLES = 50", self.generator)
        self.assertIn("ANGLE_COUNT = 72", self.generator)
        self.assertIn("_angle_distance(angle, theta)", self.generator)
        self.assertIn("radii = _circular_average", self.generator)
        self.assertIn("field[level][angle_index] = value", self.generator)
        self.assertIn("point = profile.point(z, theta", self.generator)

    def test_torso_integrates_yoke_and_neck_ring(self) -> None:
        self.assertIn("def _side_strength(theta: float)", self.generator)
        self.assertIn("shoulder_boost = 0.044", self.generator)
        self.assertIn("neck_start = len(vertices)", self.generator)
        self.assertIn("0.071 * math.cos(theta)", self.generator)

    def test_underbody_is_shorter_wider_shared_edge_gusset(self) -> None:
        self.assertIn("return 0.625 + 0.180 * (side**1.60)", self.generator)
        self.assertIn("half_span = 4", self.generator)
        self.assertIn("steps = 16", self.generator)
        self.assertIn("point.z -= 0.018 * math.sin(math.pi * t)", self.generator)

    def test_sleeves_are_reduced_and_extended_beneath_yoke(self) -> None:
        self.assertIn('f"UpperArm_{side}"', self.generator)
        self.assertIn('f"LowerArm_{side}"', self.generator)
        self.assertIn(
            "shoulder_inner = upper_head - upper_direction * 0.030", self.generator
        )
        self.assertIn("radius = 0.039 - 0.013 * _smoothstep(t)", self.generator)

    def test_hood_is_a_three_dimensional_open_front_shell(self) -> None:
        self.assertIn("def _open_front_hood(", self.generator)
        self.assertIn("theta_start = -math.pi / 4.0", self.generator)
        self.assertIn("theta_end = 5.0 * math.pi / 4.0", self.generator)
        self.assertIn(
            '"three-dimensional open-front polar hood shell"', self.generator
        )

    def test_body_is_reference_not_topology_source(self) -> None:
        self.assertIn('obj["bodyTopologyCopied"] = False', self.generator)
        self.assertIn('obj["ellipseOnlyProfileUsed"] = False', self.generator)
        self.assertNotIn("BVHTree.FromPolygons", self.generator)
        self.assertNotIn("_selected_polygons", self.generator)


if __name__ == "__main__":
    unittest.main()
