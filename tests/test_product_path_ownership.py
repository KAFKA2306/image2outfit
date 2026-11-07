from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import production_contract as contract  # noqa: E402
import production_gate  # noqa: E402


class ProductPathOwnershipTest(unittest.TestCase):
    def _root(self, temporary: str) -> Path:
        root = Path(temporary)
        config = root / "config"
        config.mkdir(parents=True)
        (config / "job.schema.v2.json").write_text(
            json.dumps({"type": "object"}), encoding="utf-8"
        )
        return root

    def _policy(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "requiredPoses": ["standing"],
            "minimumPreview": {"requiredViews": []},
            "requiredHumanEvidenceKinds": [],
        }

    def _job(self) -> dict[str, object]:
        return {
            "schemaVersion": 2,
            "id": "product-a",
            "adapterId": "adapter-a",
            "productRoot": "Assets/GenWorks/product-a",
            "productManifestPath": "Assets/GenWorks/product-a/ProductManifest.json",
            "blendPath": "Assets/GenWorks/product-a/Source/product.blend",
            "fbxAssetPath": "Assets/GenWorks/product-a/Models/product.fbx",
            "prefabAssetPath": "Assets/GenWorks/product-a/Prefab/product.prefab",
            "integratedPrefabAssetPath": "Assets/GenWorks/product-a/Prefab/integrated.prefab",
            "deliveryAssets": ["Assets/GenWorks/product-a/Models/product.fbx"],
            "licenseEvidence": "config/products/product-a/license.json",
            "humanEvidence": {},
            "targetAvatarAssetPath": "Assets/SharedAvatar/target.prefab",
            "privateSourceRoots": ["Assets/_Vendor"],
        }

    def test_canonical_product_paths_and_shared_inputs_are_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            errors = contract.validate_job(self._job(), self._policy(), root)
        self.assertEqual(errors, [])

    def test_cross_product_delivery_asset_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            job = self._job()
            job["deliveryAssets"] = ["Assets/GenWorks/product-b/Models/product.fbx"]
            errors = contract.validate_job(job, self._policy(), root)
        self.assertIn(
            "job.deliveryAssets[0] must belong to Assets/GenWorks/product-a", errors
        )

    def test_cross_product_license_record_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            job = self._job()
            job["licenseEvidence"] = "config/products/product-b/license.json"
            errors = contract.validate_job(job, self._policy(), root)
        self.assertIn(
            "job.licenseEvidence must belong to config/products/product-a", errors
        )

    def test_human_evidence_identity_is_bound_to_job_and_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            evidence_path = root / "Assets" / "_Local" / "Evidence" / "review.json"
            evidence_path.parent.mkdir(parents=True)
            evidence_path.write_text(
                json.dumps(
                    {
                        "jobId": "product-b",
                        "adapterId": "adapter-b",
                        "candidateManifestSha256": "not-a-hash",
                    }
                ),
                encoding="utf-8",
            )
            job = self._job()
            job["humanEvidence"] = {
                "visual-review": "Assets/_Local/Evidence/review.json"
            }
            errors = contract.validate_job(job, self._policy(), root)
        self.assertIn("job.humanEvidence.visual-review jobId must match job.id", errors)
        self.assertIn(
            "job.humanEvidence.visual-review adapterId must match job.adapterId", errors
        )
        self.assertIn(
            "job.humanEvidence.visual-review candidateManifestSha256 must be a lowercase SHA-256",
            errors,
        )

    def test_resolved_delivery_path_cannot_escape_product_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            job = self._job()
            job["deliveryAssets"] = [
                "Assets/GenWorks/product-a/../product-b/Models/product.fbx"
            ]
            errors = contract.validate_job(job, self._policy(), root)
        self.assertIn(
            "job.deliveryAssets[0] must belong to Assets/GenWorks/product-a", errors
        )

    def test_gate_load_rejects_invalid_job_before_candidate_or_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            policy = self._policy()
            (root / "config" / "release-policy.json").write_text(
                json.dumps(policy), encoding="utf-8"
            )
            job = self._job()
            job["deliveryAssets"] = ["Assets/GenWorks/product-b/Models/product.fbx"]
            job_path = root / "job.json"
            job_path.write_text(json.dumps(job), encoding="utf-8")
            with patch.object(
                production_gate.candidate_contract,
                "required_job_fields",
                return_value=("schemaVersion", "id"),
            ):
                with self.assertRaisesRegex(ValueError, "job contract invalid"):
                    production_gate._load(job_path, root)


if __name__ == "__main__":
    unittest.main()
