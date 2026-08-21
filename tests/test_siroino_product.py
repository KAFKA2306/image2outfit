from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = "siroino-heather-hooded-bodysuit"
REVISION = "v29-smoothed-clearance-tapered-yoke-fitted-sleeve"
PRODUCT_SCRIPT = ROOT / "tools" / "siroino_heather_hooded_product.py"
V29_PATH = ROOT / "tools" / "siroino_heather_manifold_yoke_v29.py"
PROBE_PATH = ROOT / "tools" / "siroino_heather_geometry_probe.py"
POSE_PROBE_PATH = ROOT / "tools" / "siroino_heather_hooded_bodysuit_pose_probe.py"
FUSED_POSE_PATH = ROOT / "tools" / "siroino_heather_hooded_fused_pose_probe.py"
CONFIG_ROOT = ROOT / "config" / "products" / PRODUCT
JOB_PATH = CONFIG_ROOT / "job.json"
CONSTRUCTION_PATH = CONFIG_ROOT / "construction.json"


class SiroinoGeometryProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probe = PROBE_PATH.read_text(encoding="utf-8")
        cls.pose_probe = POSE_PROBE_PATH.read_text(encoding="utf-8")
        cls.fused_pose = FUSED_POSE_PATH.read_text(encoding="utf-8")
        cls.job = json.loads(JOB_PATH.read_text(encoding="utf-8"))
        cls.tree = ast.parse(cls.probe, filename=str(PROBE_PATH))

    def test_job_uses_fused_probe_and_delivers_diagnostics(self) -> None:
        self.assertEqual(
            self.job["hostedPoseScript"],
            "tools/siroino_heather_hooded_fused_pose_probe.py",
        )
        self.assertIn(
            f"Assets/GenWorks/{PRODUCT}/Tests/geometry-diagnostics.json",
            self.job["deliveryAssets"],
        )

    def test_fused_probe_delegates_to_audited_probe_with_wider_frame(self) -> None:
        for fragment in (
            "import siroino_heather_hooded_bodysuit_pose_probe as probe",
            "camera.data.ortho_scale *= 1.24",
            "return probe.main()",
        ):
            self.assertIn(fragment, self.fused_pose)

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


class SiroinoV29GeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.product = PRODUCT_SCRIPT.read_text(encoding="utf-8")
        cls.source = V29_PATH.read_text(encoding="utf-8")
        cls.job = json.loads(JOB_PATH.read_text(encoding="utf-8"))
        cls.construction = json.loads(CONSTRUCTION_PATH.read_text(encoding="utf-8"))

    def test_product_installs_current_v29_geometry(self) -> None:
        self.assertIn(
            "import siroino_heather_manifold_yoke_v29 as manifold_yoke",
            self.product,
        )
        self.assertIn("manifold_yoke.install(pattern)", self.product)
        self.assertIn("DESIGN_REVISION = manifold_yoke.DESIGN_REVISION", self.product)

    def test_v29_uses_bounded_smoothed_clearance_and_parametric_components(
        self,
    ) -> None:
        for fragment in (
            f'DESIGN_REVISION = "{REVISION}"',
            "maximum_step: float = 0.012",
            "for _ in range(4):",
            "yoke_rings = 5",
            "offsets = tuple(range(-16, 17, 2))",
            "radius = 0.027 + 0.006",
            "rows = 6",
            'obj["bodyTopologyCopied"] = False',
            "pattern.create_outfit = lambda",
        ):
            self.assertIn(fragment, self.source)

    def test_job_and_construction_track_current_revision(self) -> None:
        self.assertEqual(self.job["buildRevision"], REVISION)
        self.assertEqual(self.construction["designRevision"], REVISION)
        panels = set(self.construction["panels"])
        for panel in (
            "five-ring-tapered-shoulder-yoke-and-fitted-neck",
            "seventeen-column-four-millimetre-sag-pelvic-saddle",
            "small-root-fitted-sleeve-caps",
            "compact-six-row-rear-neck-folded-hood",
            "four-iteration-smoothed-bounded-clearance-projection",
            "no-body-topology-copy-no-body-face-region-selection",
        ):
            self.assertIn(panel, panels)

        evidence = (
            f"Assets/GenWorks/{PRODUCT}/Research/smoothed-clearance-yoke-trial.json"
        )
        self.assertEqual(
            self.construction["researchTrial"]["generatedEvidence"], evidence
        )
        self.assertIn(evidence, self.job["deliveryAssets"])
        self.assertEqual(
            self.job["researchMethod"]["currentReference"]["paperUrl"],
            "https://arxiv.org/abs/2606.24564",
        )
        self.assertFalse(self.job["researchMethod"]["authorsImplementationExecuted"])
        self.assertFalse(self.job["researchMethod"]["authorsCodeCopied"])

    def test_superseded_visual_revisions_remain_rejection_history(self) -> None:
        for revision in (
            "v27-closed-saddle-sleevecap-folded-hood",
            "v28-flat-saddle-contoured-cap-hood-roll",
        ):
            self.assertIn(revision, self.product)
        self.assertIn("VISUAL", self.product.upper())

    def test_v29_primary_representation_is_reported_by_validation(self) -> None:
        for fragment in (
            'result["pelvicSaddleColumns"] = 17',
            'result["taperedYokeRings"] = 5',
            'result["clearanceDisplacementSmoothing"] = 4',
            "polar torso with tapered yoke, shallow saddle, fitted sleeves and compact hood",
        ):
            self.assertIn(fragment, self.source)


if __name__ == "__main__":
    unittest.main()
