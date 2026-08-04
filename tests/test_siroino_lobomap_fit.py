from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = "siroino-heather-hooded-bodysuit"
REVISION = "v24-smooth-normal-highcut-repair"


class SiroinoLoBoMapFitTests(unittest.TestCase):
    def test_product_executes_body_anchor_lobomap_then_surface_repair(self) -> None:
        product = (ROOT / "tools" / "siroino_heather_hooded_product.py").read_text(
            encoding="utf-8"
        )
        wrapper = (
            ROOT / "tools" / "siroino_heather_hooded_product_v24.py"
        ).read_text(encoding="utf-8")
        self.assertIn("import siroino_heather_lobomap_fit as lobomap", product)
        self.assertIn("v21.install(pattern)", product)
        self.assertIn("lobomap.install(pattern)", product)
        self.assertLess(
            product.index("v21.install(pattern)"),
            product.index("lobomap.install(pattern)"),
        )
        self.assertIn(
            "import siroino_heather_smooth_surface_repair as repair",
            wrapper,
        )
        self.assertIn("repair.install(base.pattern)", wrapper)
        self.assertIn("base.DESIGN_REVISION = base.pattern.DESIGN_REVISION", wrapper)

    def test_local_bone_trial_is_a_real_bounded_geometry_operation(self) -> None:
        source = (ROOT / "tools" / "siroino_heather_lobomap_fit.py").read_text(
            encoding="utf-8"
        )
        for token in (
            "BVHTree.FromPolygons",
            "armature.pose.bones",
            "inverse_rotations",
            "localResidualEdgeRmsBeforeM",
            "localResidualEdgeRmsAfterM",
            "MAX_STEP_M = 0.004",
            '"authorsImplementationExecuted": False',
            '"authorsCodeCopied": False',
            "vertex.co = inverse_object @ candidate",
        ):
            self.assertIn(token, source)

    def test_surface_repair_mutates_real_mesh_with_bounded_operations(self) -> None:
        source = (
            ROOT / "tools" / "siroino_heather_smooth_surface_repair.py"
        ).read_text(encoding="utf-8")
        for token in (
            "bmesh.ops.holes_fill",
            "barycentric interpolation of evaluated body vertex normals",
            "HIGHCUT_MAX_LIFT_M = 0.090",
            "REPAIR_MAX_WORLD_STEP_M = 0.095",
            "HOOD_LATERAL_SCALE = 0.72",
            "vertex.co = inverse_object @ candidate",
            '"completionClaim": False',
        ):
            self.assertIn(token, source)

    def test_job_and_construction_track_the_executed_trial(self) -> None:
        config_root = ROOT / "config" / "products" / PRODUCT
        job = json.loads((config_root / "job.json").read_text(encoding="utf-8"))
        construction = json.loads(
            (config_root / "construction.json").read_text(encoding="utf-8")
        )
        self.assertEqual(job["buildRevision"], REVISION)
        self.assertEqual(construction["designRevision"], REVISION)
        self.assertEqual(
            job["buildScript"],
            "tools/siroino_heather_hooded_product_v24.py",
        )
        self.assertEqual(
            job["researchMethod"]["paperUrl"],
            "https://arxiv.org/abs/2605.07450",
        )
        expected = (
            f"Assets/GenWorks/{PRODUCT}/Research/"
            "smooth-normal-highcut-repair-trial.json"
        )
        self.assertEqual(construction["researchTrial"]["generatedEvidence"], expected)
        self.assertIn(expected, job["deliveryAssets"])


if __name__ == "__main__":
    unittest.main()
