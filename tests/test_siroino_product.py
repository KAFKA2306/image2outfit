from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = "siroino-heather-hooded-bodysuit"
REVISION = "v27-closed-saddle-sleevecap-folded-hood"
PROBE_PATH = ROOT / "tools" / "siroino_heather_geometry_probe.py"
POSE_PROBE_PATH = ROOT / "tools" / "siroino_heather_hooded_bodysuit_pose_probe.py"
JOB_PATH = ROOT / "config" / "products" / PRODUCT / "job.json"


class SiroinoGeometryProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probe = PROBE_PATH.read_text(encoding="utf-8")
        cls.pose_probe = POSE_PROBE_PATH.read_text(encoding="utf-8")
        cls.job = json.loads(JOB_PATH.read_text(encoding="utf-8"))
        cls.tree = ast.parse(cls.probe, filename=str(PROBE_PATH))

    def test_job_runs_probe_and_delivers_diagnostics(self) -> None:
        self.assertEqual(
            self.job["hostedPoseScript"],
            "tools/siroino_heather_hooded_bodysuit_pose_probe.py",
        )
        self.assertIn(
            "Assets/GenWorks/siroino-heather-hooded-bodysuit/Tests/geometry-diagnostics.json",
            self.job["deliveryAssets"],
        )

    def test_probe_reuses_exact_bvh_overlap_pairs(self) -> None:
        self.assertIn("body_tree.overlap(tree)", self.pose_probe)
        self.assertIn("probe.overlap_diagnostics", self.pose_probe)
        self.assertIn("Root-local evaluated polygon centers", self.pose_probe)

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
