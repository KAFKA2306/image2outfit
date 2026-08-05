from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import production_gate  # noqa: E402
import runtime_paths  # noqa: E402
from production_gate_core import DirectoryTransaction  # noqa: E402


class DirectoryTransactionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.target = (
            self.root
            / ".image2outfit"
            / "products"
            / "test-product"
            / "candidate"
        )
        self.target.mkdir(parents=True)
        (self.target / "marker.txt").write_text("last-good", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_failed_iteration_restores_last_good_directory(self) -> None:
        transaction = DirectoryTransaction(self.target)
        had_original = transaction.begin()
        self.target.mkdir(parents=True)
        (self.target / "marker.txt").write_text("failed-new", encoding="utf-8")
        transaction.rollback(had_original)
        self.assertEqual(
            "last-good", (self.target / "marker.txt").read_text(encoding="utf-8")
        )
        self.assertFalse(transaction.backup.exists())
        self.assertFalse(transaction.journal.exists())

    def test_successful_iteration_commits_new_directory(self) -> None:
        transaction = DirectoryTransaction(self.target)
        had_original = transaction.begin()
        self.target.mkdir(parents=True)
        (self.target / "marker.txt").write_text("new-good", encoding="utf-8")
        transaction.commit(had_original)
        self.assertEqual(
            "new-good", (self.target / "marker.txt").read_text(encoding="utf-8")
        )
        self.assertFalse(transaction.backup.exists())
        self.assertFalse(transaction.journal.exists())

    def test_next_run_recovers_interrupted_protected_state(self) -> None:
        transaction = DirectoryTransaction(self.target)
        transaction.begin()
        recovered = DirectoryTransaction(self.target)
        recovered.recover()
        self.assertEqual(
            "last-good", (self.target / "marker.txt").read_text(encoding="utf-8")
        )
        self.assertFalse(recovered.backup.exists())
        self.assertFalse(recovered.journal.exists())

    def test_next_run_recovers_interrupted_prepared_state(self) -> None:
        transaction = DirectoryTransaction(self.target)
        transaction._write_journal("PREPARED", True)
        recovered = DirectoryTransaction(self.target)
        recovered.recover()
        self.assertEqual(
            "last-good", (self.target / "marker.txt").read_text(encoding="utf-8")
        )
        self.assertFalse(recovered.journal.exists())

    def test_rollback_removes_new_directory_without_previous_state(self) -> None:
        target = (
            self.root
            / ".image2outfit"
            / "products"
            / "new-product"
            / "release"
        )
        transaction = DirectoryTransaction(target)
        had_original = transaction.begin()
        target.mkdir(parents=True)
        (target / "package.zip").write_text("invalid", encoding="utf-8")
        transaction.rollback(had_original)
        self.assertFalse(target.exists())
        self.assertFalse(transaction.backup.exists())
        self.assertFalse(transaction.journal.exists())


class ProductionGateCommercialTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        product = self.root / "config" / "products" / "demo"
        product.mkdir(parents=True)
        self.write_json(
            self.root / "config" / "release-policy.json",
            {"schemaVersion": 1, "commercialMethodPolicy": {}},
        )
        self.write_json(
            product / "construction.json",
            {
                "schemaVersion": 1,
                "productId": "demo",
                "profile": "loose-layered",
            },
        )
        self.job = {
            "id": "demo",
            "adapterId": "demo-v1",
            "buildScript": "tools/demo_product.py",
        }
        self.selection = {
            "schemaVersion": 1,
            "passed": True,
            "productId": "demo",
            "commercialProfile": "commercial-v1",
            "constructionProfile": "loose-layered",
            "constructionPath": "config/products/demo/construction.json",
            "requiredCapabilities": [
                "layering-collision",
                "dynamic-evaluation",
            ],
            "requiredCommercialEvidence": [
                "penetration-report",
                "runtime-performance",
                "motion-review",
            ],
            "errors": [],
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def write_json(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value) + "\n", encoding="utf-8")

    def candidate_manifest(self, value: dict | None = None) -> Path:
        path = (
            runtime_paths.for_job(self.root, self.job).candidate
            / "candidate-manifest.json"
        )
        self.write_json(path, value or {"schemaVersion": 2, "jobId": "demo"})
        return path

    def test_candidate_manifest_binds_method_and_policy_hashes(self) -> None:
        manifest = self.candidate_manifest()
        binding = production_gate._bind_method_to_candidate(
            self.job,
            self.selection,
            self.root,
        )
        saved = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(saved["constructionMethod"], binding)
        self.assertEqual(binding["constructionProfile"], "loose-layered")
        self.assertEqual(len(binding["constructionSha256"]), 64)
        self.assertEqual(len(binding["releasePolicySha256"]), 64)

    def test_policy_or_construction_change_invalidates_candidate(self) -> None:
        binding = production_gate._binding_snapshot(
            self.job,
            self.selection,
            self.root,
        )
        manifest = {"schemaVersion": 2, "constructionMethod": binding}
        construction = self.root / self.selection["constructionPath"]
        self.write_json(
            construction,
            {
                "schemaVersion": 1,
                "productId": "demo",
                "profile": "panel-sewn",
            },
        )
        errors = production_gate._bound_method_errors(
            self.job,
            self.selection,
            manifest,
            self.root,
        )
        self.assertTrue(
            any("constructionSha256" in value for value in errors),
            errors,
        )

    def test_failed_commercial_evidence_never_calls_release_core(self) -> None:
        self.candidate_manifest(
            {
                "schemaVersion": 2,
                "constructionMethod": production_gate._binding_snapshot(
                    self.job,
                    self.selection,
                    self.root,
                ),
            }
        )
        commercial = {
            "schemaVersion": 1,
            "passed": False,
            "candidateManifestSha256": "0" * 64,
            "errors": ["runtime-performance: evidence unreadable"],
        }
        with (
            mock.patch.object(
                production_gate.method_selection,
                "select",
                return_value=self.selection,
            ),
            mock.patch.object(
                production_gate.method_selection,
                "validate_commercial_evidence",
                return_value=commercial,
            ),
            mock.patch.object(production_gate.core, "_run_release") as runner,
        ):
            result = production_gate._run_release(
                Path("config/products/demo/job.json"),
                self.job,
                {},
                self.root,
            )

        self.assertEqual(result, 2)
        runner.assert_not_called()
        report = json.loads(
            (
                runtime_paths.for_job(self.root, self.job).reports
                / "commercial-method-quality.json"
            ).read_text(encoding="utf-8")
        )
        self.assertFalse(report["passed"])


if __name__ == "__main__":
    unittest.main()
