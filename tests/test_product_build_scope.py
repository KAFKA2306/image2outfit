from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
TOOLS = PROJECT / "tools"
sys.path.insert(0, str(TOOLS))

import resolve_product_build_scope as scope


class ProductBuildScopeTest(unittest.TestCase):
    def _root(self, directory: str, *, automatic_build: bool = True) -> Path:
        root = Path(directory)
        (root / "config/products/demo").mkdir(parents=True)
        (root / "config/pipeline/requests").mkdir(parents=True)
        shutil.copy(PROJECT / "config/job.schema.v2.json", root / "config/job.schema.v2.json")
        shutil.copy(PROJECT / "config/toolchain-lock.json", root / "config/toolchain-lock.json")
        job = {
            "schemaVersion": 2,
            "id": "demo",
            "productName": "Demo",
            "adapterId": "demo-v1",
            "automaticBuild": automatic_build,
            "productRoot": "Assets/GenWorks/demo",
            "productManifestPath": "Assets/GenWorks/demo/ProductManifest.json",
            "buildScript": "tools/demo_build.py",
            "blendPath": "Assets/GenWorks/demo/Source/demo.blend",
            "fbxAssetPath": "Assets/GenWorks/demo/Models/demo.fbx",
            "prefabAssetPath": "Assets/GenWorks/demo/Prefab/demo.prefab",
            "integratedPrefabAssetPath": "Assets/GenWorks/demo/Prefab/demo-integrated.prefab",
            "targetAvatarAssetPath": "Assets/Avatar.prefab",
            "licenseEvidence": "config/products/demo/license.json",
            "privateSourceRoots": ["Assets/_Local"],
            "deliveryAssets": ["Assets/GenWorks/demo/ProductManifest.json"],
            "previewPaths": {
                name: f"Assets/GenWorks/demo/Previews/{name}.png"
                for name in ("front", "back", "left", "right", "three-quarter")
            },
            "humanEvidence": {
                name: f"Assets/_Local/Evidence/demo/{name}.json"
                for name in (
                    "visual-review",
                    "pose-penetration-review",
                    "vrchat-runtime-review",
                )
            },
        }
        (root / "config/products/demo/job.json").write_text(
            json.dumps(job), encoding="utf-8"
        )
        return root

    def test_job_and_request_for_same_product_collapse_to_one_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            selected, reason = scope.select_job(
                [
                    "config/products/demo/job.json",
                    "config/pipeline/requests/demo.json",
                ],
                root,
                include_pipeline_request=True,
            )
        self.assertEqual(selected, "config/products/demo/job.json")
        self.assertEqual(reason, "selected")

    def test_self_hosted_scope_does_not_infer_pipeline_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            selected, reason = scope.select_job(
                ["config/pipeline/requests/demo.json"],
                root,
                include_pipeline_request=False,
            )
        self.assertIsNone(selected)
        self.assertEqual(reason, "selected-product-jobs-0")

    def test_resolution_emits_one_environment_contract_for_both_runners(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            hosted = scope.resolve(
                root=root,
                explicit_job="config/products/demo/job.json",
                changed=[],
                materialize_job=False,
                include_pipeline_request=True,
            )
            self_hosted = scope.resolve(
                root=root,
                explicit_job="config/products/demo/job.json",
                changed=[],
                materialize_job=True,
                include_pipeline_request=False,
            )
        self.assertEqual(hosted.environment["JOB_ID"], "demo")
        self.assertEqual(hosted.environment["JOB_PATH"], "config/products/demo/job.json")
        self.assertEqual(
            self_hosted.environment["JOB_PATH"], "Assets/_Local/Jobs/demo/job.json"
        )
        self.assertEqual(hosted.environment["BLENDER_VERSION"], "4.4.3")
        self.assertEqual(
            hosted.environment["PRODUCT_ROOT"], self_hosted.environment["PRODUCT_ROOT"]
        )

    def test_manual_recovery_stays_skipped_on_self_hosted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory, automatic_build=False)
            result = scope.resolve(
                root=root,
                explicit_job="config/products/demo/job.json",
                changed=[],
                materialize_job=True,
                include_pipeline_request=False,
            )
        self.assertEqual(result.environment["SKIP_PRODUCT_BUILD"], "true")
        self.assertEqual(result.reason, "demo-manual-recovery")

    def test_workflows_delegate_scope_resolution(self) -> None:
        workflows = [
            PROJECT / ".github/workflows/build-product-hosted.yml",
            PROJECT / ".github/workflows/build-product-self-hosted.yml",
        ]
        for path in workflows:
            text = path.read_text(encoding="utf-8")
            self.assertEqual(text.count("tools/resolve_product_build_scope.py"), 1)
            self.assertNotIn("Only schemaVersion 2 jobs are accepted", text)
            self.assertNotIn("selected-product-jobs-", text)


if __name__ == "__main__":
    unittest.main()
