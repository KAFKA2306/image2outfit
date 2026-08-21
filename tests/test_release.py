from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import candidate_manifest
import pipeline as legacy
import production_gate_core
import release_gate
import release_orchestrator
import release_packager
from release_provenance_gate import evaluate_release_provenance


POLICY = {
    "schemaVersion": 1,
    "blockedReleaseAdapterIds": [],
    "minimumPreview": {
        "width": 1024,
        "height": 1024,
        "requiredViews": ["front", "back", "left", "right", "three-quarter"],
    },
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
    "licenseEvidence",
    "privateSourceRoots",
    "deliveryAssets",
    "previewPaths",
    "humanEvidence",
]


class CommercialEvidenceContractTest(unittest.TestCase):
    def test_evidence_requires_tool_identity_and_hashed_artifacts(self) -> None:
        policy = json.loads(
            (ROOT / "config/release-policy.json").read_text(encoding="utf-8")
        )
        evidence = policy["commercialMethodPolicy"]["evidenceContract"]
        self.assertEqual(evidence["schemaVersion"], 2)
        self.assertEqual(
            evidence["toolContract"]["requiredFields"], ["id", "version", "command"]
        )
        self.assertEqual(
            evidence["sourceArtifactContract"]["requiredFields"], ["path", "sha256"]
        )
        self.assertIs(
            evidence["sourceArtifactContract"]["candidateHashBindingRequired"], True
        )


class PoseContractTest(unittest.TestCase):
    def test_release_policy_is_the_only_product_pose_contract(self) -> None:
        policy = json.loads(
            (ROOT / "config/release-policy.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            policy["requiredPoses"],
            ["neutral", "arms-up", "arm-cross", "crouch", "sit", "prone"],
        )
        conflicts = []
        for path in (ROOT / "config/products").glob("*/construction.json"):
            construction = json.loads(path.read_text(encoding="utf-8"))
            if "requiredPoses" in construction:
                conflicts.append(path.relative_to(ROOT).as_posix())
        self.assertEqual([], conflicts)


class ReleaseIntegrationTest(unittest.TestCase):
    def test_imported_release_route_has_one_validator(self) -> None:
        self.assertIs(production_gate_core._run_release, release_orchestrator._run_release)
        self.assertFalse(hasattr(release_gate, "evidence_gate"))
        self.assertFalse(hasattr(release_gate, "run_release"))

    def test_direct_legacy_release_is_disabled(self) -> None:
        source = (TOOLS / "release_gate.py").read_text(encoding="utf-8")
        self.assertIn("direct release_gate release is disabled", source)
        self.assertIn("tools/production_gate.py", source)


class ReleaseRawEvidenceContractTest(unittest.TestCase):
    def test_packager_copies_raw_evidence_before_manifesting_release(self) -> None:
        source = (TOOLS / "release_packager.py").read_text(encoding="utf-8")
        human = source.index('package / "Evidence" / "Human"')
        commercial = source.index('package / "Evidence" / "Commercial"')
        release_manifest = source.index('release / "release-manifest.json"')
        self.assertLess(human, release_manifest)
        self.assertLess(commercial, release_manifest)


class ReleaseGateTest(unittest.TestCase):
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
            '[project]\nname = "test"\nversion = "0.0.0"\n'
            'dependencies = ["Pillow==12.3.0"]\n',
            encoding="utf-8",
        )
        self.write_json(self.root / "Packages/vpm-manifest.json", {})
        self.write_json(self.root / "Packages/manifest.json", {})
        (self.root / "ProjectSettings/ProjectVersion.txt").write_text(
            "m_EditorVersion: 2022.3.22f1\n", encoding="utf-8"
        )
        self.unity_pipeline_path.write_text("// test pipeline\n", encoding="utf-8")

        self.build_script = self.root / "tools/build.py"
        self.build_script.write_text("print('build')\n", encoding="utf-8")
        self.avatar = self.root / "Assets/_Vendor/TestAvatar/Avatar.prefab"
        self.avatar.write_text("private avatar", encoding="utf-8")
        self.avatar_source = self.root / "Assets/_Vendor/TestAvatar/Avatar.fbx"
        self.avatar_source.write_text("private source", encoding="utf-8")
        self.outfit_fbx = self.root / "Assets/GenWorks/test-product/Models/Outfit.fbx"
        self.outfit_fbx.write_text("outfit", encoding="utf-8")
        self.license = self.root / "Assets/_Local/Evidence/test-product/license.json"
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
            "integratedPrefabAssetPath": (
                "Assets/GenWorks/test-product/Prefab/Outfit_avatar.prefab"
            ),
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
            patch.object(release_gate, "ROOT", self.root),
            patch.object(release_gate, "POLICY_PATH", self.policy_path),
            patch.object(release_gate, "JOB_SCHEMA_PATH", self.schema_path),
            patch.object(
                release_gate, "UNITY_PIPELINE_PATH", self.unity_pipeline_path
            ),
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

    def test_legacy_job_is_rejected(self) -> None:
        legacy_job = dict(self.job)
        legacy_job["schemaVersion"] = 1
        self.write_json(self.job_path, legacy_job)
        with self.assertRaisesRegex(ValueError, "schemaVersion must be 2"):
            release_gate.load(self.job_path)

    def test_private_avatar_cannot_be_selected_for_delivery(self) -> None:
        self.job["deliveryAssets"] = ["Assets/_Vendor/TestAvatar/Avatar.fbx"]
        with self.assertRaisesRegex(ValueError, "private avatar source"):
            release_gate.candidate_files(self.job, POLICY)

    def test_tampered_candidate_file_is_rejected(self) -> None:
        candidate = self.root / self.job["candidateDir"]
        file = candidate / "UnityAssets/GenWorks/test-product/Outfit.fbx"
        file.parent.mkdir(parents=True)
        file.write_text("original", encoding="utf-8")
        manifest = {
            "schemaVersion": 2,
            "kind": "image2outfit-candidate",
            "jobId": self.job["id"],
            "adapterId": self.job["adapterId"],
            "sourceCommit": "local",
            "inputHashes": {},
            "files": release_gate.manifest([file], candidate),
        }
        file.write_text("tampered", encoding="utf-8")
        errors = release_gate.verify_candidate(
            self.job_path, self.job, candidate, manifest
        )
        self.assertTrue(
            any("candidate file changed" in error for error in errors), errors
        )

    def test_direct_release_mode_is_disabled(self) -> None:
        with patch.object(
            sys,
            "argv",
            [
                "release_gate.py",
                "--mode",
                "release",
                "--job",
                str(self.job_path),
            ],
        ):
            self.assertEqual(release_gate.main(), 2)


class ReleasePackagerTest(unittest.TestCase):
    def test_raw_human_and_runtime_evidence_are_packaged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = root / ".image2outfit/products/demo/candidate"
            release = root / ".image2outfit/products/demo/release"
            candidate.mkdir(parents=True)
            payload = candidate / "UnityAssets/demo.prefab"
            payload.parent.mkdir(parents=True)
            payload.write_text("prefab", encoding="utf-8")
            manifest = {
                "schemaVersion": 2,
                "kind": "image2outfit-candidate",
                "sourceCommit": "abc",
            }
            manifest_path = candidate / "candidate-manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            candidate_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

            screenshot = root / "Assets/_Local/Evidence/demo/runtime.png"
            screenshot.parent.mkdir(parents=True)
            screenshot.write_bytes(b"runtime")
            evidence_path = (
                root / "Assets/_Local/Evidence/demo/vrchat-runtime-review.json"
            )
            evidence_path.write_text(
                json.dumps(
                    {"runtimeScreenshot": "Assets/_Local/Evidence/demo/runtime.png"}
                ),
                encoding="utf-8",
            )
            commercial = root / "Assets/GenWorks/demo/Evidence/Commercial"
            commercial.mkdir(parents=True)
            (commercial / "topology-audit.json").write_text("{}\n", encoding="utf-8")
            job_path = root / "config/products/demo/job.json"
            job_path.parent.mkdir(parents=True)
            job_path.write_text("{}\n", encoding="utf-8")
            job = {
                "id": "demo",
                "productName": "Demo",
                "adapterId": "demo-v1",
                "productRoot": "Assets/GenWorks/demo",
                "humanEvidence": {
                    "vrchat-runtime-review": (
                        "Assets/_Local/Evidence/demo/vrchat-runtime-review.json"
                    )
                },
            }
            result = release_packager.package_release(
                root=root,
                job_path=job_path,
                job=job,
                policy={"blockedReleaseAdapterIds": []},
                candidate=candidate,
                release=release,
                candidate_manifest=manifest,
                candidate_hash=candidate_hash,
                human_evidence={"vrchat-runtime-review": {"passed": True}},
                verify_candidate=lambda *_: [],
                now=lambda: datetime.now(timezone.utc).isoformat(),
            )
            self.assertTrue(
                (
                    release / "Package/Evidence/Human/vrchat-runtime-review.json"
                ).is_file()
            )
            self.assertTrue(
                (release / "Package/Evidence/Human/runtime/runtime.png").is_file()
            )
            self.assertTrue(
                (release / "Package/Evidence/Commercial/topology-audit.json").is_file()
            )
            archive = root / result["zip"]["path"]
            self.assertTrue(archive.is_file())
            with zipfile.ZipFile(archive) as bundle:
                names = set(bundle.namelist())
            self.assertIn("Package/Evidence/Human/vrchat-runtime-review.json", names)
            self.assertIn("Package/Evidence/Human/runtime/runtime.png", names)


class ReleaseProvenanceGateTests(unittest.TestCase):
    SHA = "a" * 40
    HEAD = "b" * 40

    def merged_pr(self) -> dict:
        return {
            "number": 42,
            "merged_at": "2026-08-15T00:00:00Z",
            "merge_commit_sha": self.SHA,
            "base": {"ref": "main"},
            "head": {"sha": self.HEAD},
        }

    def successful_run(self) -> dict:
        return {
            "id": 123,
            "name": "Release policy tests",
            "head_sha": self.HEAD,
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-08-15T00:01:00Z",
            "html_url": "https://github.com/KAFKA2306/image2outfit/actions/runs/123",
        }

    def evaluate(self, *, pulls=None, runs=None, ref="refs/heads/main") -> dict:
        return evaluate_release_provenance(
            release_ref=ref,
            release_sha=self.SHA,
            default_branch="main",
            associated_pulls=pulls if pulls is not None else [self.merged_pr()],
            workflow_runs=runs if runs is not None else [self.successful_run()],
        )

    def test_verified_requires_merged_pr_and_exact_head_policy_success(self) -> None:
        result = self.evaluate()
        self.assertEqual(result["state"], "VERIFIED")
        self.assertEqual(result["pr_number"], 42)
        self.assertEqual(result["pr_head_sha"], self.HEAD)
        self.assertEqual(result["policy_run_id"], 123)

    def test_direct_push_is_blocked(self) -> None:
        result = self.evaluate(pulls=[])
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["failure_class"], "MERGED_PR_PROVENANCE_MISSING")

    def test_non_default_branch_is_blocked(self) -> None:
        result = self.evaluate(ref="refs/heads/feat/example")
        self.assertEqual(result["failure_class"], "NON_DEFAULT_BRANCH")

    def test_missing_policy_run_is_blocked(self) -> None:
        result = self.evaluate(runs=[])
        self.assertEqual(result["failure_class"], "RELEASE_POLICY_RUN_MISSING")

    def test_failed_or_pending_policy_run_is_blocked(self) -> None:
        failed = self.successful_run() | {"conclusion": "failure"}
        result = self.evaluate(runs=[failed])
        self.assertEqual(result["failure_class"], "RELEASE_POLICY_NOT_SUCCESSFUL")

        pending = self.successful_run() | {"status": "in_progress", "conclusion": None}
        result = self.evaluate(runs=[pending])
        self.assertEqual(result["failure_class"], "RELEASE_POLICY_NOT_SUCCESSFUL")

    def test_success_for_another_head_does_not_authorize_release(self) -> None:
        other = self.successful_run() | {"head_sha": "c" * 40}
        result = self.evaluate(runs=[other])
        self.assertEqual(result["failure_class"], "RELEASE_POLICY_RUN_MISSING")


if __name__ == "__main__":
    unittest.main()
