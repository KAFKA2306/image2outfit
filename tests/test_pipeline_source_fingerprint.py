from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.pipeline import ExecutionMode, new_pipeline_state
from pipeline_source_fingerprint import fingerprint_paths
from run_garment_pipeline import _identity_mismatches, _resume_or_reset


def expected_identity(*, source_fingerprint: str = "new-source") -> dict[str, str]:
    return {
        "productId": "ghost-gown",
        "targetAvatar": "SiroinoSotai_PC",
        "sourceReference": "private-reference://sha256/example",
        "profileId": "garment-reconstruction-v1",
        "revisionId": "v1",
        "sourceFingerprint": source_fingerprint,
    }


def pipeline_state(*, source_fingerprint: str) -> dict:
    expected = expected_identity(source_fingerprint=source_fingerprint)
    state = new_pipeline_state(
        product_id=expected["productId"],
        target_avatar=expected["targetAvatar"],
        source_reference=expected["sourceReference"],
        profile_id=expected["profileId"],
        revision_id=expected["revisionId"],
        run_id="previous-run",
    )
    state["source_fingerprint"] = source_fingerprint
    return state


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
        expected = expected_identity()
        state = pipeline_state(source_fingerprint="old-source")
        self.assertEqual(
            _identity_mismatches(state, expected),
            ["sourceFingerprint"],
        )

    def test_source_change_resets_instead_of_resuming_stale_state(self) -> None:
        expected = expected_identity()
        state = _resume_or_reset(
            pipeline_state(source_fingerprint="old-source"),
            request={},
            expected=expected,
            mode=ExecutionMode.EXECUTE,
        )
        self.assertEqual(state["status"], "READY")
        self.assertEqual(state["completed_stages"], [])
        self.assertEqual(state["source_fingerprint"], expected["sourceFingerprint"])
        self.assertEqual(
            state["checkpoint_reset"],
            {
                "reason": "source-fingerprint-changed",
                "previousRunId": "previous-run",
                "previousSourceFingerprint": "old-source",
                "sourceFingerprint": "new-source",
            },
        )

    def test_matching_source_resumes_existing_checkpoint(self) -> None:
        expected = expected_identity()
        state = _resume_or_reset(
            pipeline_state(source_fingerprint=expected["sourceFingerprint"]),
            request={},
            expected=expected,
            mode=ExecutionMode.PLAN,
        )
        self.assertEqual(state["parent_run_id"], "previous-run")
        self.assertEqual(state["resume_count"], 1)
        self.assertNotIn("checkpoint_reset", state)

    def test_non_source_identity_mismatch_is_rejected(self) -> None:
        expected = expected_identity()
        previous = pipeline_state(source_fingerprint=expected["sourceFingerprint"])
        previous["target_avatar"] = "different-avatar"
        with self.assertRaisesRegex(ValueError, "targetAvatar"):
            _resume_or_reset(
                previous,
                request={},
                expected=expected,
                mode=ExecutionMode.PLAN,
            )


if __name__ == "__main__":
    unittest.main()
