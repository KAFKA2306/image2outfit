from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import audit_repository_hygiene  # noqa: E402


class FinalRepositoryStateTest(unittest.TestCase):
    def test_full_repository_hygiene_passes(self) -> None:
        result = audit_repository_hygiene.audit(ROOT)
        self.assertTrue(result["passed"], result["findings"])
        self.assertEqual(result["findingCount"], 0)

    def test_every_tracked_product_has_namespaced_contracts(self) -> None:
        products = ROOT / "config" / "products"
        product_dirs = sorted(path for path in products.iterdir() if path.is_dir())
        self.assertGreaterEqual(len(product_dirs), 2)
        for product_dir in product_dirs:
            job_path = product_dir / "job.json"
            license_path = product_dir / "license.json"
            self.assertTrue(job_path.is_file(), job_path)
            self.assertTrue(license_path.is_file(), license_path)
            job = json.loads(job_path.read_text(encoding="utf-8-sig"))
            product_id = product_dir.name
            self.assertEqual(job["id"], product_id)
            self.assertEqual(job["productRoot"], f"Assets/GenWorks/{product_id}")
            self.assertEqual(
                job["licenseEvidence"],
                f"config/products/{product_id}/license.json",
            )

    def test_every_product_declares_a_resumable_checkpoint(self) -> None:
        policy = json.loads(
            (ROOT / "config" / "genworks-handoff-policy.json").read_text(
                encoding="utf-8-sig"
            )
        )
        products = ROOT / "config" / "products"
        required_fields = (
            "productManifestPath",
            "blendPath",
            "fbxAssetPath",
            "prefabAssetPath",
            "integratedPrefabAssetPath",
        )
        required_views = set(policy["requiredPreviewViews"])
        allowed_statuses = set(policy["statuses"])
        completion_status = policy["completionStatus"]
        completion_gates = policy["requiredCompletionGates"]
        out_of_scope = set(policy["outOfScopeGates"])
        self.assertFalse(set(completion_gates) & out_of_scope)

        for product_dir in sorted(path for path in products.iterdir() if path.is_dir()):
            job = json.loads(
                (product_dir / "job.json").read_text(encoding="utf-8-sig")
            )
            product_root = job["productRoot"]
            delivery_assets = set(job.get("deliveryAssets", []))

            for field in required_fields:
                value = job.get(field)
                self.assertIsInstance(value, str, f"{product_dir.name}: {field}")
                self.assertTrue(value, f"{product_dir.name}: {field}")
                self.assertTrue(
                    value.startswith(product_root + "/"),
                    f"{product_dir.name}: {field} must stay under {product_root}",
                )
                self.assertIn(
                    value,
                    delivery_assets,
                    f"{product_dir.name}: {field} must be tracked as a handoff asset",
                )

            previews = job.get("previewPaths")
            self.assertIsInstance(previews, dict, product_dir.name)
            self.assertEqual(set(previews), required_views, product_dir.name)
            for value in previews.values():
                self.assertTrue(value.startswith(product_root + "/"), value)
                self.assertIn(value, delivery_assets, value)

            manifest_path = ROOT / job["productManifestPath"]
            self.assertTrue(manifest_path.is_file(), manifest_path)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            self.assertEqual(manifest.get("productId"), job["id"])
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
                for gate in completion_gates:
                    self.assertEqual(gates.get(gate), "PASS", (manifest_path, gate))

    def test_handoff_policy_blocks_artifact_only_and_zero_rebuild_workflows(self) -> None:
        policy = json.loads(
            (ROOT / "config" / "genworks-handoff-policy.json").read_text(
                encoding="utf-8-sig"
            )
        )
        rules = policy["rules"]
        self.assertFalse(rules["actionsArtifactsAreCanonicalWorkState"])
        self.assertTrue(rules["trackedCheckpointRequiredForHandoff"])
        self.assertTrue(rules["completionDeterminedByRenderedEvidence"])
        self.assertTrue(rules["visualAppearanceReviewRequired"])
        self.assertTrue(rules["visualAppearanceReviewMayBePerformedByChatGPT"])
        self.assertFalse(rules["unityRequiredForCompletion"])
        self.assertFalse(rules["runtimeValidationInScope"])
        self.assertFalse(rules["outOfScopeFailuresAreBlockers"])
        self.assertFalse(rules["fitAuditFailureBlocksCompletion"])
        self.assertTrue(
            rules["runtimeCompatibilityMustNotBeClaimedWithoutExternalEvidence"]
        )
        self.assertFalse(rules["rebuildFromZeroWhenCheckpointExists"])
        self.assertTrue(rules["retainRejectedCheckpointAndReason"])

    def test_runtime_state_is_not_tracked(self) -> None:
        self.assertFalse((ROOT / ".github" / "run").exists())
        self.assertFalse((ROOT / ".github" / "status").exists())


if __name__ == "__main__":
    unittest.main()
