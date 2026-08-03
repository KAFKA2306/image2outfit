from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import production_contract as contract  # noqa: E402


class ProductionContractTest(unittest.TestCase):
    def test_job_schema_rejects_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            schema = {
                "type": "object",
                "additionalProperties": False,
                "required": ["schemaVersion"],
                "properties": {"schemaVersion": {"const": 2}},
            }
            path = root / "schema.json"
            path.write_text(json.dumps(schema), encoding="utf-8")
            errors = contract.validate_schema_file(
                {"schemaVersion": 2, "typoField": True}, path, "job"
            )
        self.assertIn("job.typoField is not allowed", errors)

    def test_workspace_failure_restores_canonical_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "Assets" / "GenWorks" / "demo"
            target.mkdir(parents=True)
            marker = target / "marker.txt"
            marker.write_text("last-good", encoding="utf-8")
            transaction = contract.WorkspaceSnapshot(target)
            had_original = transaction.begin()
            marker.write_text("broken", encoding="utf-8")
            (target / "partial.fbx").write_text("partial", encoding="utf-8")
            transaction.rollback(had_original)
            self.assertEqual(marker.read_text(encoding="utf-8"), "last-good")
            self.assertFalse((target / "partial.fbx").exists())
            self.assertFalse(transaction.backup.exists())
            self.assertFalse(transaction.journal.exists())

    def test_commercial_source_artifacts_require_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "Assets" / "result.json"
            source.parent.mkdir(parents=True)
            source.write_text("{}\n", encoding="utf-8")
            sha = hashlib.sha256(source.read_bytes()).hexdigest()
            normalized, errors = contract.validate_hashed_artifacts(
                [{"path": "Assets/result.json", "sha256": sha}], root=root
            )
            self.assertEqual(errors, [])
            self.assertEqual(normalized[0]["sha256"], sha)
            _, errors = contract.validate_hashed_artifacts(
                [{"path": "Assets/result.json", "sha256": "0" * 64}], root=root
            )
            self.assertIn(
                "sourceArtifacts[0].sha256 mismatch: Assets/result.json", errors
            )

    def test_known_fit_failure_blocks_candidate_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = (
                root
                / "Assets"
                / "GenWorks"
                / "demo"
                / "ProductManifest.json"
            )
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "productId": "demo",
                        "productRoot": "Assets/GenWorks/demo",
                        "technicalGates": {
                            "fitPenetration": "FAIL",
                            "humanVisualReview": "FAIL",
                        },
                        "fitAuditSummary": {"pass": False},
                    }
                ),
                encoding="utf-8",
            )
            errors = contract.product_state_errors(
                {
                    "id": "demo",
                    "productRoot": "Assets/GenWorks/demo",
                    "productManifestPath": "Assets/GenWorks/demo/ProductManifest.json",
                },
                root,
            )
            self.assertIn("product technical gate failed: fitPenetration", errors)
            self.assertIn("product fit audit is explicitly failing", errors)
            self.assertFalse(
                any("humanVisualReview" in value for value in errors), errors
            )


if __name__ == "__main__":
    unittest.main()
