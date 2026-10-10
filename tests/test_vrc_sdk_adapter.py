from __future__ import annotations

import json
import sys
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.vrc_sdk_adapter import (  # noqa: E402
    ACTION_BUILD_AND_TEST,
    ACTION_BUILD_AND_UPLOAD,
    ACTION_CAPTURE_EVIDENCE,
    ACTION_SDK_STATUS,
    ACTION_VALIDATE_AVATAR,
    BLOCKED,
    FAIL,
    NOT_RUN,
    PASS,
    UNVERIFIED,
    UPLOAD_FAILURE_EVENT,
    UPLOAD_SUCCESS_EVENT,
    AdapterEvent,
    CandidateBinding,
    TargetIdentity,
    UnavailableVrcSdkAdapter,
    find_credential_material,
    vrc_build_and_test,
    vrc_build_and_upload,
    vrc_capture_evidence,
    vrc_sdk_status,
    vrc_validate_avatar,
)

CANDIDATE_SHA = "a" * 64
OTHER_SHA = "b" * 64
ARTIFACT_SHA = "c" * 64


class FakeSdk:
    """Controlled harness: scripted SDK outcomes that record every call."""

    def __init__(self, **overrides: Any) -> None:
        self.calls: list[str] = []
        self.script: dict[str, Any] = {
            "sdk_status": {
                "available": True,
                "sdkVersion": "3.10.0",
                "unityVersion": "2022.3.22f1",
            },
            "validate_avatar": {"status": PASS},
            "build_and_test": {"status": PASS, "artifactSha256": ARTIFACT_SHA},
            "capture_evidence": {
                "status": PASS,
                "evidence": [
                    {"kind": "validation", "status": PASS, "sha256": "d" * 64},
                    {"kind": "build_and_test", "status": PASS, "sha256": "e" * 64},
                ],
            },
            "build_and_upload": AdapterEvent(
                name=UPLOAD_SUCCESS_EVENT,
                candidate_sha256=CANDIDATE_SHA,
                target_id="avatar-demo",
                artifact_sha256=ARTIFACT_SHA,
            ),
        }
        self.script.update(overrides)

    def _value(self, name: str) -> Any:
        self.calls.append(name)
        value = self.script[name]
        if isinstance(value, Exception):
            raise value
        return value

    def sdk_status(self) -> Mapping[str, Any]:
        return self._value("sdk_status")

    def validate_avatar(
        self, candidate: CandidateBinding, target: TargetIdentity
    ) -> Mapping[str, Any]:
        return self._value("validate_avatar")

    def build_and_test(
        self, candidate: CandidateBinding, target: TargetIdentity
    ) -> Mapping[str, Any]:
        return self._value("build_and_test")

    def capture_evidence(
        self, candidate: CandidateBinding, target: TargetIdentity
    ) -> Mapping[str, Any]:
        return self._value("capture_evidence")

    def build_and_upload(
        self, candidate: CandidateBinding, target: TargetIdentity
    ) -> AdapterEvent:
        return self._value("build_and_upload")


def candidate() -> CandidateBinding:
    return CandidateBinding(product_id="siroino-demo", candidate_sha256=CANDIDATE_SHA)


def target() -> TargetIdentity:
    return TargetIdentity(target_id="avatar-demo")


def run_chain(
    sdk: Any, cand: CandidateBinding | None = None, tgt: TargetIdentity | None = None
):
    """Run the gated chain in order, mirroring the upload gate contract."""
    cand = cand or candidate()
    tgt = tgt or target()
    validation = vrc_validate_avatar(sdk, cand, tgt)
    build = vrc_build_and_test(sdk, cand, tgt, validation)
    evidence_result = vrc_capture_evidence(sdk, cand, tgt)
    upload = vrc_build_and_upload(
        sdk,
        cand,
        tgt,
        validation=validation,
        build_and_test=build,
        evidence=evidence_result.evidence,
    )
    return validation, build, evidence_result, upload


class VrcSdkAdapterContractTests(unittest.TestCase):
    def test_sdk_absence_is_runtime_state_not_failure(self) -> None:
        adapter = UnavailableVrcSdkAdapter()
        status = vrc_sdk_status(adapter, candidate())
        validation, build, evidence_result, upload = run_chain(adapter)

        self.assertEqual(status.status, NOT_RUN)
        self.assertEqual(validation.status, NOT_RUN)
        self.assertEqual(build.status, NOT_RUN)
        self.assertEqual(evidence_result.status, NOT_RUN)
        self.assertEqual(upload.status, NOT_RUN)
        for result in (status, validation, build, evidence_result, upload):
            self.assertNotEqual(result.status, FAIL)
            self.assertEqual(result.retry_stage is None, result.status == PASS)

    def test_unverified_prerequisite_keeps_upload_from_running(self) -> None:
        sdk = FakeSdk(validate_avatar={"status": UNVERIFIED})
        validation, build, evidence_result, upload = run_chain(sdk)

        self.assertEqual(validation.status, UNVERIFIED)
        self.assertEqual(upload.status, NOT_RUN)
        self.assertNotIn("build_and_upload", sdk.calls)

    def test_validation_failure_never_reaches_build_or_upload(self) -> None:
        sdk = FakeSdk(validate_avatar={"status": FAIL, "errors": ["missing rig"]})
        validation, build, evidence_result, upload = run_chain(sdk)

        self.assertEqual(validation.status, FAIL)
        self.assertEqual(validation.retry_stage, ACTION_VALIDATE_AVATAR)
        self.assertEqual(build.status, BLOCKED)
        self.assertEqual(upload.status, BLOCKED)
        self.assertNotIn("build_and_test", sdk.calls)
        self.assertNotIn("build_and_upload", sdk.calls)

    def test_build_failure_is_structured_blocker(self) -> None:
        sdk = FakeSdk(
            build_and_test={"status": FAIL, "errors": ["shader compile error"]}
        )
        validation, build, _, upload = run_chain(sdk)

        self.assertEqual(build.status, FAIL)
        self.assertEqual(build.errors, ("shader compile error",))
        self.assertEqual(build.retry_stage, ACTION_BUILD_AND_TEST)
        self.assertEqual(upload.status, BLOCKED)
        self.assertNotIn("build_and_upload", sdk.calls)

    def test_candidate_hash_mismatch_rejects_upload(self) -> None:
        sdk = FakeSdk()
        validation, build, evidence_result, _ = run_chain(sdk)
        other = CandidateBinding(product_id="siroino-demo", candidate_sha256=OTHER_SHA)
        sdk.calls.clear()
        upload = vrc_build_and_upload(
            sdk,
            other,
            target(),
            validation=validation,
            build_and_test=build,
            evidence=evidence_result.evidence,
        )

        self.assertEqual(upload.status, BLOCKED)
        self.assertIn("different candidate", upload.errors[0])
        self.assertNotIn("build_and_upload", sdk.calls)

    def test_evidence_bound_to_other_candidate_is_rejected(self) -> None:
        sdk = FakeSdk(
            capture_evidence={
                "status": PASS,
                "evidence": [
                    {
                        "kind": "validation",
                        "status": PASS,
                        "sha256": "d" * 64,
                        "candidateSha256": OTHER_SHA,
                    },
                ],
            }
        )
        _, _, evidence_result, _ = run_chain(sdk)

        self.assertEqual(evidence_result.status, BLOCKED)
        self.assertEqual(evidence_result.evidence, ())

    def test_missing_target_identity_rejects_upload(self) -> None:
        sdk = FakeSdk()
        validation, build, evidence_result, _ = run_chain(sdk)
        sdk.calls.clear()
        upload = vrc_build_and_upload(
            sdk,
            candidate(),
            None,
            validation=validation,
            build_and_test=build,
            evidence=evidence_result.evidence,
        )

        self.assertEqual(upload.status, BLOCKED)
        self.assertIn("target identity", upload.errors[0])
        self.assertNotIn("build_and_upload", sdk.calls)
        with self.assertRaises(ValueError):
            TargetIdentity(target_id="")

    def test_missing_evidence_rejects_upload(self) -> None:
        sdk = FakeSdk(
            capture_evidence={
                "status": PASS,
                "evidence": [
                    {"kind": "validation", "status": PASS, "sha256": "d" * 64}
                ],
            }
        )
        validation, build, evidence_result, upload = run_chain(sdk)

        self.assertEqual(upload.status, BLOCKED)
        self.assertIn("missing evidence: build_and_test", upload.errors)
        self.assertNotIn("build_and_upload", sdk.calls)

    def test_unhashed_pass_evidence_is_not_accepted(self) -> None:
        sdk = FakeSdk(
            capture_evidence={
                "status": PASS,
                "evidence": [
                    {"kind": "validation", "status": PASS},
                    {"kind": "build_and_test", "status": PASS, "sha256": "e" * 64},
                ],
            }
        )
        _, _, _, upload = run_chain(sdk)

        self.assertEqual(upload.status, BLOCKED)
        self.assertNotIn("build_and_upload", sdk.calls)

    def test_upload_success_requires_matching_event(self) -> None:
        validation, build, evidence_result, upload = run_chain(FakeSdk())

        self.assertEqual(upload.status, PASS)
        self.assertEqual(upload.artifact_sha256, ARTIFACT_SHA)
        self.assertIsNone(upload.retry_stage)

    def test_upload_adapter_exception_never_falls_back_to_success(self) -> None:
        sdk = FakeSdk(build_and_upload=RuntimeError("network reset"))
        _, _, _, upload = run_chain(sdk)

        self.assertEqual(upload.status, FAIL)
        self.assertEqual(upload.retry_stage, ACTION_BUILD_AND_UPLOAD)
        self.assertEqual(upload.errors, ("adapter raised RuntimeError",))
        self.assertIsNone(upload.artifact_sha256)

    def test_upload_failure_event_is_failure(self) -> None:
        sdk = FakeSdk(
            build_and_upload=AdapterEvent(
                name=UPLOAD_FAILURE_EVENT,
                candidate_sha256=CANDIDATE_SHA,
                target_id="avatar-demo",
            )
        )
        _, _, _, upload = run_chain(sdk)

        self.assertEqual(upload.status, FAIL)
        self.assertIsNone(upload.artifact_sha256)

    def test_process_exit_style_return_is_not_success(self) -> None:
        sdk = FakeSdk(build_and_upload=True)
        _, _, _, upload = run_chain(sdk)

        self.assertEqual(upload.status, FAIL)
        self.assertEqual(upload.errors, ("upload returned no adapter event",))

    def test_success_event_bound_to_other_candidate_is_blocked(self) -> None:
        sdk = FakeSdk(
            build_and_upload=AdapterEvent(
                name=UPLOAD_SUCCESS_EVENT,
                candidate_sha256=OTHER_SHA,
                target_id="avatar-demo",
                artifact_sha256=ARTIFACT_SHA,
            )
        )
        _, _, _, upload = run_chain(sdk)

        self.assertEqual(upload.status, BLOCKED)
        self.assertIsNone(upload.artifact_sha256)

    def test_success_event_bound_to_other_target_is_blocked(self) -> None:
        sdk = FakeSdk(
            build_and_upload=AdapterEvent(
                name=UPLOAD_SUCCESS_EVENT,
                candidate_sha256=CANDIDATE_SHA,
                target_id="avatar-other",
                artifact_sha256=ARTIFACT_SHA,
            )
        )
        _, _, _, upload = run_chain(sdk)

        self.assertEqual(upload.status, BLOCKED)

    def test_success_without_artifact_hash_is_failure(self) -> None:
        sdk = FakeSdk(
            build_and_upload=AdapterEvent(
                name=UPLOAD_SUCCESS_EVENT,
                candidate_sha256=CANDIDATE_SHA,
                target_id="avatar-demo",
            )
        )
        _, _, _, upload = run_chain(sdk)

        self.assertEqual(upload.status, FAIL)
        self.assertEqual(upload.errors, ("upload success without an artifact hash",))

    def test_credential_like_adapter_output_is_blocked_and_not_echoed(self) -> None:
        secret = "otpauth://totp/vrchat?secret=JBSWY3DPEHPK3PXP"
        sdk = FakeSdk(validate_avatar={"status": PASS, "warnings": [secret]})
        validation = vrc_validate_avatar(sdk, candidate(), target())
        serialized = json.dumps(validation.to_dict())

        self.assertEqual(validation.status, BLOCKED)
        self.assertNotIn("JBSWY3DPEHPK3PXP", serialized)
        self.assertNotIn("otpauth://", serialized)

    def test_credential_key_in_evidence_is_blocked_and_not_stored(self) -> None:
        sdk = FakeSdk(
            capture_evidence={
                "status": PASS,
                "evidence": [
                    {
                        "kind": "validation",
                        "status": PASS,
                        "sha256": "d" * 64,
                        "sessionToken": "abc123",
                    }
                ],
            }
        )
        evidence_result = vrc_capture_evidence(sdk, candidate(), target())
        serialized = json.dumps(evidence_result.to_dict())

        self.assertEqual(evidence_result.status, BLOCKED)
        self.assertNotIn("abc123", serialized)

    def test_unknown_status_and_invalid_hash_fail_closed(self) -> None:
        bad_status = vrc_validate_avatar(
            FakeSdk(validate_avatar={"status": "MAYBE"}), candidate(), target()
        )
        bad_hash = vrc_build_and_test(
            FakeSdk(build_and_test={"status": PASS, "artifactSha256": "not-a-hash"}),
            candidate(),
            target(),
            vrc_validate_avatar(FakeSdk(), candidate(), target()),
        )

        self.assertEqual(bad_status.status, FAIL)
        self.assertEqual(bad_hash.status, FAIL)

    def test_sdk_status_reports_availability_without_completion(self) -> None:
        available = vrc_sdk_status(FakeSdk(), candidate())
        unavailable = vrc_sdk_status(
            FakeSdk(sdk_status={"available": False}), candidate()
        )

        self.assertEqual(available.status, PASS)
        self.assertEqual(available.sdk_version, "3.10.0")
        self.assertEqual(available.unity_version, "2022.3.22f1")
        self.assertEqual(unavailable.status, NOT_RUN)
        self.assertEqual(available.action, ACTION_SDK_STATUS)

    def test_result_projection_is_machine_readable_and_candidate_bound(self) -> None:
        _, _, evidence_result, upload = run_chain(FakeSdk())
        payload = upload.to_dict()

        self.assertEqual(payload["projection"], "runtime")
        self.assertEqual(payload["candidateSha256"], CANDIDATE_SHA)
        self.assertEqual(payload["targetId"], "avatar-demo")
        self.assertEqual(payload["artifactSha256"], ARTIFACT_SHA)
        self.assertEqual(json.loads(json.dumps(payload)), payload)
        self.assertEqual(
            {item["kind"] for item in evidence_result.to_dict()["evidence"]},
            {"validation", "build_and_test"},
        )
        self.assertEqual(ACTION_CAPTURE_EVIDENCE, evidence_result.action)

    def test_find_credential_material_reports_paths_only(self) -> None:
        findings = find_credential_material(
            {"a": {"recoveryCode": "xyz"}, "b": ["Bearer abc.def"]}
        )

        self.assertEqual(findings, ("$.a.recoveryCode", "$.b[0]"))
        self.assertEqual(find_credential_material({"status": PASS, "errors": []}), ())


if __name__ == "__main__":
    unittest.main()
