from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import avatar_workflow  # noqa: E402


class AvatarWorkflowTests(unittest.TestCase):
    def test_project_workflow_has_eleven_separate_outfits(self) -> None:
        config = avatar_workflow._load_config(ROOT)
        self.assertEqual(len(config["outfits"]), 11)
        self.assertEqual(
            len({item["id"] for item in config["outfits"]}),
            11,
        )
        self.assertEqual(
            config["scenes"]["workbench"],
            "Assets/Scenes/Avatar/00_SiroinoOutfitWorkbench.unity",
        )
        self.assertEqual(config["sceneCapture"]["view"], "camera")
        self.assertEqual(
            config["sceneCapture"]["cameraPath"],
            "AvatarPreviewStage/PreviewCamera",
        )
        self.assertTrue(all(item.get("clothEvidence") for item in config["outfits"]))
        self.assertTrue(all(item.get("scene") for item in config["outfits"]))

    def test_project_preflight_passes_for_baked_upload_set(self) -> None:
        result = avatar_workflow.preflight(ROOT)
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["selectedOutfitCount"], 11)
        self.assertEqual(len(result["outfits"]), 11)
        self.assertFalse(result["errors"])
        self.assertTrue(
            all(item["sceneCapture"]["passed"] for item in result["outfits"])
        )

    def test_visual_regression_records_and_compares_baselines(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            visual_root = root / "visual"
            visual_root.mkdir(parents=True)
            Image.new("RGBA", (4, 4), (10, 20, 30, 255)).save(visual_root / "front.png")
            config = {
                "schemaVersion": 1,
                "workflowId": "test",
                "paths": {
                    "bakeRoot": "visual",
                    "cauRoot": "visual",
                    "runtimeRoot": ".image2outfit/avatar-workflow",
                    "ledger": ".image2outfit/avatar-workflow/upload-ledger.json",
                    "visualBaselineRoot": ".image2outfit/avatar-workflow/visual-baselines",
                },
                "visual": {
                    "requiredPaths": ["front.png"],
                    "warningMeanAbsoluteError": 0.03,
                },
                "outfits": [
                    {
                        "id": "test",
                        "name": "Test",
                        "productId": "test",
                        "prefab": "visual/front.png",
                        "cauSetting": "visual/front.png",
                        "visualRoot": "visual",
                    }
                ],
            }
            recorded = avatar_workflow.visual_regression(
                root, config=config, record_baseline=True
            )
            self.assertTrue(recorded["passed"])
            compared = avatar_workflow.visual_regression(root, config=config)
            self.assertTrue(compared["passed"])
            self.assertEqual(compared["results"][0]["status"], "PASS")

            Image.new("RGBA", (4, 4), (250, 240, 230, 255)).save(
                visual_root / "front.png"
            )
            changed = avatar_workflow.visual_regression(root, config=config)
            self.assertTrue(changed["passed"])
            self.assertEqual(changed["results"][0]["status"], "WARN")
            self.assertTrue(changed["visualIssuesAreNonBlocking"])

    def test_ledger_keeps_status_and_never_serializes_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {
                "schemaVersion": 1,
                "workflowId": "test",
                "paths": {
                    "bakeRoot": "visual",
                    "cauRoot": "visual",
                    "runtimeRoot": ".image2outfit/avatar-workflow",
                    "ledger": ".image2outfit/avatar-workflow/upload-ledger.json",
                    "visualBaselineRoot": ".image2outfit/avatar-workflow/visual-baselines",
                },
                "visual": {
                    "requiredPaths": ["front.png"],
                    "warningMeanAbsoluteError": 0.03,
                },
                "outfits": [
                    {
                        "id": "test",
                        "name": "Test",
                        "productId": "test",
                        "prefab": "visual/front.png",
                        "cauSetting": "visual/front.png",
                        "visualRoot": "visual",
                    }
                ],
            }
            (root / "visual").mkdir()
            (root / "visual" / "front.png").write_bytes(b"test")
            (root / "visual" / "front.png.meta").write_text("guid: " + "a" * 32 + "\n")
            value = avatar_workflow.record_ledger(
                root,
                config=config,
                outfit_id="test",
                status="SUCCEEDED",
                blueprint_id="avtr_test",
            )
            ledger_text = (root / config["paths"]["ledger"]).read_text()
            self.assertEqual(value["outfits"][0]["status"], "SUCCEEDED")
            self.assertFalse(value["credentialsStored"])
            self.assertNotIn("password", ledger_text.lower())
            json.loads(ledger_text)


if __name__ == "__main__":
    unittest.main()
