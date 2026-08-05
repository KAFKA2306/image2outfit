from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = "siroino-heather-hooded-bodysuit"
REVISION = "v29-smoothed-clearance-tapered-yoke-fitted-sleeve"


class SiroinoManifoldYokeTests(unittest.TestCase):
    def test_v29_entrypoint_overrides_v28_visual_mechanisms(self) -> None:
        product = (ROOT / "tools" / "siroino_heather_hooded_product.py").read_text(
            encoding="utf-8"
        )
        generator = (ROOT / "tools" / "siroino_heather_manifold_yoke_v29.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "import siroino_heather_manifold_yoke_v29 as manifold_yoke",
            product,
        )
        self.assertIn("manifold_yoke.install(pattern)", product)
        for token in (
            'DESIGN_REVISION = "v29-smoothed-clearance-tapered-yoke-fitted-sleeve"',
            "base._enforce_clearance = _enforce_clearance",
            "base._torso_and_saddle = _torso_and_saddle",
            "base._sleeve = _sleeve",
            "base._folded_back_hood = _folded_back_hood",
            "base._validate = _validate",
        ):
            self.assertIn(token, generator)

    def test_v29_keeps_bounded_body_reference_operations(self) -> None:
        base = (ROOT / "tools" / "siroino_heather_closed_components_v27.py").read_text(
            encoding="utf-8"
        )
        for token in (
            "class PolarBodyProfile",
            "HEIGHT_SAMPLES = 50",
            "ANGLE_COUNT = 72",
            "BVHTree.FromPolygons",
            '"bodyTopologyCopied": False',
            '"authorsImplementationExecuted": False',
            '"authorsCodeCopied": False',
        ):
            self.assertIn(token, base)
        self.assertNotIn("_selected_polygons", base)

    def test_job_and_construction_track_v29_trial(self) -> None:
        config_root = ROOT / "config" / "products" / PRODUCT
        job = json.loads((config_root / "job.json").read_text(encoding="utf-8"))
        construction = json.loads(
            (config_root / "construction.json").read_text(encoding="utf-8")
        )
        self.assertEqual(job["buildRevision"], REVISION)
        self.assertEqual(construction["designRevision"], REVISION)
        self.assertIn(
            "five-ring-tapered-shoulder-yoke-and-fitted-neck",
            construction["panels"],
        )
        self.assertIn(
            "seventeen-column-four-millimetre-sag-pelvic-saddle",
            construction["panels"],
        )
        self.assertIn("small-root-fitted-sleeve-caps", construction["panels"])
        self.assertIn(
            "compact-six-row-rear-neck-folded-hood",
            construction["panels"],
        )
        self.assertIn(
            "four-iteration-smoothed-bounded-clearance-projection",
            construction["panels"],
        )
        evidence = (
            f"Assets/GenWorks/{PRODUCT}/Research/smoothed-clearance-yoke-trial.json"
        )
        self.assertEqual(construction["researchTrial"]["generatedEvidence"], evidence)
        self.assertIn(evidence, job["deliveryAssets"])
        self.assertIn(
            f"Assets/GenWorks/{PRODUCT}/Research/flat-saddle-cap-hood-roll-trial.json",
            job["deliveryAssets"],
        )
        self.assertEqual(
            job["researchMethod"]["currentReference"]["paperUrl"],
            "https://arxiv.org/abs/2606.24564",
        )


if __name__ == "__main__":
    unittest.main()
