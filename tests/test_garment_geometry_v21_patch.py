from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = ROOT / "tools" / "siroino_heather_hooded_v21_patch.py"
PRODUCT_PATH = ROOT / "tools" / "siroino_heather_hooded_product.py"
JOB_PATH = ROOT / "config" / "products" / "siroino-heather-hooded-bodysuit" / "job.json"


class GarmentGeometryV22BodyAnchorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.patch = PATCH_PATH.read_text(encoding="utf-8")
        cls.product = PRODUCT_PATH.read_text(encoding="utf-8")
        cls.job = json.loads(JOB_PATH.read_text(encoding="utf-8"))
        cls.tree = ast.parse(cls.patch, filename=str(PATCH_PATH))

    def test_active_product_installs_flat_patch(self) -> None:
        self.assertIn("import siroino_heather_hooded_v21_patch as v21", self.product)
        self.assertLess(
            self.product.index("v21.install(pattern)"),
            self.product.index("DESIGN_REVISION = pattern.DESIGN_REVISION"),
        )
        imports = {
            alias.name
            for node in self.tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertFalse(
            any(name.startswith("siroino_") for name in imports),
            "The flat patch must not add another internal import level",
        )

    def test_job_declares_v22_revision(self) -> None:
        self.assertEqual(
            self.job["buildRevision"],
            "v22-dama-inspired-body-anchored-shell",
        )
        self.assertEqual(
            self.job["buildScript"],
            "tools/siroino_heather_hooded_product.py",
        )

    def test_underbody_strip_reaches_below_v20_cutoff(self) -> None:
        self.assertIn("0.515 <= center.z <= 0.850", self.patch)
        self.assertIn("(z - 0.515) / (0.850 - 0.515)", self.patch)
        self.assertIn("0.024 + 0.141 * _smoothstep(t)", self.patch)

    def test_body_anchor_clearance_is_positive_and_bounded(self) -> None:
        self.assertIn("SHELL_CLEARANCE_M = 0.022", self.patch)
        self.assertIn("MIN_ANCHOR_OFFSET_M = 0.018", self.patch)
        self.assertIn("MAX_ANCHOR_OFFSET_M = 0.026", self.patch)
        self.assertIn("allOffsetsStrictlyPositive", self.patch)

    def test_body_anchor_representation_is_persisted(self) -> None:
        self.assertIn('"body_anchor_triangle"', self.patch)
        self.assertIn('"body_anchor_barycentric"', self.patch)
        self.assertIn('"body_anchor_offset_m"', self.patch)
        self.assertIn("BVHTree.FromPolygons", self.patch)
        self.assertIn("_barycentric_coordinates", self.patch)

    def test_offset_field_is_smoothed_without_raw_position_laplacian(self) -> None:
        self.assertIn("OFFSET_SMOOTH_FACTOR = 0.35", self.patch)
        self.assertIn("OFFSET_SMOOTH_ITERATIONS = 4", self.patch)
        self.assertIn("_smooth_offsets", self.patch)
        self.assertNotIn('shrinkwrap.wrap_method = "NEAREST_SURFACEPOINT"', self.patch)

    def test_research_trial_is_written_truthfully(self) -> None:
        self.assertIn('"status": "EXECUTED"', self.patch)
        self.assertIn('"authorsImplementationExecuted": False', self.patch)
        self.assertIn('"copiedFromOfficialCode": False', self.patch)
        self.assertIn("https://arxiv.org/abs/2605.21001", self.patch)
        self.assertIn("dama-body-anchor-trial.json", self.patch)

    def test_hood_roll_is_slim_and_body_clear(self) -> None:
        self.assertIn("0.074 + 0.012 * center_weight", self.patch)
        self.assertIn("0.0065", self.patch)
        self.assertIn("0.128 * lateral", self.patch)

    def test_v20_failure_is_preserved_as_evidence(self) -> None:
        self.assertIn('"v20-semantic-five-opening-highcut-shell"', self.product)
        self.assertIn("396 shell overlaps in crouch", self.product)
        self.assertIn("636 in sit", self.product)


if __name__ == "__main__":
    unittest.main()
