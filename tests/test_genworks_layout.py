from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import audit_genworks_layout


CONFIG = {
    "schemaVersion": 1,
    "canonicalRoot": "Assets/GenWorks",
    "productRoot": "Assets/GenWorks",
    "manifestName": "ProductManifest.json",
    "requiredProductDirectories": [
        "Models",
        "Textures",
        "Materials",
        "Prefab",
        "Previews",
        "Documentation",
    ],
    "assetPathFields": [
        "outfitPrefabPath",
        "integratedPrefabPath",
        "previewPath",
        "documentationPath",
    ],
    "productionExtensions": [".fbx", ".prefab", ".mat", ".png", ".cs"],
    "allowedExternalAssetRoots": [
        "Assets/_Local",
        "Assets/_Vendor",
        "Assets/SiroinoWorks",
    ],
    "forbiddenAssetRoots": ["Assets/Editor"],
}


class GenWorksLayoutTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "config").mkdir(parents=True)
        (self.root / "Assets" / "GenWorks").mkdir(parents=True)
        (self.root / "config" / "genworks-layout.json").write_text(
            json.dumps(CONFIG), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_valid_product_manifest_passes(self) -> None:
        product = self.root / "Assets" / "GenWorks" / "test-outfit"
        for name in CONFIG["requiredProductDirectories"]:
            (product / name).mkdir(parents=True)
        prefab = product / "Prefab" / "Outfit.prefab"
        preview = product / "Previews" / "front.png"
        readme = product / "Documentation" / "README.md"
        for file in (prefab, preview, readme):
            file.write_text("test", encoding="utf-8")
        (product / "ProductManifest.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "productId": "test-outfit",
                    "productRoot": "Assets/GenWorks/test-outfit",
                    "outfitPrefabPath": "Assets/GenWorks/test-outfit/Prefab/Outfit.prefab",
                    "previewPath": "Assets/GenWorks/test-outfit/Previews/front.png",
                    "documentationPath": "Assets/GenWorks/test-outfit/Documentation/README.md",
                }
            ),
            encoding="utf-8",
        )
        result = audit_genworks_layout.audit(
            self.root, self.root / "config" / "genworks-layout.json"
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["products"], 1)

    def test_manifest_cannot_reference_another_product(self) -> None:
        product = self.root / "Assets" / "GenWorks" / "one"
        product.mkdir(parents=True)
        outside = self.root / "Assets" / "GenWorks" / "two" / "Outfit.prefab"
        outside.parent.mkdir(parents=True)
        outside.write_text("test", encoding="utf-8")
        (product / "ProductManifest.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "productId": "one",
                    "productRoot": "Assets/GenWorks/one",
                    "outfitPrefabPath": "Assets/GenWorks/two/Outfit.prefab",
                }
            ),
            encoding="utf-8",
        )
        result = audit_genworks_layout.audit(
            self.root, self.root / "config" / "genworks-layout.json"
        )
        self.assertFalse(result["passed"])
        self.assertTrue(
            any(item["code"] == "asset-outside-product" for item in result["findings"])
        )

    def test_root_editor_folder_is_forbidden(self) -> None:
        editor = self.root / "Assets" / "Editor"
        editor.mkdir(parents=True)
        (editor / "OldTool.cs").write_text("class OldTool {}", encoding="utf-8")
        result = audit_genworks_layout.audit(
            self.root, self.root / "config" / "genworks-layout.json"
        )
        self.assertFalse(result["passed"])
        self.assertTrue(
            any(
                item["code"] == "forbidden-asset-root"
                and item["path"] == "Assets/Editor/OldTool.cs"
                for item in result["findings"]
            )
        )


if __name__ == "__main__":
    unittest.main()
