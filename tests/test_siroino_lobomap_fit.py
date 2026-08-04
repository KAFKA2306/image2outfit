from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = "siroino-heather-hooded-bodysuit"
REVISION = "v24-structured-template-cage"


class SiroinoStructuredTemplateCageTests(unittest.TestCase):
    def test_product_replaces_body_anchor_and_lobomap_active_path(self) -> None:
        product = (ROOT / "tools" / "siroino_heather_hooded_product.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("import siroino_heather_template_cage_v24 as template_cage", product)
        self.assertIn("template_cage.install(pattern)", product)
        self.assertNotIn("v21.install(pattern)", product)
        self.assertNotIn("lobomap.install(pattern)", product)

    def test_template_cage_is_explicit_and_does_not_copy_body_topology(self) -> None:
        source = (ROOT / "tools" / "siroino_heather_template_cage_v24.py").read_text(
            encoding="utf-8"
        )
        for token in (
            'DESIGN_REVISION = "v24-structured-template-cage"',
            "TORSO_COLUMNS = 64",
            "shared-edge U-shaped gusset",
            'obj["bodyTopologyCopied"] = False',
            '"bodyRole": "surface and skin-weight reference only"',
            '"authorsImplementationExecuted": False',
            '"authorsCodeCopied": False',
            "pattern.create_outfit = lambda",
        ):
            self.assertIn(token, source)
        self.assertNotIn("BVHTree.FromPolygons", source)
        self.assertNotIn("_selected_polygons", source)

    def test_job_and_construction_track_structured_trial(self) -> None:
        config_root = ROOT / "config" / "products" / PRODUCT
        job = json.loads((config_root / "job.json").read_text(encoding="utf-8"))
        construction = json.loads(
            (config_root / "construction.json").read_text(encoding="utf-8")
        )
        self.assertEqual(job["buildRevision"], REVISION)
        self.assertEqual(construction["designRevision"], REVISION)
        self.assertIn(
            "no-body-topology-copy-no-body-face-selection",
            construction["panels"],
        )
        self.assertIn(
            "body topology is not copied",
            construction["researchTrial"]["implementation"],
        )
        evidence = (
            f"Assets/GenWorks/{PRODUCT}/Research/"
            "structured-template-cage-trial.json"
        )
        self.assertEqual(construction["researchTrial"]["generatedEvidence"], evidence)
        self.assertIn(evidence, job["deliveryAssets"])
        self.assertEqual(
            job["researchMethod"]["currentReference"]["paperUrl"],
            "https://arxiv.org/abs/2606.24564",
        )


if __name__ == "__main__":
    unittest.main()
