from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

import run_garment_pipeline as runner
from image2outfit.pipeline import (
    PIPELINE_STAGES,
    ExecutionMode,
    new_pipeline_state,
    run_pipeline,
)
from image2outfit.tooling import ToolDescriptor, ToolRegistry


SOURCE_FINGERPRINT = "same-source"


def expected_identity(*, source_fingerprint: str = SOURCE_FINGERPRINT) -> dict[str, str]:
    return {
        "productId": "resume-integrity",
        "targetAvatar": "SiroinoSotai_PC",
        "sourceReference": "private-reference://sha256/resume-integrity",
        "profileId": "garment-reconstruction-v1",
        "revisionId": "v1",
        "sourceFingerprint": source_fingerprint,
    }


def registry_for(called: list[str], *, fail_at: str = "") -> ToolRegistry:
    registry = ToolRegistry()
    for stage in PIPELINE_STAGES:

        def handler(state, stage_name=stage.value):
            called.append(stage_name)
            if stage_name == fail_at:
                raise RuntimeError("expected failure")
            return {"mode": "planned", "stage": stage_name}

        registry.register(
            stage,
            handler,
            ToolDescriptor(stage.value, stage.value, f"{stage.value}.json"),
        )
    return registry


def partial_checkpoint() -> dict:
    identity = expected_identity()
    state = new_pipeline_state(
        product_id=identity["productId"],
        target_avatar=identity["targetAvatar"],
        source_reference=identity["sourceReference"],
        profile_id=identity["profileId"],
        revision_id=identity["revisionId"],
        run_id="checkpoint-run",
    )
    state["source_fingerprint"] = SOURCE_FINGERPRINT
    return run_pipeline(
        state,
        registry_for([], fail_at=PIPELINE_STAGES[3].value),
    )


def resume(previous: dict, *, source_fingerprint: str = SOURCE_FINGERPRINT) -> dict:
    return runner._resume_or_reset(
        previous,
        request={},
        expected=expected_identity(source_fingerprint=source_fingerprint),
        mode=ExecutionMode.PLAN,
    )


class PipelineResumeIntegrityTests(unittest.TestCase):
    def test_control_resumes_at_next_unfinished_stage_without_replaying_prefix(self) -> None:
        resumed = resume(partial_checkpoint())
        called: list[str] = []
        result = run_pipeline(resumed, registry_for(called))

        self.assertEqual(called[0], PIPELINE_STAGES[3].value)
        self.assertNotIn(PIPELINE_STAGES[0].value, called)
        self.assertEqual(result["status"], "PLANNED")
        self.assertEqual(
            [record["status"] for record in result["stage_records"][:3]],
            ["REUSED", "REUSED", "REUSED"],
        )

    def test_state_output_tamper_is_rejected_before_resume_run_is_created(self) -> None:
        checkpoint = partial_checkpoint()
        original_run = checkpoint["run_id"]
        stage = PIPELINE_STAGES[0].value
        checkpoint["outputs"][stage] = {"mode": "planned", "stage": "tampered"}

        with patch.object(runner, "resume_pipeline_state") as resume_state:
            with self.assertRaisesRegex(ValueError, "output mismatch"):
                resume(checkpoint)
        resume_state.assert_not_called()
        self.assertEqual(checkpoint["run_id"], original_run)

    def test_record_output_tamper_is_rejected_by_record_digest(self) -> None:
        checkpoint = partial_checkpoint()
        checkpoint["stage_records"][0]["output"]["stage"] = "tampered"
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            resume(checkpoint)

    def test_output_digest_tamper_is_rejected(self) -> None:
        checkpoint = partial_checkpoint()
        checkpoint["stage_records"][0]["outputDigest"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            resume(checkpoint)

    def test_record_digest_tamper_is_rejected(self) -> None:
        checkpoint = partial_checkpoint()
        checkpoint["stage_records"][0]["recordDigest"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            resume(checkpoint)

    def test_chain_tamper_is_rejected(self) -> None:
        checkpoint = partial_checkpoint()
        checkpoint["stage_records"][1]["previousRecordDigest"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "chain is broken"):
            resume(checkpoint)

    def test_missing_completed_record_is_rejected(self) -> None:
        checkpoint = partial_checkpoint()
        del checkpoint["stage_records"][1]
        with self.assertRaises(ValueError):
            resume(checkpoint)

    def test_wrong_record_run_and_product_identity_are_rejected(self) -> None:
        for field, message in (("runId", "runId mismatch"), ("productId", "productId mismatch")):
            with self.subTest(field=field):
                checkpoint = partial_checkpoint()
                checkpoint["stage_records"][0][field] = "wrong"
                with self.assertRaisesRegex(ValueError, message):
                    resume(checkpoint)

    def test_source_fingerprint_change_keeps_fresh_reset_semantics(self) -> None:
        checkpoint = partial_checkpoint()
        stage = PIPELINE_STAGES[0].value
        checkpoint["outputs"][stage] = {"mode": "planned", "stage": "stale-and-tampered"}

        reset = resume(checkpoint, source_fingerprint="new-source")

        self.assertEqual(reset["completed_stages"], [])
        self.assertEqual(reset["stage_records"], [])
        self.assertEqual(reset["outputs"], {})
        self.assertEqual(reset["checkpoint_reset"]["reason"], "source-fingerprint-changed")
        self.assertEqual(reset["source_fingerprint"], "new-source")

    def test_runner_boundary_rejects_tamper_before_registry_or_adapter_creation(self) -> None:
        checkpoint = partial_checkpoint()
        stage = PIPELINE_STAGES[0].value
        checkpoint["outputs"][stage] = {"mode": "planned", "stage": "tampered"}
        request = {
            "schemaVersion": 1,
            "productId": expected_identity()["productId"],
            "targetAvatar": expected_identity()["targetAvatar"],
            "sourceReference": expected_identity()["sourceReference"],
            "revisionId": expected_identity()["revisionId"],
        }

        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            request_path = root / "request.json"
            resume_path = root / "resume.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            resume_path.write_text(json.dumps(checkpoint), encoding="utf-8")
            args = argparse.Namespace(
                request=request_path,
                profile=None,
                engine="deterministic",
                execute=False,
                output=None,
                resume_state=resume_path,
                checkpoint_output=None,
                audit_root=Path(".image2outfit/audit"),
            )
            with (
                patch.object(runner, "parse_args", return_value=args),
                patch.object(runner, "_profile_path", return_value=ROOT / "profile.json"),
                patch.object(
                    runner,
                    "load_profile",
                    return_value={"profileId": expected_identity()["profileId"]},
                ),
                patch.object(
                    runner,
                    "pipeline_source_fingerprint",
                    return_value=SOURCE_FINGERPRINT,
                ),
                patch.object(runner, "build_registry") as build_registry,
            ):
                with self.assertRaisesRegex(ValueError, "output mismatch"):
                    runner.main()
        build_registry.assert_not_called()


if __name__ == "__main__":
    unittest.main()
