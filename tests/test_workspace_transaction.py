from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

from workspace_transaction import WorkspaceSnapshot  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
