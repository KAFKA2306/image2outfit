from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import candidate_orchestrator  # noqa: E402
import production_gate  # noqa: E402
import runtime_paths  # noqa: E402
from runtime_transaction import DirectoryTransaction  # noqa: E402


class DirectoryTransactionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.target = (
            self.root / ".image2outfit" / "products" / "test-product" / "candidate"
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
        target = self.root / ".image2outfit" / "products" / "new-product" / "release"
        transaction = DirectoryTransaction(target)
        had_original = transaction.begin()
        target.mkdir(parents=True)
        (target / "package.zip").write_text("invalid", encoding="utf-8")
        transaction.rollback(had_original)
        self.assertFalse(target.exists())
        self.assertFalse(transaction.backup.exists())
        self.assertFalse(transaction.journal.exists())


class CandidateFinalizeTransactionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.job = {
            "id": "demo",
            "adapterId": "demo-v1",
            "candidateDir": ".image2outfit/products/demo/candidate",
            "releaseDir": ".image2outfit/products/demo/release",
            "artifactDir": ".image2outfit/products/demo/reports",
            "productRoot": "Assets/GenWorks/demo",
        }
        self.candidate = self.root / self.job["candidateDir"]
        self.release = self.root / self.job["releaseDir"]
        self.artifact = self.root / self.job["artifactDir"]
        self.workspace = self.root / self.job["productRoot"]
        for path, marker in (
            (self.candidate, "old-candidate"),
            (self.release, "old-release"),
            (self.workspace, "old-workspace"),
        ):
            path.mkdir(parents=True)
            (path / "marker.txt").write_text(marker, encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _fake_candidate_run(self, *_args: object, **_kwargs: object) -> int:
        self.candidate.mkdir(parents=True, exist_ok=True)
        (self.candidate / "marker.txt").write_text("new-candidate", encoding="utf-8")
        (self.workspace / "marker.txt").write_text("new-workspace", encoding="utf-8")
        self.artifact.mkdir(parents=True, exist_ok=True)
        (self.artifact / "audit.json").write_text("{}\n", encoding="utf-8")
        return 0

    def _run(self, finalize_candidate: object) -> int:
        with (
            mock.patch.object(
                candidate_orchestrator.candidate_contract, "ROOT", self.root
            ),
            mock.patch.object(
                candidate_orchestrator,
                "_research_state",
                return_value=({"passed": True}, {}, "0" * 64),
            ),
            mock.patch.object(
                candidate_orchestrator,
                "run_candidate",
                side_effect=self._fake_candidate_run,
            ),
            mock.patch.object(
                candidate_orchestrator.contract,
                "product_state_errors",
                return_value=[],
            ),
            mock.patch.object(
                candidate_orchestrator,
                "_bind_pose_contract_to_candidate",
                return_value=[],
            ),
            mock.patch.object(candidate_orchestrator, "_bind_research_to_candidate"),
        ):
            return candidate_orchestrator._run_candidate(
                Path("job.json"),
                self.job,
                {},
                finalize_candidate=finalize_candidate,
            )

    def test_finalizer_failure_restores_candidate_workspace_and_release(self) -> None:
        finalizer = mock.Mock(side_effect=RuntimeError("binding failed"))
        with self.assertRaisesRegex(RuntimeError, "binding failed"):
            self._run(finalizer)

        finalizer.assert_called_once_with()
        self.assertEqual(
            "old-candidate",
            (self.candidate / "marker.txt").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            "old-workspace",
            (self.workspace / "marker.txt").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            "old-release",
            (self.release / "marker.txt").read_text(encoding="utf-8"),
        )
        audit = json.loads((self.artifact / "audit.json").read_text(encoding="utf-8"))
        self.assertTrue(audit["stateProtection"]["previousCandidateRestored"])
        self.assertTrue(audit["stateProtection"]["previousWorkspaceRestored"])
        self.assertTrue(audit["stateProtection"]["previousReleaseRestored"])

    def test_finalizer_runs_before_last_good_backup_is_committed(self) -> None:
        def finalize() -> None:
            self.assertTrue(
                self.candidate.parent.joinpath(".candidate.last-good").is_dir()
            )
            self.assertTrue(
                self.workspace.parent.joinpath(".demo.last-good-workspace").is_dir()
            )
            self.assertEqual(
                "new-candidate",
                (self.candidate / "marker.txt").read_text(encoding="utf-8"),
            )

        result = self._run(finalize)

        self.assertEqual(result, 0)
        self.assertEqual(
            "new-candidate",
            (self.candidate / "marker.txt").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            "new-workspace",
            (self.workspace / "marker.txt").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            "old-release",
            (self.release / "marker.txt").read_text(encoding="utf-8"),
        )
        self.assertFalse(
            self.candidate.parent.joinpath(".candidate.last-good").exists()
        )
        self.assertFalse(
            self.workspace.parent.joinpath(".demo.last-good-workspace").exists()
        )


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

    def test_failed_commercial_evidence_never_calls_release_orchestrator(self) -> None:
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
            mock.patch.object(production_gate, "run_release") as runner,
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
