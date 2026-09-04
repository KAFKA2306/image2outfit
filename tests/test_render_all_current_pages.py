from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

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
    def test_visual_fail_and_rejected_evidence_are_still_published_as_webp(self) -> None:
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
                rejected
                / "Evidence"
                / "Rejected"
                / "run-2"
                / "Previews"
                / "front.png"
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


if __name__ == "__main__":
    unittest.main()
