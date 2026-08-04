from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = ROOT / "tools" / "siroino_heather_fused_roll_v28.py"
BASE_PATH = ROOT / "tools" / "siroino_heather_closed_components_v27.py"
PRODUCT_PATH = ROOT / "tools" / "siroino_heather_hooded_product.py"
POSE_PATH = ROOT / "tools" / "siroino_heather_hooded_fused_pose_probe.py"
JOB_PATH = ROOT / "config" / "products" / "siroino-heather-hooded-bodysuit" / "job.json"


class GarmentGeometryFusedRollTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generator = GENERATOR_PATH.read_text(encoding="utf-8")
        cls.base = BASE_PATH.read_text(encoding="utf-8")
        cls.product = PRODUCT_PATH.read_text(encoding="utf-8")
        cls.pose = POSE_PATH.read_text(encoding="utf-8")
        cls.job = json.loads(JOB_PATH.read_text(encoding="utf-8"))
        cls.tree = ast.parse(cls.generator, filename=str(GENERATOR_PATH))

    def test_stable_entrypoints_install_v28(self) -> None:
        self.assertEqual(
            self.job["buildScript"],
            "tools/siroino_heather_hooded_product.py",
        )
        self.assertEqual(
            self.job["hostedPoseScript"],
            "tools/siroino_heather_hooded_fused_pose_probe.py",
        )
        self.assertIn(
            "import siroino_heather_fused_roll_v28 as fused_roll",
            self.product,
        )
        self.assertIn("fused_roll.install(pattern)", self.product)
        self.assertIn("import siroino_heather_hooded_pattern as pattern", self.product)
        self.assertNotIn("siroino_heather_hooded_pattern_v13", self.product)

    def test_v28_reuses_one_validated_geometry_base(self) -> None:
        imports = {
            alias.name
            for node in self.tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
            if alias.name.startswith("siroino_")
        }
        self.assertEqual(imports, {"siroino_heather_closed_components_v27"})
        for token in (
            "class PolarBodyProfile",
            "HEIGHT_SAMPLES = 50",
            "ANGLE_COUNT = 72",
            "BVHTree.FromPolygons",
            "_enforce_clearance",
            '"bodyTopologyCopied": False',
        ):
            self.assertIn(token, self.base)

    def test_underbody_is_flat_and_fifteen_columns_wide(self) -> None:
        self.assertIn("return 0.665 + 0.105 * (side**1.80)", self.generator)
        self.assertIn("offsets = tuple(range(-14, 15, 2))", self.generator)
        self.assertIn("longitudinal_steps = 16", self.generator)
        self.assertIn("point.z -= 0.012 * math.sin(math.pi * t)", self.generator)
        self.assertIn("subdivision_levels=0", self.generator)
        self.assertIn('result["pelvicSaddleColumns"] = 15', self.generator)

    def test_sleeve_root_has_a_contoured_radius_profile(self) -> None:
        self.assertIn("shoulder_inner = upper_head - direction * 0.038", self.generator)
        self.assertIn("radius = 0.034 + 0.014", self.generator)
        self.assertIn("radius = 0.048 - 0.010", self.generator)
        self.assertIn("radius = 0.038 - 0.012", self.generator)
        self.assertNotIn("radius = 0.058 - 0.019", self.generator)

    def test_hood_is_a_u_shaped_roll_not_a_sheet(self) -> None:
        self.assertIn("samples = 33", self.generator)
        self.assertIn("0.088 * math.cos(theta)", self.generator)
        self.assertIn("0.019,", self.generator)
        self.assertIn(
            '"contoured U-shaped folded hood roll around rear neck"',
            self.generator,
        )
        self.assertNotIn("columns = 40", self.generator)
        hood_section = self.generator.split("def _folded_back_hood(", 1)[1].split(
            "def _validate(", 1
        )[0]
        self.assertNotIn("faces.append", hood_section)

    def test_pose_adapter_widens_every_required_view(self) -> None:
        self.assertIn("camera.data.ortho_scale *= 1.24", self.pose)
        self.assertIn("target[2] + 0.075", self.pose)
        self.assertIn("return probe.main()", self.pose)

    def test_v28_preserves_truth_boundary(self) -> None:
        self.assertIn('manifest["status"] = "WORKING"', self.product)
        self.assertIn(
            'manifest["technicalGates"]["visualAppearanceReview"] = "PENDING"',
            self.product,
        )
        self.assertIn('"authorsImplementationExecuted": False', self.product)
        self.assertIn('"authorsCodeCopied": False', self.product)


if __name__ == "__main__":
    unittest.main()
