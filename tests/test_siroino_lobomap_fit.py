from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = "siroino-heather-hooded-bodysuit"
REVISION = "v23-dama-anchor-lobomap-residual-fit"


class SiroinoLoBoMapFitTests(unittest.TestCase):
    def test_product_executes_body_anchor_then_lobomap(self) -> None:
        product = (ROOT / "tools" / "siroino_heather_hooded_product.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("import siroino_heather_lobomap_fit as lobomap", product)
        self.assertIn("v21.install(pattern)", product)
        self.assertIn("lobomap.install(pattern)", product)
        self.assertLess(
            product.index("v21.install(pattern)"),
            product.index("lobomap.install(pattern)"),
        )
        self.assertLess(
            product.index("lobomap.install(pattern)"),
            product.index("DESIGN_REVISION = pattern.DESIGN_REVISION"),
        )

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

    def test_job_and_construction_track_the_executed_trial(self) -> None:
        config_root = ROOT / "config" / "products" / PRODUCT
        job = json.loads((config_root / "job.json").read_text(encoding="utf-8"))
        construction = json.loads(
            (config_root / "construction.json").read_text(encoding="utf-8")
        )
        self.assertEqual(job["buildRevision"], REVISION)
        self.assertEqual(construction["designRevision"], REVISION)
        self.assertEqual(
            job["researchMethod"]["paperUrl"],
            "https://arxiv.org/abs/2605.07450",
        )
        self.assertEqual(
            construction["researchTrial"]["generatedEvidence"],
            f"Assets/GenWorks/{PRODUCT}/Research/lobofit-local-bone-trial.json",
        )
        self.assertIn(
            f"Assets/GenWorks/{PRODUCT}/Research/lobofit-local-bone-trial.json",
            job["deliveryAssets"],
        )


if __name__ == "__main__":
    unittest.main()
