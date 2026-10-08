from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

from release_orchestrator import validate_go_release_pair  # noqa: E402
from runtime_transaction import ReceiptBoundDirectoryTransaction  # noqa: E402


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReleasePairTransactionTest(unittest.TestCase):
    def _old_pair(self, root: Path) -> tuple[Path, Path]:
        release = root / "release"
        release.mkdir()
        (release / "version.txt").write_text("old", encoding="utf-8")
        receipt = root / "artifact" / "audit.json"
        _write_json(receipt, {"decision": "GO", "version": "old"})
        return release, receipt

    def _new_payload(self, release: Path) -> None:
        release.mkdir(parents=True)
        (release / "version.txt").write_text("new", encoding="utf-8")

    def test_recovery_before_receipt_staging_restores_previous_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release, receipt = self._old_pair(Path(tmp))
            tx = ReceiptBoundDirectoryTransaction(release, receipt)
            tx.begin()
            self._new_payload(release)
            ReceiptBoundDirectoryTransaction(release, receipt).recover()
            self.assertEqual((release / "version.txt").read_text(), "old")
            self.assertEqual(json.loads(receipt.read_text())["version"], "old")

    def test_recovery_after_receipt_staging_restores_previous_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release, receipt = self._old_pair(Path(tmp))
            tx = ReceiptBoundDirectoryTransaction(release, receipt)
            tx.begin()
            self._new_payload(release)
            _write_json(tx.receipt_staging, {"decision": "GO", "version": "new"})
            ReceiptBoundDirectoryTransaction(release, receipt).recover()
            self.assertEqual((release / "version.txt").read_text(), "old")
            self.assertEqual(json.loads(receipt.read_text())["version"], "old")

    def test_recovery_during_commit_restores_previous_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release, receipt = self._old_pair(Path(tmp))
            tx = ReceiptBoundDirectoryTransaction(release, receipt)
            had_original = tx.begin()
            self._new_payload(release)
            _write_json(tx.receipt_staging, {"decision": "GO", "version": "new"})
            tx._write_pair_journal("COMMITTING", had_original, True)
            tx.receipt_staging.replace(receipt)
            ReceiptBoundDirectoryTransaction(release, receipt).recover()
            self.assertEqual((release / "version.txt").read_text(), "old")
            self.assertEqual(json.loads(receipt.read_text())["version"], "old")

    def test_committed_marker_makes_cleanup_recoverable_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release, receipt = self._old_pair(Path(tmp))
            tx = ReceiptBoundDirectoryTransaction(release, receipt)
            had_original = tx.begin()
            self._new_payload(release)
            _write_json(tx.receipt_staging, {"decision": "GO", "version": "new"})
            tx.receipt_staging.replace(receipt)
            tx._write_pair_journal("COMMITTED", had_original, True)
            recovered = ReceiptBoundDirectoryTransaction(release, receipt)
            recovered.recover()
            recovered.recover()
            self.assertEqual((release / "version.txt").read_text(), "new")
            self.assertEqual(json.loads(receipt.read_text())["version"], "new")
            self.assertFalse(tx.backup.exists())
            self.assertFalse(tx.receipt_backup.exists())

    def test_first_release_interruption_leaves_no_false_go(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = root / "release"
            receipt = root / "artifact" / "audit.json"
            tx = ReceiptBoundDirectoryTransaction(release, receipt)
            tx.begin()
            self._new_payload(release)
            _write_json(tx.receipt_staging, {"decision": "GO"})
            ReceiptBoundDirectoryTransaction(release, receipt).recover()
            self.assertFalse(release.exists())
            self.assertFalse(receipt.exists())

    def test_normal_commit_keeps_new_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release, receipt = self._old_pair(Path(tmp))
            tx = ReceiptBoundDirectoryTransaction(release, receipt)
            had_original = tx.begin()
            self._new_payload(release)
            _write_json(tx.receipt_staging, {"decision": "GO", "version": "new"})
            tx.commit(had_original)
            ReceiptBoundDirectoryTransaction(release, receipt).recover()
            self.assertEqual((release / "version.txt").read_text(), "new")
            self.assertEqual(json.loads(receipt.read_text())["version"], "new")


class ReleasePairBindingTest(unittest.TestCase):
    def _pair(self, root: Path) -> tuple[Path, Path, str]:
        job_id = "demo-product"
        adapter_id = "demo-adapter"
        candidate_hash = "a" * 64
        release = root / "release"
        release.mkdir()
        manifest = release / "release-manifest.json"
        _write_json(
            manifest,
            {
                "jobId": job_id,
                "adapterId": adapter_id,
                "candidateManifestSha256": candidate_hash,
            },
        )
        archive = release / f"{job_id}.zip"
        archive.write_bytes(b"archive")
        receipt = root / "audit.json"
        _write_json(
            receipt,
            {
                "decision": "GO",
                "releaseEligible": True,
                "jobId": job_id,
                "adapterId": adapter_id,
                "candidateManifestSha256": candidate_hash,
                "releaseManifestSha256": _digest(manifest),
                "zip": {"sha256": _digest(archive)},
            },
        )
        return release, receipt, candidate_hash

    def test_hash_bound_pair_accepts_exact_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release, receipt, candidate_hash = self._pair(Path(tmp))
            self.assertEqual(
                validate_go_release_pair(
                    release=release,
                    receipt_path=receipt,
                    job_id="demo-product",
                    adapter_id="demo-adapter",
                    candidate_hash=candidate_hash,
                ),
                [],
            )

    def test_tampered_receipt_hash_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release, receipt, candidate_hash = self._pair(Path(tmp))
            value = json.loads(receipt.read_text())
            value["releaseManifestSha256"] = "0" * 64
            _write_json(receipt, value)
            errors = validate_go_release_pair(
                release=release,
                receipt_path=receipt,
                job_id="demo-product",
                adapter_id="demo-adapter",
                candidate_hash=candidate_hash,
            )
            self.assertIn("GO receipt releaseManifestSha256 mismatch", errors)

    def test_tampered_release_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release, receipt, candidate_hash = self._pair(Path(tmp))
            (release / "release-manifest.json").write_text("{}\n", encoding="utf-8")
            errors = validate_go_release_pair(
                release=release,
                receipt_path=receipt,
                job_id="demo-product",
                adapter_id="demo-adapter",
                candidate_hash=candidate_hash,
            )
            self.assertTrue(any("release manifest" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
