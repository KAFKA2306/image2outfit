from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = ROOT / "tools" / "siroino_heather_closed_components_v27.py"
PRODUCT_PATH = ROOT / "tools" / "siroino_heather_hooded_product.py"
RETIRED_PATHS = (
    ROOT / "tools" / "siroino_heather_hooded_v21_patch.py",
    ROOT / "tools" / "siroino_heather_lobomap_fit.py",
    ROOT / "tools" / "siroino_heather_template_cage_v24.py",
    ROOT / "tools" / "siroino_heather_cross_section_cage_v25.py",
    ROOT / "tools" / "siroino_heather_polar_yoke_v26.py",
)


class GarmentGeometryClosedComponentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generator = GENERATOR_PATH.read_text(encoding="utf-8")
        cls.product = PRODUCT_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.generator, filename=str(GENERATOR_PATH))

    def test_active_product_installs_closed_components(self) -> None:
        self.assertIn(
            "import siroino_heather_closed_components_v27 as closed_components",
            self.product,
        )
        self.assertLess(
            self.product.index("closed_components.install(pattern)"),
            self.product.index("DESIGN_REVISION = pattern.DESIGN_REVISION"),
        )
        for token in (
            "polar_yoke.install(pattern)",
            "cross_section_cage.install(pattern)",
            "template_cage.install(pattern)",
            "v21.install(pattern)",
            "lobomap.install(pattern)",
        ):
            self.assertNotIn(token, self.product)

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
            "The closed-components module must not add another internal import level",
        )
        self.assertIn("pattern: ModuleType", self.generator)

    def test_primary_surface_retains_height_by_angle_radius_field(self) -> None:
        for token in (
            "class PolarBodyProfile",
            "HEIGHT_SAMPLES = 50",
            "ANGLE_COUNT = 72",
            "_angle_distance(angle, theta)",
            "_circular_average(_circular_average(radii, 2), 2)",
            "field[level][angle_index] = value",
            "point = profile.point(z, theta",
        ):
            self.assertIn(token, self.generator)

    def test_underbody_is_an_eleven_column_surface_saddle(self) -> None:
        self.assertIn("offsets = tuple(range(-10, 11, 2))", self.generator)
        self.assertIn("longitudinal_steps = 16", self.generator)
        self.assertIn("point.z -= 0.024 * math.sin(math.pi * t)", self.generator)
        self.assertIn('obj["pelvicSaddleColumns"] = len(front_row)', self.generator)
        self.assertIn('"pelvicSaddleColumns": 11', self.generator)

    def test_sleeve_caps_overlap_the_yoke(self) -> None:
        self.assertIn('f"UpperArm_{side}"', self.generator)
        self.assertIn('f"LowerArm_{side}"', self.generator)
        self.assertIn("shoulder_inner = upper_head - direction * 0.055", self.generator)
        self.assertIn("radius = 0.056 - 0.017", self.generator)
        self.assertIn("minimum_clearance=0.010", self.generator)

    def test_hood_is_a_low_folded_back_shell(self) -> None:
        self.assertIn("def _folded_back_hood(", self.generator)
        self.assertIn("columns = 40", self.generator)
        self.assertIn("rows = 9", self.generator)
        self.assertIn("theta = math.pi * column / (columns - 1)", self.generator)
        self.assertIn(
            'obj["hoodConstruction"] = "low folded-back hood shell attached around rear neck"',
            self.generator,
        )

    def test_clearance_projection_occurs_after_topology_creation(self) -> None:
        self.assertLess(
            self.generator.index("mesh.from_pydata(vertices, [], faces)"),
            self.generator.index("_enforce_clearance(obj, body_tree, minimum_clearance)"),
        )
        self.assertIn("maximum_step: float = 0.040", self.generator)
        self.assertIn("BVHTree.FromPolygons", self.generator)
        self.assertIn('"bodyTopologyCopied": False', self.generator)
        self.assertNotIn("_selected_polygons", self.generator)


if __name__ == "__main__":
    unittest.main()
