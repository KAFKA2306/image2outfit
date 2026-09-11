from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.pipeline import ExecutionMode, new_pipeline_state
from pipeline_source_fingerprint import fingerprint_paths, pipeline_source_fingerprint
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


def make_source_fixture(root: Path) -> tuple[Path, Path]:
    files = {
        "src/image2outfit/runtime.py": "runtime-v1\n",
        "tools/runner.py": "runner-v1\n",
        "config/products/ghost-gown/product.json": "{}\n",
        "requests/ghost-gown.json": "{}\n",
        "config/release-policy.json": "{}\n",
        "config/genworks-handoff-policy.json": "{}\n",
        "contracts/quality/quality-spec.json": "{}\n",
        "config/job.schema.v2.json": "{}\n",
        "config/products/construction.schema.v1.json": "{}\n",
        "config/pipeline/visual-quality-defaults.v1.json": "{}\n",
        "config/toolchain-lock.json": "{}\n",
        "config/pipeline/stage-audit-record.schema.v1.json": "{}\n",
        "config/pipeline/run-audit-manifest.schema.v1.json": "{}\n",
        "pyproject.toml": "[project]\nname='fixture'\n",
        "uv.lock": "fixture-lock\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    profile_path = root / "config/pipeline-profiles/garment-reconstruction-v1.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        json.dumps(
            {
                "profileId": "garment-reconstruction-v1",
                "auditContract": {
                    "recordSchema": "config/pipeline/stage-audit-record.schema.v1.json",
                    "manifestSchema": "config/pipeline/run-audit-manifest.schema.v1.json",
                    "storageRoot": ".image2outfit/audit/{productId}/{runId}",
                },
            }
        ),
        encoding="utf-8",
    )
    return root / "requests/ghost-gown.json", profile_path


def fixture_fingerprint(root: Path, request_path: Path, profile_path: Path) -> str:
    return pipeline_source_fingerprint(
        root,
        product_id="ghost-gown",
        request_path=request_path,
        profile_path=profile_path,
    )


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

    def test_execution_semantic_dependencies_invalidate_checkpoint_identity(self) -> None:
        dependencies = (
            "src/image2outfit/runtime.py",
            "tools/runner.py",
            "config/products/ghost-gown/product.json",
            "requests/ghost-gown.json",
            "config/pipeline-profiles/garment-reconstruction-v1.json",
            "config/release-policy.json",
            "config/genworks-handoff-policy.json",
            "contracts/quality/quality-spec.json",
            "config/job.schema.v2.json",
            "config/products/construction.schema.v1.json",
            "config/pipeline/stage-audit-record.schema.v1.json",
            "config/pipeline/run-audit-manifest.schema.v1.json",
            "config/toolchain-lock.json",
            "uv.lock",
        )
        for relative in dependencies:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                request_path, profile_path = make_source_fixture(root)
                initial = fixture_fingerprint(root, request_path, profile_path)
                path = root / relative
                path.write_text(path.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
                self.assertNotEqual(initial, fixture_fingerprint(root, request_path, profile_path))

    def test_generated_runtime_outputs_do_not_change_source_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path, profile_path = make_source_fixture(root)
            initial = fixture_fingerprint(root, request_path, profile_path)

            for relative in (
                ".image2outfit/audit/ghost-gown/run-1/stage.json",
                "build/ghost-gown/render.png",
                "candidates/ghost-gown/output.json",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("generated\n", encoding="utf-8")

            self.assertEqual(initial, fixture_fingerprint(root, request_path, profile_path))

    def test_missing_referenced_schema_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path, profile_path = make_source_fixture(root)
            (root / "config/pipeline/stage-audit-record.schema.v1.json").unlink()
            with self.assertRaises(FileNotFoundError):
                fixture_fingerprint(root, request_path, profile_path)

    def test_profile_dependency_cannot_escape_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path, profile_path = make_source_fixture(root)
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["auditContract"]["recordSchema"] = "../../outside-schema.json"
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "escapes repository"):
                fixture_fingerprint(root, request_path, profile_path)

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
