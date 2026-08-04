from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "tools" / "siroino_heather_pattern_coordinate_v24.py"
ENTRYPOINT = ROOT / "tools" / "siroino_heather_pattern_coordinate_product.py"
JOB = ROOT / "config" / "products" / "siroino-heather-hooded-bodysuit" / "job.json"
CONSTRUCTION = JOB.with_name("construction.json")


class PatternCoordinateV24Tests(unittest.TestCase):
    def test_job_and_construction_select_v24(self) -> None:
        job = json.loads(JOB.read_text(encoding="utf-8"))
        construction = json.loads(CONSTRUCTION.read_text(encoding="utf-8"))
        self.assertEqual(job["buildRevision"], "v24-pattern-coordinate-highcut-shell")
        self.assertEqual(construction["designRevision"], job["buildRevision"])
        self.assertEqual(
            job["buildScript"],
            "tools/siroino_heather_pattern_coordinate_product.py",
        )
        self.assertIn(
            "Assets/GenWorks/siroino-heather-hooded-bodysuit/Research/pattern-coordinate-trial.json",
            job["deliveryAssets"],
        )

    def test_trial_is_an_executed_bounded_geometry_operation(self) -> None:
        source = MODULE.read_text(encoding="utf-8")
        self.assertIn("Spatio-Temporal Garment Reconstruction", source)
        self.assertIn('"status": "EXECUTED"', source)
        self.assertIn("0.555 <= z < 0.640", source)
        self.assertIn("abs(center.y) <= 0.105", source)
        self.assertIn("arm_weight >= 0.030", source)
        self.assertIn("pattern._body_shell_predicate", source)

    def test_entrypoint_installs_v24_after_existing_fitting(self) -> None:
        source = ENTRYPOINT.read_text(encoding="utf-8")
        self.assertIn("import siroino_heather_hooded_product as product", source)
        self.assertIn("v24.install(product.pattern)", source)
        self.assertIn("return product.main()", source)


if __name__ == "__main__":
    unittest.main()
