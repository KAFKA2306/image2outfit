from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = "siroino-heather-hooded-bodysuit"
PROBE_PATH = ROOT / "tools" / "siroino_heather_geometry_probe.py"
POSE_PROBE_PATH = ROOT / "tools" / "siroino_heather_hooded_fused_pose_probe.py"
POSE_PROBE_IMPL_PATH = (
    ROOT / "tools" / "siroino_heather_hooded_bodysuit_pose_probe.py"
)
JOB_PATH = ROOT / "config" / "products" / PRODUCT / "job.json"


class SiroinoGeometryProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probe = PROBE_PATH.read_text(encoding="utf-8")
        cls.pose_probe = POSE_PROBE_PATH.read_text(encoding="utf-8")
        cls.pose_probe_impl = POSE_PROBE_IMPL_PATH.read_text(encoding="utf-8")
        cls.job = json.loads(JOB_PATH.read_text(encoding="utf-8"))
        cls.tree = ast.parse(cls.probe, filename=str(PROBE_PATH))

    def test_job_runs_probe_and_delivers_diagnostics(self) -> None:
        self.assertEqual(
            self.job["hostedPoseScript"],
            "tools/siroino_heather_hooded_fused_pose_probe.py",
        )
        self.assertIn(
            "Assets/GenWorks/siroino-heather-hooded-bodysuit/Tests/geometry-diagnostics.json",
            self.job["deliveryAssets"],
        )

    def test_fused_probe_delegates_to_measured_pose_probe(self) -> None:
        self.assertIn(
            "import siroino_heather_hooded_bodysuit_pose_probe as probe",
            self.pose_probe,
        )
        self.assertIn("return probe.main()", self.pose_probe)

    def test_pose_probe_reuses_exact_bvh_overlap_pairs(self) -> None:
        self.assertIn("body_tree.overlap(tree)", self.pose_probe_impl)
        self.assertIn("probe.overlap_diagnostics", self.pose_probe_impl)
        self.assertIn("Root-local evaluated polygon centers", self.pose_probe_impl)

    def test_probe_records_spatial_and_weight_evidence(self) -> None:
        for fragment in (
            "VOXEL_M = 0.05",
            "rootLocalBounds",
            "rootLocalQuantiles",
            "dominantGroupPairs",
            "topVoxels",
            "topWeights",
            "boundaryLoops",
        ):
            self.assertIn(fragment, self.probe)

    def test_probe_clears_temporary_evaluated_mesh(self) -> None:
        self.assertIn("evaluated.to_mesh_clear()", self.probe)

    def test_probe_has_no_internal_repository_imports(self) -> None:
        imported = {
            alias.name
            for node in self.tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertFalse(any(name.startswith("siroino_") for name in imported))


if __name__ == "__main__":
    unittest.main()
