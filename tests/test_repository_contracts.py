from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import release_gate as gate  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


class RepositoryContractTest(unittest.TestCase):
    def test_single_documentation_authority(self) -> None:
        documents = (ROOT / "README.md", ROOT / "AGENTS.md")
        for path in documents:
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file(), f"Missing root document: {path.name}")

        self.assertFalse(
            (ROOT / "docs").exists(),
            "Repository-wide guidance belongs in root README.md or AGENTS.md",
        )
        nested_agents = sorted(
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("AGENTS.md")
            if path != ROOT / "AGENTS.md"
        )
        self.assertEqual([], nested_agents)

        text_by_path = {path: path.read_text(encoding="utf-8") for path in documents}
        combined = "\n".join(text_by_path.values())
        for required in (
            "config/products/<slug>/",
            "Assets/GenWorks/<slug>/",
            "contents: read",
            "task audit:repo",
            ".image2outfit/products/<slug>/{reports,candidate,release}",
        ):
            with self.subTest(required=required):
                self.assertIn(required, combined)

        readme = text_by_path[ROOT / "README.md"]
        self.assertIn(
            "以前の `Artifacts/`、`Candidates/`、`Release/` は使用しません",
            readme,
        )
        for forbidden in (
            "docs/GENWORKS_LAYOUT.md",
            "docs/TOOLCHAIN.md",
            ".github/AGENTS.md",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertFalse(
                    any(f"]({forbidden})" in text for text in text_by_path.values())
                )

    def test_deprecated_paths_and_workflows_are_absent(self) -> None:
        for path in (
            ROOT / "Assets" / "GenWorks" / "Legacy",
            ROOT / ".github" / "run",
            ROOT / ".github" / "status",
            ROOT / "tools" / "audit_snapshot.py",
            ROOT / "tools" / "package_snapshot.py",
        ):
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self.assertFalse(path.exists())

        published = sorted(
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("*")
            if path.is_dir() and path.name.casefold() == "published"
        )
        self.assertEqual([], published)

        workflows = ROOT / ".github" / "workflows"
        self.assertTrue((workflows / "build-product-hosted.yml").is_file())
        for obsolete in (
            "siroino-wide-cargo-hosted.yml",
            "siroino-wide-cargo-self-hosted.yml",
            "siroino-wide-cargo-release.yml",
            "siroino-cyber-kawaii-large.yml",
            "genworks-siroino-render-loop.yml",
            "render-validation.yml",
        ):
            with self.subTest(workflow=obsolete):
                self.assertFalse((workflows / obsolete).exists())

    def test_layout_and_snapshot_contracts_are_canonical(self) -> None:
        layout = read_json(ROOT / "config" / "genworks-layout.json")
        self.assertNotIn("legacyRoot", layout)
        self.assertIn("Assets/GenWorks/Legacy", layout["forbiddenAssetRoots"])

        active_contract_files = (
            ROOT / "README.md",
            ROOT / "AGENTS.md",
            ROOT / "Taskfile.yml",
            ROOT / "Assets" / "GenWorks" / "OutfitCatalog.json",
            ROOT
            / "Assets"
            / "GenWorks"
            / "Shared"
            / "Editor"
            / "GeneratedOutfitPrefabConfigurator.cs",
        )
        forbidden_tokens = (
            "Legacy/Snapshots",
            "legacySnapshots",
            "legacySnapshotCount",
            "audit:snapshot",
            "package:snapshot",
            "LegacyRoot",
            "tools/audit_snapshot.py",
            "tools/package_snapshot.py",
        )
        violations: list[str] = []
        for path in active_contract_files:
            self.assertTrue(path.is_file(), f"Missing contract file: {path}")
            text = path.read_text(encoding="utf-8")
            violations.extend(
                f"{path.relative_to(ROOT).as_posix()}: {token}"
                for token in forbidden_tokens
                if token in text
            )
        self.assertEqual([], violations)

    def test_release_and_handoff_policies_are_current(self) -> None:
        release = read_json(ROOT / "config" / "release-policy.json")
        self.assertNotIn("primaryAdapterId", release)
        self.assertIn("haolan-v1.6", release["blockedReleaseAdapterIds"])
        self.assertEqual(
            release["singleReleaseValidator"],
            "tools/customer_quality.py",
        )
        self.assertEqual(
            release["requiredPoses"],
            ["neutral", "arms-up", "arm-cross", "crouch", "sit", "prone"],
        )
        self.assertIn(
            "reviewerReference",
            release["humanEvidenceContracts"]["commonRequiredFields"],
        )

        handoff = read_json(ROOT / "config" / "genworks-handoff-policy.json")
        self.assertEqual(handoff["schemaVersion"], 2)
        self.assertEqual(
            handoff["statuses"],
            ["WORKING", "COMPLETE", "REJECTED"],
        )
        self.assertEqual(handoff["completionStatus"], "COMPLETE")
        completion = set(handoff["requiredCompletionGates"])
        out_of_scope = set(handoff["outOfScopeGates"])
        self.assertEqual(
            completion,
            {
                "blender",
                "editableSource",
                "fbx",
                "prefabDeclared",
                "fiveViewEvidence",
                "poseEvidence",
                "visualAppearanceReview",
                "researchTrial",
            },
        )
        self.assertEqual(
            out_of_scope,
            {
                "unityImport",
                "unitySaveReload",
                "prefabReload",
                "modularAvatar",
                "ndmf",
                "vrchatBuildTest",
                "vrchatRuntime",
                "humanRuntimeReview",
            },
        )
        self.assertFalse(completion & out_of_scope)

        expected_rules = {
            "actionsArtifactsAreCanonicalWorkState": False,
            "trackedCheckpointRequiredForHandoff": True,
            "completionDeterminedByRenderedEvidence": True,
            "visualAppearanceReviewRequired": True,
            "visualAppearanceReviewMayBePerformedByChatGPT": True,
            "unityRequiredForCompletion": False,
            "runtimeValidationInScope": False,
            "outOfScopeFailuresAreBlockers": False,
            "fitAuditFailureBlocksCompletion": False,
            "runtimeCompatibilityMustNotBeClaimedWithoutExternalEvidence": True,
            "rebuildFromZeroWhenCheckpointExists": False,
            "retainRejectedCheckpointAndReason": True,
        }
        for name, value in expected_rules.items():
            with self.subTest(rule=name):
                self.assertIs(handoff["rules"][name], value)

    def test_schemas_are_closed_and_authoritative(self) -> None:
        job_schema = read_json(ROOT / "config" / "job.schema.v2.json")
        self.assertEqual(tuple(job_schema["required"]), gate.required_job_fields())
        self.assertEqual(job_schema["properties"]["schemaVersion"]["const"], 2)
        self.assertIs(job_schema["additionalProperties"], False)
        self.assertIn("hostedPoseScript", job_schema["properties"])
        self.assertIn("productRoot", job_schema["required"])
        self.assertIn("productManifestPath", job_schema["required"])
        for field in ("artifactDir", "candidateDir", "releaseDir"):
            self.assertNotIn(field, job_schema["required"])
            self.assertNotIn(field, job_schema["properties"])

        construction_schema = read_json(
            ROOT / "config" / "products" / "construction.schema.v1.json"
        )
        self.assertIs(construction_schema["additionalProperties"], False)
        self.assertEqual(
            set(construction_schema["required"]),
            {"schemaVersion", "productId", "profile"},
        )
        self.assertEqual(sorted((ROOT / "config").glob("*.template.json")), [])

    def test_every_product_has_a_verifiable_canonical_handoff(self) -> None:
        products_root = ROOT / "config" / "products"
        product_dirs = sorted(path for path in products_root.iterdir() if path.is_dir())
        self.assertGreaterEqual(len(product_dirs), 2)

        policy = read_json(ROOT / "config" / "genworks-handoff-policy.json")
        required_views = set(policy["requiredPreviewViews"])
        allowed_statuses = set(policy["statuses"])
        completion_status = policy["completionStatus"]
        completion_gates = policy["requiredCompletionGates"]
        required_assets = (
            "productManifestPath",
            "blendPath",
            "fbxAssetPath",
            "prefabAssetPath",
            "integratedPrefabAssetPath",
        )

        for product_dir in product_dirs:
            product_id = product_dir.name
            with self.subTest(product=product_id):
                job_path = product_dir / "job.json"
                license_path = product_dir / "license.json"
                construction_path = product_dir / "construction.json"
                self.assertTrue(job_path.is_file(), job_path)
                self.assertTrue(license_path.is_file(), license_path)
                self.assertTrue(construction_path.is_file(), construction_path)

                job = read_json(job_path)
                construction = read_json(construction_path)
                product_root = f"Assets/GenWorks/{product_id}"
                product_root_path = ROOT / product_root
                delivery_assets = set(job.get("deliveryAssets", []))

                self.assertEqual(job["id"], product_id)
                self.assertEqual(job["productRoot"], product_root)
                self.assertEqual(construction["productId"], product_id)
                self.assertEqual(
                    job["licenseEvidence"],
                    f"config/products/{product_id}/license.json",
                )
                for field in ("artifactDir", "candidateDir", "releaseDir"):
                    self.assertNotIn(field, job)
                for suffix in ("job", "license", "approval"):
                    self.assertFalse(
                        (ROOT / "config" / f"{product_id}-{suffix}.json").exists()
                    )

                self.assertTrue((product_root_path / "README.md").is_file())
                self.assertTrue((product_root_path / "Prefab").is_dir())

                for field in required_assets:
                    value = job.get(field)
                    self.assertIsInstance(value, str, f"{product_id}: {field}")
                    self.assertTrue(value, f"{product_id}: {field}")
                    self.assertTrue(value.startswith(product_root + "/"))
                    self.assertIn(value, delivery_assets)

                previews = job.get("previewPaths")
                self.assertIsInstance(previews, dict, product_id)
                self.assertEqual(set(previews), required_views)
                for value in previews.values():
                    self.assertTrue(value.startswith(product_root + "/"))
                    self.assertIn(value, delivery_assets)

                manifest_path = ROOT / job["productManifestPath"]
                self.assertTrue(manifest_path.is_file(), manifest_path)
                manifest = read_json(manifest_path)
                self.assertEqual(manifest.get("productId"), product_id)
                self.assertEqual(manifest.get("productRoot"), product_root)
                status = manifest.get("status", manifest.get("state"))
                self.assertIn(status, allowed_statuses, manifest_path)

                handoff = manifest.get("handoff")
                self.assertIsInstance(handoff, dict, manifest_path)
                self.assertTrue(handoff.get("resumable"), manifest_path)
                self.assertEqual(handoff.get("canonicalWorkspace"), product_root)
                self.assertTrue(handoff.get("doNotRebuildFromZero"), manifest_path)

                gates = manifest.get("technicalGates")
                self.assertIsInstance(gates, dict, manifest_path)
                if status == completion_status:
                    for gate_name in completion_gates:
                        self.assertEqual(
                            gates.get(gate_name),
                            "PASS",
                            (manifest_path, gate_name),
                        )
                    for value in delivery_assets:
                        self.assertTrue(
                            (ROOT / value).is_file(),
                            f"{product_id}: missing COMPLETE asset {value}",
                        )

                gate_paths = {
                    "blender": [job["blendPath"]],
                    "editableSource": [job["blendPath"]],
                    "fbx": [job["fbxAssetPath"]],
                    "prefabDeclared": [
                        job["prefabAssetPath"],
                        job["integratedPrefabAssetPath"],
                    ],
                    "fiveViewEvidence": list(previews.values()),
                    "poseEvidence": list(job.get("posePaths", {}).values()),
                }
                for gate_name, paths in gate_paths.items():
                    if gates.get(gate_name) != "PASS":
                        continue
                    for value in paths:
                        self.assertTrue(
                            (ROOT / value).is_file(),
                            f"{product_id}: {gate_name}=PASS but missing {value}",
                        )

    def test_unity_adapter_and_release_boundary_remain_current(self) -> None:
        pipeline = (
            ROOT
            / "Assets"
            / "GenWorks"
            / "Shared"
            / "Editor"
            / "Image2OutfitPipeline.cs"
        )
        self.assertEqual(gate.UNITY_PIPELINE_PATH, pipeline)
        self.assertTrue(pipeline.is_file())
        self.assertFalse((ROOT / "Assets" / "Editor").exists())

        configurator = pipeline.with_name("GeneratedOutfitPrefabConfigurator.cs")
        self.assertTrue(configurator.is_file())
        self.assertTrue(configurator.with_suffix(".cs.meta").is_file())
        source = configurator.read_text(encoding="utf-8")
        for required in (
            'CanonicalPrefabSegment = "/Prefab/"',
            'SharedRoot = "Assets/GenWorks/Shared/"',
            "filename.IndexOf('/') < 0",
            "OnPostprocessAllAssets",
            "PrefabUtility.LoadPrefabContents",
            "ModularAvatarMergeArmature",
            "ModularAvatarMeshSettings",
            "ArmatureLockMode.BaseToMerge",
            "mangleNames = true",
        ):
            with self.subTest(required=required):
                self.assertIn(required, source)
        for forbidden in (
            "LegacyRoot",
            "VRCAvatarDescriptor",
            'OutfitPrefabSegment = "/Prefabs/Outfit/"',
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

        release_gate_source = (TOOLS / "release_gate.py").read_text(encoding="utf-8")
        self.assertNotIn("def evidence_gate", release_gate_source)
        self.assertNotIn("def run_release", release_gate_source)
        core = (TOOLS / "production_gate_core.py").read_text(encoding="utf-8")
        release = (TOOLS / "release_orchestrator.py").read_text(encoding="utf-8")
        self.assertNotIn("legacy.run_release", core)
        self.assertNotIn("legacy.run_release", release)
        self.assertIn("contract.package_release", release)


if __name__ == "__main__":
    unittest.main()
