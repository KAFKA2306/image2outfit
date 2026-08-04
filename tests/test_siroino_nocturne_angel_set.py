from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "siroino-nocturne-angel-set"
CONFIG = ROOT / "config" / "products" / PRODUCT_ID
SCRIPT = ROOT / "tools" / "siroino_nocturne_angel_set.py"
POSE_SCRIPT = ROOT / "tools" / "siroino_nocturne_angel_pose.py"
GEOMETRY = ROOT / "tools" / "siroino_nocturne_geometry.py"
MODULES = ROOT / "tools" / "siroino_nocturne_modules.py"
RECORDS = ROOT / "tools" / "siroino_nocturne_records.py"


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
        joined = " ".join(construction["panels"] + construction["separateGeometry"])
        for required in ("skirt", "sailor collar", "wings", "beret", "leg warmers"):
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
            "transfer_weights",
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
        self.assertIn("metrics.get(\"degenerateTriangles\", 0) == 0", source)

    def test_v3_uses_sewn_bodice_panels_and_stable_modules(self) -> None:
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
        self.assertIn("_rounded_feather", source)
        self.assertIn('(skirt, "hips")', source)
        self.assertIn("(shoe, foot)", source)
        self.assertNotIn("Nocturne_Cropped_Bodice", source)


if __name__ == "__main__":
    unittest.main()
