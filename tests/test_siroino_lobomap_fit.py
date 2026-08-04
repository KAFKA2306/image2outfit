from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = "siroino-heather-hooded-bodysuit"
REVISION = "v25-side-aware-taubin-shell"


class SiroinoLoBoMapFitTests(unittest.TestCase):
    def test_product_executes_body_anchor_lobomap_then_side_aware_repair(self) -> None:
        product = (ROOT / "tools" / "siroino_heather_hooded_product.py").read_text(
            encoding="utf-8"
        )
        lobomap = (ROOT / "tools" / "siroino_heather_lobomap_fit.py").read_text(
            encoding="utf-8"
        )
        compatibility = (
            ROOT / "tools" / "siroino_heather_smooth_surface_repair.py"
        ).read_text(encoding="utf-8")
        fairing = (
            ROOT / "tools" / "siroino_heather_side_aware_fairing.py"
        ).read_text(encoding="utf-8")
        self.assertIn("import siroino_heather_lobomap_fit as lobomap", product)
        self.assertLess(
            product.index("v21.install(pattern)"),
            product.index("lobomap.install(pattern)"),
        )
        self.assertIn(
            "import siroino_heather_smooth_surface_repair as repair",
            lobomap,
        )
        self.assertIn("repair.install(pattern)", lobomap)
        self.assertIn(
            "from siroino_heather_side_aware_fairing import DESIGN_REVISION, install",
            compatibility,
        )
        self.assertIn("pattern.create_outfit = create_outfit", fairing)

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

    def test_side_aware_repair_executes_measured_mesh_operations(self) -> None:
        source = (
            ROOT / "tools" / "siroino_heather_side_aware_fairing.py"
        ).read_text(encoding="utf-8")
        for token in (
            "bmesh.ops.holes_fill",
            "FAIRING_LAMBDA = 0.24",
            "FAIRING_MU = -0.245",
            "UNDERBODY_CLEARANCE_M = 0.034",
            "POSE_CORRECTION_ROUNDS = 2",
            "body_tree.overlap(shell_tree)",
            "continuous subdivided and solidified folded hood panel",
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
            "tools/siroino_heather_hooded_product.py",
        )
        self.assertEqual(
            job["researchMethod"]["paperUrl"],
            "https://arxiv.org/abs/2605.07450",
        )
        expected = (
            f"Assets/GenWorks/{PRODUCT}/Research/"
            "side-aware-taubin-shell-trial.json"
        )
        self.assertEqual(construction["researchTrial"]["generatedEvidence"], expected)
        self.assertIn(expected, job["deliveryAssets"])


if __name__ == "__main__":
    unittest.main()
