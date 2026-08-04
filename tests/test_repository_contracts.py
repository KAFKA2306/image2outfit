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
        root_documents = (ROOT / "README.md", ROOT / "AGENTS.md")
        for path in root_documents:
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
        self.assertEqual(
            [],
            nested_agents,
            f"Nested agent contracts duplicate root AGENTS.md: {nested_agents}",
        )

        text_by_path = {
            path: path.read_text(encoding="utf-8") for path in root_documents
        }
        combined = "\n".join(text_by_path.values())
        for required in (
            "config/products/<slug>/",
            "Assets/GenWorks/<slug>/",
            "contents: read",
            "task audit:repo",
        ):
            with self.subTest(required=required):
                self.assertIn(required, combined)

        for forbidden in (
            "docs/GENWORKS_LAYOUT.md",
            "docs/TOOLCHAIN.md",
            ".github/AGENTS.md",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertFalse(
                    any(f"]({forbidden})" in text for text in text_by_path.values()),
                    f"Deleted document link remains: {forbidden}",
                )

    def test_deprecated_paths_and_runtime_state_are_absent(self) -> None:
        forbidden_paths = (
            ROOT / "Assets" / "GenWorks" / "Legacy",
            ROOT / ".github" / "run",
            ROOT / ".github" / "status",
            ROOT / "tools" / "audit_snapshot.py",
            ROOT / "tools" / "package_snapshot.py",
        )
        for path in forbidden_paths:
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self.assertFalse(path.exists(), f"Deprecated path remains: {path}")

        published = sorted(
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("*")
            if path.is_dir() and path.name.casefold() == "published"
        )
        self.assertEqual(
            [],
            published,
            f"Deprecated Published directories exist: {published}",
        )

    def test_workflow_surface_is_generic(self) -> None:
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
                self.assertFalse((workflows / obsolete).exists(), obsolete)

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
        self.assertEqual(
            [],
            violations,
            f"Removed snapshot contracts remain: {violations}",
        )

    def test_every_product_uses_the_same_namespaced_contract(self) -> None:
        products_root = ROOT / "config" / "products"
        product_dirs = sorted(path for path in products_root.iterdir() if path.is_dir())
        self.assertGreaterEqual(len(product_dirs), 2)

        policy = read_json(ROOT / "config" / "genworks-handoff-policy.json")
        required_views = set(policy["requiredPreviewViews"])
        allowed_statuses = set(policy["statuses"])
        automated_gates = policy["requiredAutomatedTechnicalGatesBeforeHumanReview"]
        human_gates = policy["requiredHumanReleaseGates"]
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
                self.assertTrue(job_path.is_file(), job_path)
                self.assertTrue(license_path.is_file(), license_path)

                job = read_json(job_path)
                product_root = f"Assets/GenWorks/{product_id}"
                delivery_assets = set(job.get("deliveryAssets", []))
                self.assertEqual(job["id"], product_id)
                self.assertEqual(job["productRoot"], product_root)
                self.assertEqual(
                    job["licenseEvidence"],
                    f"config/products/{product_id}/license.json",
                )

                for suffix in ("job", "license", "approval"):
                    self.assertFalse(
                        (ROOT / "config" / f"{product_id}-{suffix}.json").exists()
                    )

                for field in required_assets:
                    value = job.get(field)
                    self.assertIsInstance(value, str, f"{product_id}: {field}")
                    self.assertTrue(value, f"{product_id}: {field}")
                    self.assertTrue(
                        value.startswith(product_root + "/"),
                        f"{product_id}: {field} must stay under {product_root}",
                    )
                    self.assertIn(
                        value,
                        delivery_assets,
                        f"{product_id}: {field} must be a handoff asset",
                    )

                previews = job.get("previewPaths")
                self.assertIsInstance(previews, dict, product_id)
                self.assertEqual(set(previews), required_views, product_id)
                for value in previews.values():
                    self.assertTrue(value.startswith(product_root + "/"), value)
                    self.assertIn(value, delivery_assets, value)

                manifest_path = ROOT / job["productManifestPath"]
                self.assertTrue(manifest_path.is_file(), manifest_path)
                manifest = read_json(manifest_path)
                self.assertEqual(manifest.get("productId"), product_id)
                self.assertEqual(manifest.get("productRoot"), product_root)

                status = manifest.get("status")
                self.assertIn(status, allowed_statuses, manifest_path)
                handoff = manifest.get("handoff")
                self.assertIsInstance(handoff, dict, manifest_path)
                self.assertTrue(handoff.get("resumable"), manifest_path)
                self.assertEqual(handoff.get("canonicalWorkspace"), product_root)
                self.assertTrue(handoff.get("doNotRebuildFromZero"), manifest_path)

                gates = manifest.get("technicalGates")
                self.assertIsInstance(gates, dict, manifest_path)
                if status in {"TECHNICAL_READY", "HUMAN_REVIEW_PENDING", "RELEASED"}:
                    for gate_name in automated_gates:
                        self.assertEqual(
                            gates.get(gate_name), "PASS", (manifest_path, gate_name)
                        )
                if status == "RELEASED":
                    for gate_name in human_gates:
                        self.assertEqual(
                            gates.get(gate_name), "PASS", (manifest_path, gate_name)
                        )

    def test_handoff_policy_preserves_resumable_work(self) -> None:
        rules = read_json(ROOT / "config" / "genworks-handoff-policy.json")["rules"]
        expected = {
            "actionsArtifactsAreCanonicalWorkState": False,
            "trackedCheckpointRequiredForHandoff": True,
            "unityConfiguredPrefabsRequiredForTechnicalReady": True,
            "humanReviewRequiredForRelease": True,
            "rebuildFromZeroWhenCheckpointExists": False,
            "retainRejectedCheckpointAndReason": True,
        }
        for name, value in expected.items():
            with self.subTest(rule=name):
                self.assertIs(rules[name], value)

    def test_release_schema_is_the_single_job_field_source(self) -> None:
        schema = read_json(ROOT / "config" / "job.schema.v2.json")
        self.assertEqual(tuple(schema["required"]), gate.required_job_fields())
        self.assertEqual(schema["properties"]["schemaVersion"]["const"], 2)
        self.assertIn("hostedPoseScript", schema["properties"])
        self.assertEqual(sorted((ROOT / "config").glob("*.template.json")), [])

    def test_release_policy_and_unity_adapter_remain_current(self) -> None:
        policy = read_json(ROOT / "config" / "release-policy.json")
        self.assertNotIn("primaryAdapterId", policy)
        self.assertIn("haolan-v1.6", policy["blockedReleaseAdapterIds"])

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


if __name__ == "__main__":
    unittest.main()
