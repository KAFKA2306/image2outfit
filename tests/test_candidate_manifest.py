from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import candidate_manifest  # noqa: E402

POLICY = {
    "schemaVersion": 1,
    "minimumPreview": {
        "width": 1024,
        "height": 1024,
        "requiredViews": ["front", "back", "left", "right", "three-quarter"],
    },
    "requiredHumanEvidenceKinds": [
        "visual-review",
        "pose-penetration-review",
        "vrchat-runtime-review",
    ],
    "allowedDeliveryExtensions": [".fbx", ".prefab", ".png", ".json"],
}

REQUIRED_JOB_FIELDS = [
    "schemaVersion",
    "id",
    "productName",
    "adapterId",
    "buildScript",
    "blendPath",
    "fbxAssetPath",
    "prefabAssetPath",
    "integratedPrefabAssetPath",
    "targetAvatarAssetPath",
    "licenseEvidence",
    "privateSourceRoots",
    "deliveryAssets",
    "previewPaths",
    "humanEvidence",
]


class CandidateManifestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for directory in (
            "config",
            "tools",
            "Packages",
            "ProjectSettings",
            "Assets/GenWorks/Shared/Editor",
            "Assets/_Vendor/TestAvatar",
            "Assets/GenWorks/test-product/Models",
            "Assets/_Local/Evidence/test-product",
            ".image2outfit/products/test-product/reports",
        ):
            (self.root / directory).mkdir(parents=True, exist_ok=True)

        self.policy_path = self.root / "config/release-policy.json"
        self.schema_path = self.root / "config/job.schema.v2.json"
        self.unity_pipeline_path = (
            self.root / "Assets/GenWorks/Shared/Editor/Image2OutfitPipeline.cs"
        )
        self.write_json(self.policy_path, POLICY)
        self.write_json(
            self.schema_path,
            {
                "type": "object",
                "required": REQUIRED_JOB_FIELDS,
                "properties": {"schemaVersion": {"const": 2}},
            },
        )
        self.write_json(self.root / "config/toolchain-lock.json", {"schemaVersion": 1})
        (self.root / "pyproject.toml").write_text(
            '[project]\nname = "test"\nversion = "0.0.0"\n', encoding="utf-8"
        )
        self.write_json(self.root / "Packages/vpm-manifest.json", {})
        self.write_json(self.root / "Packages/manifest.json", {})
        (self.root / "ProjectSettings/ProjectVersion.txt").write_text(
            "m_EditorVersion: 2022.3.22f1\n", encoding="utf-8"
        )
        self.unity_pipeline_path.write_text("// test pipeline\n", encoding="utf-8")

        build_script = self.root / "tools/build.py"
        build_script.write_text("print('build')\n", encoding="utf-8")
        avatar = self.root / "Assets/_Vendor/TestAvatar/Avatar.prefab"
        avatar.write_text("private avatar", encoding="utf-8")
        avatar_source = self.root / "Assets/_Vendor/TestAvatar/Avatar.fbx"
        avatar_source.write_text("private source", encoding="utf-8")
        outfit_fbx = self.root / "Assets/GenWorks/test-product/Models/Outfit.fbx"
        outfit_fbx.write_text("outfit", encoding="utf-8")
        license_path = self.root / "Assets/_Local/Evidence/test-product/license.json"
        self.write_json(
            license_path,
            {
                "adapterId": "test-adapter-v1",
                "sourceUrl": "https://example.invalid/avatar",
                "checkedAt": "2026-08-02T00:00:00Z",
                "commercialOutfitAllowed": True,
                "avatarFilesRedistributed": False,
            },
        )
        evidence_root = "Assets/_Local/Evidence/test-product"
        self.job = {
            "schemaVersion": 2,
            "id": "test-product",
            "productName": "Test outfit",
            "adapterId": "test-adapter-v1",
            "buildScript": "tools/build.py",
            "blendPath": "Assets/GenWorks/test-product/Source/Outfit.blend",
            "fbxAssetPath": "Assets/GenWorks/test-product/Models/Outfit.fbx",
            "prefabAssetPath": "Assets/GenWorks/test-product/Prefab/Outfit.prefab",
            "integratedPrefabAssetPath": "Assets/GenWorks/test-product/Prefab/Outfit_avatar.prefab",
            "targetAvatarAssetPath": "Assets/_Vendor/TestAvatar/Avatar.prefab",
            "targetSourcePath": "Assets/_Vendor/TestAvatar/Avatar.fbx",
            "artifactDir": ".image2outfit/products/test-product/reports",
            "candidateDir": ".image2outfit/products/test-product/candidate",
            "releaseDir": ".image2outfit/products/test-product/release",
            "licenseEvidence": f"{evidence_root}/license.json",
            "privateSourceRoots": ["Assets/_Vendor/TestAvatar"],
            "deliveryAssets": ["Assets/GenWorks/test-product/Models/Outfit.fbx"],
            "previewPaths": {
                view: f"Assets/GenWorks/test-product/Previews/{view}.png"
                for view in POLICY["minimumPreview"]["requiredViews"]
            },
            "humanEvidence": {
                kind: f"{evidence_root}/{kind}.json"
                for kind in POLICY["requiredHumanEvidenceKinds"]
            },
        }
        self.job_path = self.root / ".image2outfit/products/test-product/job.json"
        self.write_json(self.job_path, self.job)
        self.patches = (
            patch.object(candidate_manifest, "ROOT", self.root),
            patch.object(candidate_manifest, "POLICY_PATH", self.policy_path),
            patch.object(candidate_manifest, "JOB_SCHEMA_PATH", self.schema_path),
            patch.object(
                candidate_manifest, "UNITY_PIPELINE_PATH", self.unity_pipeline_path
            ),
        )
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()

    @staticmethod
    def write_json(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def make_candidate(self) -> tuple[Path, Path, dict]:
        candidate = self.root / self.job["candidateDir"]
        file = candidate / "UnityAssets/GenWorks/test-product/Outfit.fbx"
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("original", encoding="utf-8")
        value = {
            "schemaVersion": 2,
            "kind": "image2outfit-candidate",
            "jobId": self.job["id"],
            "productName": self.job["productName"],
            "adapterId": self.job["adapterId"],
            "runId": "test-run",
            "createdAt": "2026-09-12T00:00:00Z",
            "sourceCommit": os.environ.get("GITHUB_SHA", "local"),
            "inputHashes": candidate_manifest.inputs(self.job_path, self.job),
            "files": candidate_manifest.manifest([file], candidate),
            "unityReady": {"status": "NOT_REQUESTED"},
            "releaseDecision": "REVIEW_REQUIRED",
        }
        return candidate, file, value

    def verify(self, candidate: Path, value: dict) -> list[str]:
        return candidate_manifest.verify_candidate(
            self.job_path, self.job, candidate, value
        )

    def test_legacy_job_is_rejected(self) -> None:
        legacy_job = dict(self.job)
        legacy_job["schemaVersion"] = 1
        self.write_json(self.job_path, legacy_job)
        with self.assertRaisesRegex(ValueError, "schemaVersion must be 2"):
            candidate_manifest.load(self.job_path)

    def test_private_avatar_cannot_be_selected_for_delivery(self) -> None:
        self.job["deliveryAssets"] = ["Assets/_Vendor/TestAvatar/Avatar.fbx"]
        with self.assertRaisesRegex(ValueError, "private avatar source"):
            candidate_manifest.candidate_files(self.job, POLICY)

    def test_valid_v2_manifest_passes(self) -> None:
        candidate, _, value = self.make_candidate()
        self.assertEqual(self.verify(candidate, value), [])

    def test_missing_required_field_is_rejected_by_schema_and_writer(self) -> None:
        candidate, _, value = self.make_candidate()
        value.pop("runId")
        errors = self.verify(candidate, value)
        self.assertTrue(any("runId is required" in error for error in errors), errors)
        with self.assertRaisesRegex(ValueError, "runId is required"):
            candidate_manifest.write(candidate / "candidate-manifest.json", value)

    def test_wrong_types_are_rejected(self) -> None:
        candidate, _, value = self.make_candidate()
        value["files"] = {}
        errors = self.verify(candidate, value)
        self.assertTrue(any("files must be array" in error for error in errors), errors)

        _, _, value = self.make_candidate()
        value["files"][0]["bytes"] = "8"
        errors = self.verify(candidate, value)
        self.assertTrue(
            any("bytes must be integer" in error for error in errors), errors
        )

    def test_invalid_enum_and_sha_are_rejected(self) -> None:
        candidate, _, value = self.make_candidate()
        value["releaseDecision"] = "GO"
        errors = self.verify(candidate, value)
        self.assertTrue(
            any("releaseDecision must be one of" in error for error in errors), errors
        )

        _, _, value = self.make_candidate()
        value["files"][0]["sha256"] = "not-a-sha"
        errors = self.verify(candidate, value)
        self.assertTrue(
            any("sha256 does not match" in error for error in errors), errors
        )

    def test_duplicate_file_path_is_rejected(self) -> None:
        candidate, _, value = self.make_candidate()
        value["files"].append(deepcopy(value["files"][0]))
        errors = self.verify(candidate, value)
        self.assertTrue(
            any("duplicate candidate manifest path" in error for error in errors),
            errors,
        )

    def test_unexpected_top_level_field_is_rejected(self) -> None:
        candidate, _, value = self.make_candidate()
        value["surpriseAuthority"] = True
        errors = self.verify(candidate, value)
        self.assertTrue(
            any("surpriseAuthority is not allowed" in error for error in errors), errors
        )

    def test_stale_input_hash_is_rejected_semantically(self) -> None:
        candidate, _, value = self.make_candidate()
        key = next(iter(value["inputHashes"]))
        value["inputHashes"][key] = "0" * 64
        errors = self.verify(candidate, value)
        self.assertTrue(
            any("candidate input changed" in error for error in errors), errors
        )

    def test_tampered_candidate_file_is_rejected(self) -> None:
        candidate, file, value = self.make_candidate()
        file.write_text("tampered", encoding="utf-8")
        errors = self.verify(candidate, value)
        self.assertTrue(
            any("candidate file changed" in error for error in errors), errors
        )


if __name__ == "__main__":
    unittest.main()
