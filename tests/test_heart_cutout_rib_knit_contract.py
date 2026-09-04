from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "siroino-heart-cutout-rib-knit-dress"
PRODUCT_CONFIG = ROOT / "config" / "products" / PRODUCT_ID
PRODUCT_ROOT = ROOT / "Assets" / "GenWorks" / PRODUCT_ID


class HeartCutoutRibKnitContractTests(unittest.TestCase):
    def test_reference_is_hash_bound_without_redistribution(self) -> None:
        license_record = json.loads(
            (PRODUCT_CONFIG / "license.json").read_text(encoding="utf-8")
        )
        reference = license_record["referenceImage"]
        self.assertEqual(
            reference["sha256"],
            "e7b267d6aa9b9143fb645f85266cb81beb02f09eb4443c1f9c81bfee4daf88d3",
        )
        self.assertFalse(reference["committedToRepository"])
        self.assertFalse(any(PRODUCT_CONFIG.glob("*.png")))
        self.assertFalse(any(PRODUCT_CONFIG.glob("*.jpg")))
        self.assertFalse(any(PRODUCT_CONFIG.glob("*.webp")))

    def test_job_uses_canonical_product_namespace(self) -> None:
        job = json.loads((PRODUCT_CONFIG / "job.json").read_text(encoding="utf-8"))
        root = f"Assets/GenWorks/{PRODUCT_ID}"
        self.assertEqual(job["id"], PRODUCT_ID)
        self.assertEqual(job["productRoot"], root)
        self.assertEqual(job["productManifestPath"], f"{root}/ProductManifest.json")
        self.assertEqual(
            job["buildScript"], "tools/siroino_heart_cutout_rib_knit_dress.py"
        )
        self.assertEqual(
            job["hostedPoseScript"], "tools/siroino_required_pose_render_entry.py"
        )
        self.assertTrue((ROOT / job["buildScript"]).is_file())

    def test_required_pose_sheet_is_product_scoped(self) -> None:
        source = (ROOT / "tools" / "siroino_required_pose_render.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('f"{job[\'id\']}-pose-review.webp"', source)
        self.assertNotIn("siroino-wide-cargo-pose-review.webp", source)

    def test_manifest_starts_working_without_false_visual_pass(self) -> None:
        manifest = json.loads(
            (PRODUCT_ROOT / "ProductManifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["status"], "WORKING")
        self.assertEqual(
            manifest["technicalGates"]["visualAppearanceReview"], "PENDING"
        )


if __name__ == "__main__":
    unittest.main()
