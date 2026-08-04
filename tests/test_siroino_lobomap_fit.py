from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = "siroino-heather-hooded-bodysuit"
REVISION = "v25-cross-sectional-statistical-cage"


class SiroinoCrossSectionCageTests(unittest.TestCase):
    def test_product_replaces_previous_active_fit_paths(self) -> None:
        product = (ROOT / "tools" / "siroino_heather_hooded_product.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "import siroino_heather_cross_section_cage_v25 as cross_section_cage",
            product,
        )
        self.assertIn("cross_section_cage.install(pattern)", product)
        self.assertNotIn("template_cage.install(pattern)", product)
        self.assertNotIn("v21.install(pattern)", product)
        self.assertNotIn("lobomap.install(pattern)", product)

    def test_cross_section_cage_does_not_copy_body_topology(self) -> None:
        source = (
            ROOT / "tools" / "siroino_heather_cross_section_cage_v25.py"
        ).read_text(encoding="utf-8")
        for token in (
            'DESIGN_REVISION = "v25-cross-sectional-statistical-cage"',
            "class CrossSectionProfile",
            "TORSO_COLUMNS = 72",
            'obj["bodyTopologyCopied"] = False',
            'obj["binaryFrontBackSamplingUsed"] = False',
            '"authorsImplementationExecuted": False',
            '"authorsCodeCopied": False',
            "pattern.create_outfit = lambda",
        ):
            self.assertIn(token, source)
        self.assertNotIn("BVHTree.FromPolygons", source)
        self.assertNotIn("_selected_polygons", source)

    def test_job_and_construction_track_cross_section_trial(self) -> None:
        config_root = ROOT / "config" / "products" / PRODUCT
        job = json.loads((config_root / "job.json").read_text(encoding="utf-8"))
        construction = json.loads(
            (config_root / "construction.json").read_text(encoding="utf-8")
        )
        self.assertEqual(job["buildRevision"], REVISION)
        self.assertEqual(construction["designRevision"], REVISION)
        self.assertIn(
            "no-binary-front-back-sampling-for-primary-surface",
            construction["panels"],
        )
        self.assertIn(
            "body topology and binary front/back circumferential sampling are not used",
            construction["researchTrial"]["implementation"],
        )
        evidence = f"Assets/GenWorks/{PRODUCT}/Research/cross-sectional-cage-trial.json"
        self.assertEqual(construction["researchTrial"]["generatedEvidence"], evidence)
        self.assertIn(evidence, job["deliveryAssets"])
        self.assertEqual(
            job["researchMethod"]["currentReference"]["paperUrl"],
            "https://arxiv.org/abs/2606.24564",
        )


if __name__ == "__main__":
    unittest.main()
