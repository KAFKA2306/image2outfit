from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from pipeline_source_fingerprint import fingerprint_paths
from run_garment_pipeline import _identity_mismatches


class PipelineSourceFingerprintTests(unittest.TestCase):
    def test_fingerprint_is_content_based_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "tools"
            source.mkdir()
            first = source / "a.py"
            second = source / "b.py"
            first.write_text("alpha\n", encoding="utf-8")
            second.write_text("beta\n", encoding="utf-8")

            initial = fingerprint_paths(root, [source])
            os.utime(first, None)
            self.assertEqual(initial, fingerprint_paths(root, [source]))

            second.write_text("beta changed\n", encoding="utf-8")
            self.assertNotEqual(initial, fingerprint_paths(root, [source]))

    def test_fingerprint_includes_relative_path_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left = root / "left"
            right = root / "right"
            left.mkdir()
            right.mkdir()
            (left / "same.py").write_text("same\n", encoding="utf-8")
            (right / "same.py").write_text("same\n", encoding="utf-8")

            self.assertNotEqual(
                fingerprint_paths(root, [left]),
                fingerprint_paths(root, [right]),
            )

    def test_resume_identity_detects_only_source_change(self) -> None:
        expected = {
            "productId": "ghost-gown",
            "targetAvatar": "SiroinoSotai_PC",
            "sourceReference": "private-reference://sha256/example",
            "profileId": "garment-reconstruction-v1",
            "revisionId": "v1",
            "sourceFingerprint": "new-source",
        }
        state = {
            "product_id": expected["productId"],
            "target_avatar": expected["targetAvatar"],
            "source_reference": expected["sourceReference"],
            "profile_id": expected["profileId"],
            "revision_id": expected["revisionId"],
            "source_fingerprint": "old-source",
        }
        self.assertEqual(
            _identity_mismatches(state, expected),
            ["sourceFingerprint"],
        )


if __name__ == "__main__":
    unittest.main()
