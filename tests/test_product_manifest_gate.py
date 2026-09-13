from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import product_manifest_gate  # noqa: E402


class ProductManifestGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.product_root = self.root / "Assets" / "GenWorks" / "demo"
        self.product_root.mkdir(parents=True)
        for relative in (
            "Source/demo.blend",
            "Models/demo.fbx",
            "Prefab/demo.prefab",
            "Previews/demo-multiview.webp",
            "Previews/demo-pose.webp",
            "Tests/visual-review.json",
        ):
            path = self.product_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("evidence", encoding="utf-8")
        self.policy = {
            "completionStatus": "COMPLETE",
            "requiredCompletionGates": [
                "blender",
                "editableSource",
                "fbx",
                "prefabDeclared",
                "fiveViewEvidence",
                "poseEvidence",
                "visualAppearanceReview",
            ],
            "outOfScopeGates": ["unityImport", "vrchatRuntime"],
        }
        self.manifest = {
            "productId": "demo",
            "productRoot": "Assets/GenWorks/demo",
            "technicalGates": {
                "blender": "PASS",
                "editableSource": "PASS",
                "fbx": "PASS",
                "prefabDeclared": "PASS",
                "fiveViewEvidence": "PASS",
                "poseEvidence": "PASS",
                "visualAppearanceReview": "PASS",
                "unityImport": "FAIL",
            },
            "outputs": {
                "blend": "Assets/GenWorks/demo/Source/demo.blend",
                "fbx": "Assets/GenWorks/demo/Models/demo.fbx",
                "prefab": "Assets/GenWorks/demo/Prefab/demo.prefab",
                "multiview": "Assets/GenWorks/demo/Previews/demo-multiview.webp",
                "poseReview": "Assets/GenWorks/demo/Previews/demo-pose.webp",
            },
            "visualAppearanceReview": {
                "result": "PASS",
                "evidence": {"review": "Tests/visual-review.json"},
            },
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_all_required_pass_with_evidence_is_complete(self) -> None:
        result = product_manifest_gate.evaluate_manifest(
            self.manifest, self.policy, self.root
        )
        self.assertEqual("PASS", result["gateStatus"])
        self.assertEqual("COMPLETE", result["completionStatus"])
        self.assertEqual(
            ["unityImport", "vrchatRuntime"], result["outOfScopeGates"]
        )

    def test_missing_required_evidence_is_unverified(self) -> None:
        (self.product_root / "Previews" / "demo-pose.webp").unlink()
        result = product_manifest_gate.evaluate_manifest(
            self.manifest, self.policy, self.root
        )
        self.assertEqual("UNVERIFIED", result["gateStatus"])
        pose = next(item for item in result["requiredGates"] if item["id"] == "poseEvidence")
        self.assertEqual("UNVERIFIED", pose["status"])
        self.assertIsNone(result["completionStatus"])

    def test_explicit_required_fail_is_fail(self) -> None:
        manifest = json.loads(json.dumps(self.manifest))
        manifest["visualAppearanceReview"]["result"] = "FAIL"
        result = product_manifest_gate.evaluate_manifest(manifest, self.policy, self.root)
        self.assertEqual("FAIL", result["gateStatus"])
        self.assertIsNone(result["completionStatus"])

    def test_missing_required_gate_is_unverified(self) -> None:
        manifest = json.loads(json.dumps(self.manifest))
        del manifest["technicalGates"]["fbx"]
        result = product_manifest_gate.evaluate_manifest(manifest, self.policy, self.root)
        self.assertEqual("UNVERIFIED", result["gateStatus"])


if __name__ == "__main__":
    unittest.main()
