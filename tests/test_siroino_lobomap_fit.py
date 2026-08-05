from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = "siroino-heather-hooded-bodysuit"
REVISION = "v27-closed-saddle-sleevecap-folded-hood"


class SiroinoClosedComponentsTests(unittest.TestCase):
    def test_product_replaces_previous_active_fit_paths(self) -> None:
        product = (ROOT / "tools" / "siroino_heather_hooded_product.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "import siroino_heather_closed_components_v27 as closed_components",
            product,
        )
        self.assertIn("closed_components.install(pattern)", product)
        for token in (
            "v21.install(pattern)",
            "lobomap.install(pattern)",
            "repair.install(pattern)",
        ):
            self.assertNotIn(token, product)

    def test_closed_components_execute_bounded_geometry_operations(self) -> None:
        source = (
            ROOT / "tools" / "siroino_heather_closed_components_v27.py"
        ).read_text(encoding="utf-8")
        for token in (
            'DESIGN_REVISION = "v27-closed-saddle-sleevecap-folded-hood"',
            "class PolarBodyProfile",
            "HEIGHT_SAMPLES = 50",
            "ANGLE_COUNT = 72",
            "BVHTree.FromPolygons",
            "_enforce_clearance",
            '"bodyTopologyCopied": False',
            '"pelvicSaddleColumns": 11',
            '"authorsImplementationExecuted": False',
            '"authorsCodeCopied": False',
            "pattern.create_outfit = lambda",
        ):
            self.assertIn(token, source)
        self.assertNotIn("_selected_polygons", source)

    def test_job_and_construction_track_closed_component_trial(self) -> None:
        config_root = ROOT / "config" / "products" / PRODUCT
        job = json.loads((config_root / "job.json").read_text(encoding="utf-8"))
        construction = json.loads(
            (config_root / "construction.json").read_text(encoding="utf-8")
        )
        self.assertEqual(job["buildRevision"], REVISION)
        self.assertEqual(construction["designRevision"], REVISION)
        self.assertIn("eleven-column-pelvic-saddle", construction["panels"])
        self.assertIn(
            "bounded-post-topology-body-clearance-projection",
            construction["panels"],
        )
        self.assertIn(
            "applied only after garment-native topology is constructed",
            construction["researchTrial"]["implementation"],
        )
        evidence = (
            f"Assets/GenWorks/{PRODUCT}/Research/closed-components-clearance-trial.json"
        )
        self.assertEqual(construction["researchTrial"]["generatedEvidence"], evidence)
        self.assertIn(evidence, job["deliveryAssets"])
        self.assertIn(
            f"Assets/GenWorks/{PRODUCT}/Research/side-aware-taubin-shell-trial.json",
            job["deliveryAssets"],
        )
        self.assertEqual(
            job["researchMethod"]["currentReference"]["paperUrl"],
            "https://arxiv.org/abs/2606.24564",
        )


if __name__ == "__main__":
    unittest.main()
