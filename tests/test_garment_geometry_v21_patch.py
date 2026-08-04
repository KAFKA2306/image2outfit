from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = ROOT / "tools" / "siroino_heather_cross_section_cage_v25.py"
PRODUCT_PATH = ROOT / "tools" / "siroino_heather_hooded_product.py"
RETIRED_PATHS = (
    ROOT / "tools" / "siroino_heather_hooded_v21_patch.py",
    ROOT / "tools" / "siroino_heather_lobomap_fit.py",
    ROOT / "tools" / "siroino_heather_template_cage_v24.py",
)


class GarmentGeometryCrossSectionCageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generator = GENERATOR_PATH.read_text(encoding="utf-8")
        cls.product = PRODUCT_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.generator, filename=str(GENERATOR_PATH))

    def test_active_product_installs_cross_section_cage(self) -> None:
        self.assertIn(
            "import siroino_heather_cross_section_cage_v25 as cross_section_cage",
            self.product,
        )
        self.assertLess(
            self.product.index("cross_section_cage.install(pattern)"),
            self.product.index("DESIGN_REVISION = pattern.DESIGN_REVISION"),
        )
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
            "The cage module must not add another internal import level",
        )
        self.assertIn("pattern: ModuleType", self.generator)

    def test_primary_surface_uses_smoothed_cross_section_statistics(self) -> None:
        self.assertIn("class CrossSectionProfile", self.generator)
        self.assertIn("SAMPLE_COUNT = 54", self.generator)
        self.assertIn(
            "_quantile([abs(point.x) for point in points], 0.94)", self.generator
        )
        self.assertIn("smooth_x = _moving_average(raw_x)", self.generator)
        self.assertIn(
            "point = profile.point(z, theta, BODY_CLEARANCE_M)", self.generator
        )
        self.assertNotIn(
            "sampler.point(\n                x,\n                z,", self.generator
        )

    def test_torso_has_analytic_high_cut_boundary(self) -> None:
        self.assertIn("TORSO_COLUMNS = 72", self.generator)
        self.assertIn("TORSO_ROWS = 24", self.generator)
        self.assertIn("def _bottom_z(theta: float)", self.generator)
        self.assertIn("0.575 + 0.245 * (side**1.55)", self.generator)

    def test_underbody_is_a_shared_edge_u_gusset(self) -> None:
        self.assertIn("pair_rows: list[tuple[int, int]]", self.generator)
        self.assertIn("pairwise(pair_rows)", self.generator)
        self.assertIn(
            "faces.append((current[0], current[1], following[1], following[0]))",
            self.generator,
        )

    def test_sleeves_are_reduced_and_extended_inward(self) -> None:
        self.assertIn('f"UpperArm_{side}"', self.generator)
        self.assertIn('f"LowerArm_{side}"', self.generator)
        self.assertIn(
            "shoulder_inner = upper_head - upper_direction * 0.018", self.generator
        )
        self.assertIn("radius = 0.047 - 0.018 * _smoothstep(t)", self.generator)

    def test_cowl_is_analytic_and_does_not_use_body_sampler(self) -> None:
        self.assertIn("def _attached_cowl(", self.generator)
        self.assertIn(
            '"analytic attached cowl; no body sampler or detached tube"',
            self.generator,
        )

    def test_body_is_reference_not_topology_source(self) -> None:
        self.assertIn('obj["bodyTopologyCopied"] = False', self.generator)
        self.assertIn('obj["binaryFrontBackSamplingUsed"] = False', self.generator)
        self.assertNotIn("BVHTree.FromPolygons", self.generator)
        self.assertNotIn("_selected_polygons", self.generator)


if __name__ == "__main__":
    unittest.main()
