from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import pipeline as legacy  # noqa: E402
import release_gate as gate  # noqa: E402


POLICY = {
    "schemaVersion": 1,
    "blockedReleaseAdapterIds": ["blocked-adapter-v1"],
    "minimumPreview": {
        "width": 1024,
        "height": 1024,
        "requiredViews": ["front", "back", "left", "right", "three-quarter"],
    },
    "minimumVisualScore": 4,
    "requiredPoses": ["neutral", "arms-up", "arm-cross", "crouch", "sit", "prone"],
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
    "artifactDir",
    "candidateDir",
    "releaseDir",
    "licenseEvidence",
    "privateSourceRoots",
    "deliveryAssets",
    "previewPaths",
    "humanEvidence",
]


class ReleaseGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "config").mkdir(parents=True)
        (self.root / "tools").mkdir(parents=True)
        (self.root / "Packages").mkdir(parents=True)
        (self.root / "ProjectSettings").mkdir(parents=True)
        (self.root / "Assets" / "GenWorks" / "Shared" / "Editor").mkdir(parents=True)
        (self.root / "Assets" / "_Vendor" / "TestAvatar").mkdir(parents=True)
        (self.root / "Assets" / "_Local" / "Generated" / "test-product").mkdir(parents=True)
        (self.root / "Assets" / "_Local" / "Jobs" / "test-product").mkdir(parents=True)
        (self.root / "Assets" / "_Local" / "Evidence" / "test-product").mkdir(parents=True)

        self.policy_path = self.root / "config" / "release-policy.json"
        self.schema_path = self.root / "config" / "job.schema.v2.json"
        self.unity_pipeline_path = self.root / "Assets" / "GenWorks" / "Shared" / "Editor" / "Image2OutfitPipeline.cs"
        self.write_json(self.policy_path, POLICY)
        self.write_json(
            self.schema_path,
            {
                "type": "object",
                "required": REQUIRED_JOB_FIELDS,
                "properties": {"schemaVersion": {"const": 2}},
            },
        )
        self.write_json(self.root / "config" / "toolchain-lock.json", {"schemaVersion": 1})
        (self.root / "config" / "blender-python-requirements.txt").write_text(
            "Pillow==12.3.0\n", encoding="utf-8"
        )
        self.write_json(self.root / "Packages" / "vpm-manifest.json", {})
        self.write_json(self.root / "Packages" / "manifest.json", {})
        (self.root / "ProjectSettings" / "ProjectVersion.txt").write_text(
            "m_EditorVersion: 2022.3.22f1\n", encoding="utf-8"
        )
        self.unity_pipeline_path.write_text("// test pipeline\n", encoding="utf-8")

        self.build_script = self.root / "tools" / "build.py"
        self.build_script.write_text("print('build')\n", encoding="utf-8")
        self.avatar = self.root / "Assets" / "_Vendor" / "TestAvatar" / "Avatar.prefab"
        self.avatar.write_text("private avatar", encoding="utf-8")
        self.avatar_source = self.root / "Assets" / "_Vendor" / "TestAvatar" / "Avatar.fbx"
        self.avatar_source.write_text("private avatar source", encoding="utf-8")
        self.license = self.root / "Assets" / "_Local" / "Evidence" / "test-product" / "license.json"
        self.write_json(
            self.license,
            {
                "adapterId": "test-adapter-v1",
                "sourceUrl": "https://example.invalid/avatar",
                "checkedAt": "2026-08-02T00:00:00Z",
                "commercialOutfitAllowed": True,
                "avatarFilesRedistributed": False,
            },
        )

        self.generated = self.root / "Assets" / "_Local" / "Generated" / "test-product"
        self.outfit_fbx = self.generated / "Outfit.fbx"
        self.outfit_prefab = self.generated / "Outfit.prefab"
        self.integrated = self.generated / "Outfit_avatar.prefab"
        for file in (self.outfit_fbx, self.outfit_prefab, self.integrated):
            file.write_text(file.name, encoding="utf-8")

        self.job_path = self.root / "Assets" / "_Local" / "Jobs" / "test-product" / "job.json"
        evidence_root = "Assets/_Local/Evidence/test-product"
        generated_root = "Assets/_Local/Generated/test-product"
        self.job = {
            "schemaVersion": 2,
            "id": "test-product",
            "productName": "Test outfit",
            "adapterId": "test-adapter-v1",
            "buildScript": "tools/build.py",
            "blendPath": f"{generated_root}/Outfit.blend",
            "fbxAssetPath": f"{generated_root}/Outfit.fbx",
            "prefabAssetPath": f"{generated_root}/Outfit.prefab",
            "integratedPrefabAssetPath": f"{generated_root}/Outfit_avatar.prefab",
            "targetAvatarAssetPath": "Assets/_Vendor/TestAvatar/Avatar.prefab",
            "targetSourcePath": "Assets/_Vendor/TestAvatar/Avatar.fbx",
            "artifactDir": "Artifacts/test-product",
            "candidateDir": "Candidates/test-product",
            "releaseDir": "Release/test-product",
            "licenseEvidence": f"{evidence_root}/license.json",
            "privateSourceRoots": ["Assets/_Vendor/TestAvatar"],
            "deliveryAssets": [f"{generated_root}/Outfit.fbx", f"{generated_root}/Outfit.prefab"],
            "previewPaths": {
                view: f"{generated_root}/{view}.png"
                for view in POLICY["minimumPreview"]["requiredViews"]
            },
            "humanEvidence": {
                kind: f"{evidence_root}/{kind}.json"
                for kind in POLICY["requiredHumanEvidenceKinds"]
            },
            "allowedExtraBones": [],
        }
        self.write_json(self.job_path, self.job)

        self.patches = (
            patch.object(gate, "ROOT", self.root),
            patch.object(gate, "POLICY_PATH", self.policy_path),
            patch.object(gate, "JOB_SCHEMA_PATH", self.schema_path),
            patch.object(gate, "UNITY_PIPELINE_PATH", self.unity_pipeline_path),
            patch.object(legacy, "ROOT", self.root),
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

    @staticmethod
    def sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def build_candidate(self) -> Path:
        candidate = self.root / self.job["candidateDir"]
        asset_root = candidate / "UnityAssets" / "_Local" / "Generated" / "test-product"
        asset_root.mkdir(parents=True)
        copied = []
        for source in (self.outfit_fbx, self.outfit_prefab):
            target = asset_root / source.name
            target.write_bytes(source.read_bytes())
            copied.append(target)
        preview_root = candidate / "Preview"
        preview_root.mkdir(parents=True)
        for view in POLICY["minimumPreview"]["requiredViews"]:
            target = preview_root / f"{view}.png"
            target.write_bytes(b"preview-" + view.encode())
            copied.append(target)
        manifest_path = candidate / "candidate-manifest.json"
        gate.write(
            manifest_path,
            {
                "schemaVersion": 2,
                "kind": "image2outfit-candidate",
                "jobId": self.job["id"],
                "productName": self.job["productName"],
                "adapterId": self.job["adapterId"],
                "runId": "unit-test",
                "createdAt": "2026-08-02T00:00:00Z",
                "sourceCommit": "local",
                "inputHashes": gate.inputs(self.job_path, self.job),
                "files": gate.manifest(copied, candidate),
                "releaseDecision": "REVIEW_REQUIRED",
            },
        )
        return manifest_path

    def write_passing_evidence(self, candidate_hash: str) -> None:
        common = {
            "schemaVersion": 2,
            "jobId": self.job["id"],
            "adapterId": self.job["adapterId"],
            "candidateManifestSha256": candidate_hash,
            "status": "PASS",
            "checkedAt": "2026-08-02T00:00:00Z",
            "reviewer": "human:test-reviewer",
        }
        evidence_root = self.root / "Assets" / "_Local" / "Evidence" / "test-product"
        self.write_json(
            evidence_root / "visual-review.json",
            {
                **common,
                "kind": "visual-review",
                "scores": {"silhouette": 4, "fit": 4, "material": 4, "presentation": 4},
                "criticalDefects": 0,
            },
        )
        self.write_json(
            evidence_root / "pose-penetration-review.json",
            {
                **common,
                "kind": "pose-penetration-review",
                "poses": {pose: "PASS" for pose in POLICY["requiredPoses"]},
                "criticalPenetrations": 0,
            },
        )
        self.write_json(
            evidence_root / "vrchat-runtime-review.json",
            {
                **common,
                "kind": "vrchat-runtime-review",
                "vrchatBuildAndTest": "PASS",
                "testedInVRChat": True,
            },
        )

    def test_legacy_job_is_rejected(self) -> None:
        legacy_job = dict(self.job)
        legacy_job["schemaVersion"] = 1
        self.write_json(self.job_path, legacy_job)
        with self.assertRaisesRegex(ValueError, "schemaVersion must be 2"):
            gate.load(self.job_path)

    def test_private_avatar_cannot_be_selected_for_delivery(self) -> None:
        self.job["deliveryAssets"] = ["Assets/_Vendor/TestAvatar/Avatar.fbx"]
        with self.assertRaisesRegex(ValueError, "private avatar source"):
            gate.candidate_files(self.job, POLICY)

    def test_release_without_human_evidence_is_no_go(self) -> None:
        self.build_candidate()
        result = gate.run_release(self.job_path, self.job, POLICY)
        self.assertEqual(result, 2)
        audit = gate.read(self.root / self.job["artifactDir"] / "audit.json")
        self.assertEqual(audit["decision"], "NO-GO")
        self.assertFalse((self.root / self.job["releaseDir"]).exists())

    def test_blocked_adapter_is_rejected_with_passing_evidence(self) -> None:
        self.job["adapterId"] = "blocked-adapter-v1"
        self.write_json(self.job_path, self.job)
        manifest_path = self.build_candidate()
        self.write_passing_evidence(self.sha256(manifest_path))
        result = gate.run_release(self.job_path, self.job, POLICY)
        self.assertEqual(result, 2)
        audit = gate.read(self.root / self.job["artifactDir"] / "audit.json")
        self.assertIn("adapter blocked from release: blocked-adapter-v1", audit["errors"])

    def test_release_requires_unchanged_hash_bound_evidence(self) -> None:
        manifest_path = self.build_candidate()
        self.write_passing_evidence(self.sha256(manifest_path))
        with patch.dict(os.environ, {}, clear=True):
            result = gate.run_release(self.job_path, self.job, POLICY)
        self.assertEqual(result, 0)
        audit = gate.read(self.root / self.job["artifactDir"] / "audit.json")
        self.assertEqual(audit["decision"], "GO")
        self.assertTrue((self.root / self.job["releaseDir"] / "test-product.zip").is_file())

    def test_changed_candidate_invalidates_review(self) -> None:
        manifest_path = self.build_candidate()
        self.write_passing_evidence(self.sha256(manifest_path))
        candidate_file = next(
            file for file in (self.root / self.job["candidateDir"]).rglob("Outfit.fbx")
        )
        candidate_file.write_text("tampered", encoding="utf-8")
        result = gate.run_release(self.job_path, self.job, POLICY)
        self.assertEqual(result, 2)
        audit = gate.read(self.root / self.job["artifactDir"] / "audit.json")
        self.assertTrue(any("candidate file changed" in error for error in audit["errors"]))


if __name__ == "__main__":
    unittest.main()
