from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import runtime_paths  # noqa: E402
from runtime_transaction import WorkspaceSnapshot  # noqa: E402


class RuntimePathsTest(unittest.TestCase):
    def test_product_runtime_is_derived_from_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = runtime_paths.for_product(root, "sample-outfit")
            expected = root.resolve() / ".image2outfit" / "products" / "sample-outfit"
            self.assertEqual(paths.root, expected)
            self.assertEqual(paths.reports, expected / "reports")
            self.assertEqual(paths.candidate, expected / "candidate")
            self.assertEqual(paths.release, expected / "release")

    def test_invalid_product_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                runtime_paths.for_product(Path(temporary), "../escape")


class WorkspaceSnapshotTest(unittest.TestCase):
    def test_interrupted_snapshot_recovers_last_good_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "Assets/GenWorks/demo"
            target.mkdir(parents=True)
            (target / "ProductManifest.json").write_text(
                json.dumps({"status": "WORKING"}), encoding="utf-8"
            )
            snapshot = WorkspaceSnapshot(target)
            snapshot.begin()
            (target / "ProductManifest.json").write_text(
                json.dumps({"status": "BROKEN"}), encoding="utf-8"
            )
            recovered = WorkspaceSnapshot(target)
            recovered.recover()
            state = json.loads(
                (target / "ProductManifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(state["status"], "WORKING")
            self.assertFalse(recovered.backup.exists())
            self.assertFalse(recovered.journal.exists())
