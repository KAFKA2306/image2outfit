from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import release_gate as gate  # noqa: E402


class ConfigContractTest(unittest.TestCase):
    def test_obsolete_job_templates_are_removed(self) -> None:
        self.assertEqual(sorted((ROOT / "config").glob("*.template.json")), [])

    def test_release_policy_has_no_unused_primary_adapter(self) -> None:
        policy = json.loads(
            (ROOT / "config" / "release-policy.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("primaryAdapterId", policy)
        self.assertIn("haolan-v1.6", policy["blockedReleaseAdapterIds"])
        self.assertEqual(policy["singleReleaseValidator"], "tools/customer_quality.py")
        self.assertEqual(
            policy["requiredPoses"],
            ["neutral", "arms-up", "arm-cross", "crouch", "sit", "prone"],
        )
        self.assertIn(
            "reviewerReference",
            policy["humanEvidenceContracts"]["commonRequiredFields"],
        )

    def test_handoff_policy_separates_repository_completion_from_external_runtime(self) -> None:
        policy = json.loads(
            (ROOT / "config" / "genworks-handoff-policy.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            policy["requiredMergeCheckpointGates"],
            [
                "blender",
                "fbx",
                "prefabDeclared",
                "fiveViewEvidence",
                "poseEvidence",
                "researchTrial",
            ],
        )
        boundary = policy["repositoryCompletionBoundary"]
        self.assertIn("five-view rendered visual review", boundary["includedStages"])
        self.assertIn("six-pose rendered fit and intersection audit", boundary["includedStages"])
        self.assertEqual(
            boundary["externalOutOfScopeStages"],
            [
                "Unity import/save/reload",
                "Modular Avatar/NDMF validation",
                "VRChat Build & Test",
                "VRChat runtime human review",
            ],
        )
        rules = policy["rules"]
        self.assertIs(rules["unityRequiredForRepositoryMerge"], False)
        self.assertIs(rules["externalRuntimeStagesAreRepositoryScope"], False)
        self.assertIs(rules["externalRuntimeStagesBlockRepositoryCompletion"], False)
        self.assertIs(rules["externalRuntimeStagesBlockBranchCleanup"], False)
        self.assertIs(
            rules["repositoryCompletionIsIndependentOfExternalReleaseStatus"], True
        )

    def test_job_schema_is_the_required_field_source(self) -> None:
        schema = json.loads(
            (ROOT / "config" / "job.schema.v2.json").read_text(encoding="utf-8")
        )
        self.assertEqual(tuple(schema["required"]), gate.required_job_fields())
        self.assertEqual(schema["properties"]["schemaVersion"]["const"], 2)
        self.assertIn("hostedPoseScript", schema["properties"])
        self.assertIn("productRoot", schema["required"])
        self.assertIn("productManifestPath", schema["required"])
        self.assertIs(schema["additionalProperties"], False)
        for field in ("artifactDir", "candidateDir", "releaseDir"):
            self.assertNotIn(field, schema["required"])
            self.assertNotIn(field, schema["properties"])

    def test_construction_contract_schema_is_closed(self) -> None:
        schema = json.loads(
            (ROOT / "config" / "products" / "construction.schema.v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(
            set(schema["required"]), {"schemaVersion", "productId", "profile"}
        )

    def test_product_config_is_namespaced(self) -> None:
        product_id = "siroino-wide-cargo"
        product_config = ROOT / "config" / "products" / product_id
        job_path = product_config / "job.json"
        license_path = product_config / "license.json"
        construction_path = product_config / "construction.json"
        self.assertTrue(job_path.is_file())
        self.assertTrue(license_path.is_file())
        self.assertTrue(construction_path.is_file())
        job = json.loads(job_path.read_text(encoding="utf-8"))
        construction = json.loads(construction_path.read_text(encoding="utf-8"))
        self.assertEqual(job["id"], product_id)
        self.assertEqual(construction["productId"], product_id)
        self.assertEqual(
            job["licenseEvidence"], f"config/products/{product_id}/license.json"
        )
        for field in ("artifactDir", "candidateDir", "releaseDir"):
            self.assertNotIn(field, job)
        self.assertFalse((ROOT / "config" / f"{product_id}-job.json").exists())
        self.assertFalse((ROOT / "config" / f"{product_id}-license.json").exists())
        self.assertFalse((ROOT / "config" / f"{product_id}-approval.json").exists())

    def test_unity_pipeline_uses_the_genworks_canonical_path(self) -> None:
        expected = (
            ROOT
            / "Assets"
            / "GenWorks"
            / "Shared"
            / "Editor"
            / "Image2OutfitPipeline.cs"
        )
        self.assertEqual(gate.UNITY_PIPELINE_PATH, expected)
        self.assertTrue(expected.is_file())
        self.assertFalse((ROOT / "Assets" / "Editor").exists())

    def test_generated_outfit_prefabs_are_modular_avatar_ready(self) -> None:
        configurator = (
            ROOT
            / "Assets"
            / "GenWorks"
            / "Shared"
            / "Editor"
            / "GeneratedOutfitPrefabConfigurator.cs"
        )
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
            self.assertIn(required, source)
        self.assertNotIn("LegacyRoot", source)
        self.assertNotIn("VRCAvatarDescriptor", source)
        self.assertNotIn('OutfitPrefabSegment = "/Prefabs/Outfit/"', source)

    def test_release_gate_contains_no_customer_release_validator(self) -> None:
        source = (TOOLS / "release_gate.py").read_text(encoding="utf-8")
        self.assertNotIn("def evidence_gate", source)
        self.assertNotIn("def run_release", source)
        core = (TOOLS / "production_gate_core.py").read_text(encoding="utf-8")
        release = (TOOLS / "release_orchestrator.py").read_text(encoding="utf-8")
        self.assertNotIn("legacy.run_release", core)
        self.assertNotIn("legacy.run_release", release)
        self.assertIn("contract.package_release", release)


if __name__ == "__main__":
    unittest.main()
