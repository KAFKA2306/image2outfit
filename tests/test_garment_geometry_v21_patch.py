from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = ROOT / "tools" / "siroino_heather_manifold_yoke_v29.py"
BASE_PATH = ROOT / "tools" / "siroino_heather_closed_components_v27.py"
PRODUCT_PATH = ROOT / "tools" / "siroino_heather_hooded_product.py"
POSE_PATH = ROOT / "tools" / "siroino_heather_hooded_fused_pose_probe.py"
JOB_PATH = ROOT / "config" / "products" / "siroino-heather-hooded-bodysuit" / "job.json"


class GarmentGeometryManifoldYokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generator = GENERATOR_PATH.read_text(encoding="utf-8")
        cls.base = BASE_PATH.read_text(encoding="utf-8")
        cls.product = PRODUCT_PATH.read_text(encoding="utf-8")
        cls.pose = POSE_PATH.read_text(encoding="utf-8")
        cls.job = json.loads(JOB_PATH.read_text(encoding="utf-8"))
        cls.tree = ast.parse(cls.generator, filename=str(GENERATOR_PATH))

    def test_stable_entrypoints_install_v29(self) -> None:
        self.assertEqual(
            self.job["buildScript"],
            "tools/siroino_heather_hooded_product.py",
        )
        self.assertIn(
            "import siroino_heather_manifold_yoke_v29 as manifold_yoke",
            self.product,
        )
        self.assertIn("manifold_yoke.install(pattern)", self.product)
        self.assertIn("import siroino_heather_hooded_pattern as pattern", self.product)

    def test_v29_reuses_the_validated_geometry_chain_with_depth_four(self) -> None:
        imports = {
            alias.name
            for node in self.tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
            if alias.name.startswith("siroino_")
        }
        self.assertEqual(imports, {"siroino_heather_fused_roll_v28"})
        for token in (
            "class PolarBodyProfile",
            "HEIGHT_SAMPLES = 50",
            "ANGLE_COUNT = 72",
            "BVHTree.FromPolygons",
            '"bodyTopologyCopied": False',
        ):
            self.assertIn(token, self.base)

    def test_clearance_is_bounded_and_topology_smoothed(self) -> None:
        self.assertIn("maximum_step: float = 0.012", self.generator)
        self.assertIn("for _ in range(4)", self.generator)
        self.assertIn("0.55 * value + 0.45 * average", self.generator)
        self.assertIn('"smoothingIterations": 4', self.generator)
        self.assertNotIn("maximum_step: float = 0.040", self.generator)

    def test_yoke_closes_through_five_tapered_rings(self) -> None:
        self.assertIn("yoke_rings = 5", self.generator)
        self.assertIn("0.057 * math.cos(theta)", self.generator)
        self.assertIn("-0.006 + 0.045 * math.sin(theta)", self.generator)
        self.assertIn("1.088 + 0.004 * math.sin(theta)", self.generator)
        self.assertIn('obj["taperedYokeRings"] = yoke_rings', self.generator)

    def test_underbody_is_shallow_and_seventeen_columns_wide(self) -> None:
        self.assertIn("return 0.710 + 0.055 * (side**2.0)", self.generator)
        self.assertIn("offsets = tuple(range(-16, 17, 2))", self.generator)
        self.assertIn("longitudinal_steps = 14", self.generator)
        self.assertIn("point.z -= 0.004 * math.sin(math.pi * t)", self.generator)
        self.assertIn('result["pelvicSaddleColumns"] = 17', self.generator)

    def test_sleeves_are_fitted_instead_of_bulbous(self) -> None:
        self.assertIn("shoulder_inner = upper_head - direction * 0.018", self.generator)
        self.assertIn("radius = 0.027 + 0.006", self.generator)
        self.assertIn("radius = 0.033 - 0.001", self.generator)
        self.assertIn("radius = 0.032 - 0.007", self.generator)
        self.assertNotIn("radius = 0.048 - 0.010", self.generator)

    def test_hood_is_a_compact_rear_neck_surface(self) -> None:
        hood_section = self.generator.split("def _folded_back_hood(", 1)[1].split(
            "def _validate(", 1
        )[0]
        self.assertIn("columns = 33", hood_section)
        self.assertIn("rows = 6", hood_section)
        self.assertIn("x_radius = 0.060 + 0.025 * v", hood_section)
        self.assertIn("faces.append", hood_section)
        self.assertNotIn("curve_tube", hood_section)

    def test_pose_adapter_and_truth_boundary_remain_active(self) -> None:
        self.assertIn("camera.data.ortho_scale *= 1.24", self.pose)
        self.assertIn('manifest["status"] = "WORKING"', self.product)
        self.assertIn(
            'manifest["technicalGates"]["visualAppearanceReview"] = "PENDING"',
            self.product,
        )
        self.assertIn('"authorsImplementationExecuted": False', self.product)
        self.assertIn('"authorsCodeCopied": False', self.product)


if __name__ == "__main__":
    unittest.main()
