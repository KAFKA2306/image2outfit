from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = "siroino-heather-hooded-bodysuit"
REVISION = "v28-flat-saddle-contoured-cap-hood-roll"


class SiroinoFusedRollTests(unittest.TestCase):
    def test_v28_entrypoint_overrides_v27_visual_mechanisms(self) -> None:
        product = (
            ROOT / "tools" / "siroino_heather_hooded_fused_product.py"
        ).read_text(encoding="utf-8")
        generator = (ROOT / "tools" / "siroino_heather_fused_roll_v28.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "import siroino_heather_fused_roll_v28 as fused_roll",
            product,
        )
        self.assertIn("fused_roll.install(product.pattern)", product)
        for token in (
            'DESIGN_REVISION = "v28-flat-saddle-contoured-cap-hood-roll"',
            "base._torso_and_saddle = _torso_and_saddle",
            "base._sleeve = _sleeve",
            "base._folded_back_hood = _folded_back_hood",
            "base._validate = _validate",
        ):
            self.assertIn(token, generator)

    def test_v28_keeps_bounded_body_reference_operations(self) -> None:
        base = (
            ROOT / "tools" / "siroino_heather_closed_components_v27.py"
        ).read_text(encoding="utf-8")
        for token in (
            "class PolarBodyProfile",
            "HEIGHT_SAMPLES = 50",
            "ANGLE_COUNT = 72",
            "BVHTree.FromPolygons",
            "_enforce_clearance",
            '"bodyTopologyCopied": False',
            '"authorsImplementationExecuted": False',
            '"authorsCodeCopied": False',
        ):
            self.assertIn(token, base)
        self.assertNotIn("_selected_polygons", base)

    def test_job_and_construction_track_v28_trial(self) -> None:
        config_root = ROOT / "config" / "products" / PRODUCT
        job = json.loads((config_root / "job.json").read_text(encoding="utf-8"))
        construction = json.loads(
            (config_root / "construction.json").read_text(encoding="utf-8")
        )
        self.assertEqual(job["buildRevision"], REVISION)
        self.assertEqual(construction["designRevision"], REVISION)
        self.assertEqual(
            job["productBuildScript"],
            "tools/siroino_heather_hooded_fused_product.py",
        )
        self.assertEqual(
            job["hostedPoseScript"],
            "tools/siroino_heather_hooded_fused_pose_probe.py",
        )
        self.assertIn("fifteen-column-flat-pelvic-saddle", construction["panels"])
        self.assertIn(
            "contoured-small-root-shoulder-cap-sleeves",
            construction["panels"],
        )
        self.assertIn(
            "u-shaped-rear-neck-folded-hood-roll",
            construction["panels"],
        )
        evidence = (
            f"Assets/GenWorks/{PRODUCT}/Research/"
            "flat-saddle-cap-hood-roll-trial.json"
        )
        self.assertEqual(construction["researchTrial"]["generatedEvidence"], evidence)
        self.assertIn(evidence, job["deliveryAssets"])
        self.assertIn(
            f"Assets/GenWorks/{PRODUCT}/Research/closed-components-clearance-trial.json",
            job["deliveryAssets"],
        )
        self.assertEqual(
            job["researchMethod"]["currentReference"]["paperUrl"],
            "https://arxiv.org/abs/2606.24564",
        )


if __name__ == "__main__":
    unittest.main()
