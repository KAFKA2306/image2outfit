from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "siroino-nocturne-angel-set"
CONFIG = ROOT / "config" / "products" / PRODUCT_ID
PRODUCT = ROOT / "Assets" / "GenWorks" / PRODUCT_ID
SCRIPT = ROOT / "tools" / "siroino_nocturne_angel_set.py"
POSE_SCRIPT = ROOT / "tools" / "siroino_nocturne_angel_pose.py"
GEOMETRY = ROOT / "tools" / "siroino_nocturne_geometry.py"
MODULES = ROOT / "tools" / "siroino_nocturne_modules.py"
RECORDS = ROOT / "tools" / "siroino_nocturne_records.py"
REVISION = "v5-skinweighted-pleated-volume"


def generator_source() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in (SCRIPT, GEOMETRY, MODULES, RECORDS)
    )


class NocturneAngelSetContractTest(unittest.TestCase):
    def test_job_uses_stable_canonical_entrypoints(self) -> None:
        job = json.loads((CONFIG / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(job["schemaVersion"], 2)
        self.assertEqual(job["id"], PRODUCT_ID)
        self.assertEqual(job["productRoot"], f"Assets/GenWorks/{PRODUCT_ID}")
        self.assertEqual(job["buildRevision"], REVISION)
        self.assertEqual(job["renderLoopRevision"], "nocturne-angel-loop-v5")
        self.assertEqual(job["buildScript"], "tools/siroino_nocturne_angel_set.py")
        self.assertEqual(
            job["hostedPoseScript"], "tools/siroino_nocturne_angel_pose.py"
        )
        self.assertEqual(
            job["targetSourcePath"],
            "Assets/SiroinoWorks/SiroinoSotai/FBX/SiroinoSotai_PC.fbx",
        )
        for path in (SCRIPT, POSE_SCRIPT, GEOMETRY, MODULES, RECORDS):
            self.assertTrue(path.is_file())

    def test_construction_is_explicit_loose_layered(self) -> None:
        construction = json.loads(
            (CONFIG / "construction.json").read_text(encoding="utf-8")
        )
        self.assertEqual(construction["profile"], "loose-layered")
        self.assertEqual(construction["designRevision"], REVISION)
        joined = " ".join(construction["panels"] + construction["separateGeometry"])
        for required in ("pleated skirt", "sailor collar", "wing", "beret"):
            self.assertIn(required, joined)

    def test_reference_is_hash_bound_but_not_redistributed(self) -> None:
        reference = json.loads((CONFIG / "reference.json").read_text(encoding="utf-8"))
        self.assertEqual(
            reference["sha256"],
            "a4a15a6fc6b7290af41dbc82b5fc55e7ab74370c33018816fd829d8307629f67",
        )
        self.assertEqual(reference["dimensions"], [2048, 1229])
        self.assertFalse(reference["sourceImageRedistributed"])

    def test_generator_uses_real_cloth_and_does_not_copy_body_topology(self) -> None:
        source = generator_source()
        for required in (
            '"CLOTH"',
            "vertex_group_mass",
            "use_self_collision",
            "evaluated_get",
            '"bodyTopologyCopied": False',
            "maxBoneInfluences",
        ):
            self.assertIn(required, source)
        self.assertNotIn("base.extract_surface", source)
        self.assertNotIn("body.data.polygons", source)

    def test_generator_cleans_exact_loop_triangle_degeneracy(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        for required in (
            "_remove_degenerate_polygons",
            "mesh.calc_loop_triangles()",
            "triangle.polygon_index",
            "removedDegeneratePolygons",
            "degenerateCleanupByObject",
        ):
            self.assertIn(required, source)
        self.assertIn('metrics.get("degenerateTriangles", 0) == 0', source)

    def test_v5_uses_evaluated_weight_transfer_and_shape_preserving_cloth(self) -> None:
        source = generator_source()
        for required in (
            "transfer_weights",
            "evaluated.to_mesh()",
            "pleated_shell",
            'cloth.settings.effector_weights.gravity = 0.18',
            '"shapePreservingStiffness": True',
            "ellipsoid_between",
            "maximum_search=height * 0.060",
        ):
            self.assertIn(required, source)
        self.assertNotIn("semantic_weights", source)
        self.assertNotIn("_lower_body_weights", source)

    def test_v5_preserves_named_modules_and_rejection_history(self) -> None:
        source = generator_source()
        for object_name in (
            "Nocturne_Bodice_Front_L",
            "Nocturne_Bodice_Front_R",
            "Nocturne_Bodice_Back",
            "Nocturne_Bodice_Side_L",
            "Nocturne_Bodice_Side_R",
            "Nocturne_Cloth_Skirt",
            "Nocturne_Beret",
            "Nocturne_Wing_",
            "Nocturne_Tail",
            "Nocturne_Leg_Warmer_",
            "Nocturne_Shoe_",
        ):
            self.assertIn(object_name, source)
        self.assertNotIn("Nocturne_Cropped_Bodice", source)
        self.assertTrue((PRODUCT / "Tests" / "visual-review-v4.json").is_file())
        self.assertIn('"v4-clearance-articulated-silhouette"', source)


if __name__ == "__main__":
    unittest.main()
