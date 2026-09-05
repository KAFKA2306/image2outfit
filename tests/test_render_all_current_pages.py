from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
MODULE_PATH = TOOLS / "render_all_current.py"
SPEC = importlib.util.spec_from_file_location("render_all_current_pages", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class IoPagesGalleryTests(unittest.TestCase):
    def test_visual_fail_and_rejected_evidence_are_still_published_as_webp(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            site = root / "_site"
            current = root / "Assets" / "GenWorks" / "working"
            rejected = root / "Assets" / "GenWorks" / "rejected"
            (current / "Previews").mkdir(parents=True)
            (rejected / "Evidence" / "Rejected" / "run-2" / "Previews").mkdir(
                parents=True
            )

            (current / "ProductManifest.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "productId": "working",
                        "status": "WORKING",
                        "productRoot": "Assets/GenWorks/working",
                        "technicalGates": {"visualAppearanceReview": "FAIL"},
                    }
                ),
                encoding="utf-8",
            )
            Image.new("RGB", (8, 8)).save(current / "Previews" / "front.png")

            (rejected / "ProductManifest.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "productId": "rejected",
                        "status": "REJECTED",
                        "productRoot": "Assets/GenWorks/rejected",
                        "technicalGates": {"visualAppearanceReview": "FAIL"},
                    }
                ),
                encoding="utf-8",
            )
            Image.new("RGB", (8, 8)).save(
                rejected / "Evidence" / "Rejected" / "run-2" / "Previews" / "front.png"
            )

            previous_root = MODULE.ROOT
            try:
                MODULE.ROOT = root
                catalog = MODULE.build_io_gallery(site)
            finally:
                MODULE.ROOT = previous_root

            self.assertEqual(catalog["productCount"], 2)
            self.assertEqual(catalog["webpCount"], 2)
            by_id = {item["productId"]: item for item in catalog["products"]}
            self.assertEqual(by_id["working"]["state"], "WORKING")
            self.assertEqual(by_id["working"]["visualAppearanceReview"], "FAIL")
            self.assertEqual(by_id["rejected"]["state"], "REJECTED")
            self.assertEqual(by_id["rejected"]["sourceKind"], "rejected-preview")
            for product in catalog["products"]:
                self.assertEqual(product["webpCount"], 1)
                asset = product["assets"][0]
                self.assertTrue(asset["href"].endswith(".webp"))
                self.assertTrue((site / asset["href"]).is_file())

            html = (site / "io" / "index.html").read_text(encoding="utf-8")
            self.assertIn("visualAppearanceReview=FAIL", html)
            self.assertIn("working/front.webp", html)
            self.assertIn("rejected/front.webp", html)


    def test_skipped_product_preserves_existing_preview_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            product = root / "Assets" / "GenWorks" / "manual"
            previews = product / "Previews"
            job_path = root / "config" / "products" / "manual" / "job.json"
            previews.mkdir(parents=True)
            job_path.parent.mkdir(parents=True)
            (product / "ProductManifest.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "productId": "manual",
                        "status": "REJECTED",
                        "productRoot": "Assets/GenWorks/manual",
                    }
                ),
                encoding="utf-8",
            )
            job_path.write_text(
                json.dumps(
                    {
                        "id": "manual",
                        "productRoot": "Assets/GenWorks/manual",
                    }
                ),
                encoding="utf-8",
            )
            Image.new("RGB", (8, 8)).save(previews / "front.png")

            previous_root = MODULE.ROOT
            try:
                MODULE.ROOT = root
                resolution = SimpleNamespace(
                    environment={"SKIP_PRODUCT_BUILD": "true"},
                    reason="manual-recovery",
                )
                with mock.patch.object(MODULE, "resolve", return_value=resolution):
                    result = MODULE.render_one("unused-blender", job_path)
            finally:
                MODULE.ROOT = previous_root

            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["stage"], "preserve")
            self.assertTrue((previews / "front.png").is_file())
            self.assertIn("preserved 1 current-preview images", result["detail"])


    def test_pages_workflow_requires_webp_for_every_canonical_product(self) -> None:
        workflow = (
            ROOT / ".github" / "workflows" / "render-all-current.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("io products without WebP previews", workflow)
        self.assertIn("io catalog product count mismatch", workflow)
        self.assertIn("Path('config/products').glob('*/job.json')", workflow)

    def test_bordeaux_has_reproducible_hosted_render_entrypoint(self) -> None:
        job = json.loads(
            (
                ROOT
                / "config"
                / "products"
                / "haolan-bordeaux-knit-set"
                / "job.json"
            ).read_text(encoding="utf-8")
        )
        self.assertTrue(job["automaticBuild"])
        self.assertEqual(
            job["buildScript"],
            "tools/build_haolan_bordeaux_knit_set.py",
        )
        self.assertNotIn("hostedPoseScript", job)
        for relative in (
            "config/products/haolan-bordeaux-knit-set/skeleton.json",
            "tools/build_haolan_bordeaux_knit_set.py",
            "tools/haolan_knit_build.py",
            "tools/render_haolan_candidate_poses.py",
            "tools/render_haolan_candidate_turnaround.py",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
