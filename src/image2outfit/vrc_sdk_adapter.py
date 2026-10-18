"""Pure VRCSDK adapter contract: candidate-bound validation, build, evidence, and upload gates.

Actual Unity Editor sessions, VRChat login, SDK validation, Build & Test, Game View
capture, and Build & Upload are runtime evidence. This module never executes them and
never stores credentials. An absent SDK, a skipped step, or a failed step is reported
on this runtime projection (NOT_RUN / UNVERIFIED / FAIL / BLOCKED). None of these
results changes the garment COMPLETE gate owned by config/genworks-handoff-policy.json,
and none of them may be promoted to PASS without an adapter event bound to the
candidate hash.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
NOT_RUN = "NOT_RUN"
UNVERIFIED = "UNVERIFIED"
STATUSES = frozenset({PASS, FAIL, BLOCKED, NOT_RUN, UNVERIFIED})
NON_EXECUTED = frozenset({NOT_RUN, UNVERIFIED})

ACTION_SDK_STATUS = "vrc_sdk_status"
ACTION_VALIDATE_AVATAR = "vrc_validate_avatar"
ACTION_BUILD_AND_TEST = "vrc_build_and_test"
ACTION_CAPTURE_EVIDENCE = "vrc_capture_evidence"
ACTION_BUILD_AND_UPLOAD = "vrc_build_and_upload"
ACTIONS = (
    ACTION_SDK_STATUS,
    ACTION_VALIDATE_AVATAR,
    ACTION_BUILD_AND_TEST,
    ACTION_CAPTURE_EVIDENCE,
    ACTION_BUILD_AND_UPLOAD,
)

UPLOAD_SUCCESS_EVENT = "upload.succeeded"
UPLOAD_FAILURE_EVENT = "upload.failed"
REQUIRED_UPLOAD_EVIDENCE_KINDS = ("validation", "build_and_test")

_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_CREDENTIAL_KEY = re.compile(
    r"password|passwd|secret|token|totp|otp|recovery|session|cookie|oauth|"
    r"authorization|api[_-]?key|credential|private[_-]?key",
    re.IGNORECASE,
)
_CREDENTIAL_VALUE = re.compile(
    r"otpauth://|bearer\s+[A-Za-z0-9._~+/=-]+|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"authcookie|\bauth=[A-Za-z0-9_-]{8,}|recovery[- ]code",
    re.IGNORECASE,
)


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 hex digest")
    return value


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must be a non-empty identifier")
    return value


def find_credential_material(value: object, path: str = "$") -> tuple[str, ...]:
    """Return JSON-like paths that look like credential material, never the values."""
    findings: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{path}.{key}"
            if isinstance(key, str) and _CREDENTIAL_KEY.search(key):
                findings.append(child)
            findings.extend(find_credential_material(item, child))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            findings.extend(find_credential_material(item, f"{path}[{index}]"))
    elif isinstance(value, str) and _CREDENTIAL_VALUE.search(value):
        findings.append(path)
    return tuple(findings)


@dataclass(frozen=True, slots=True)
class CandidateBinding:
    product_id: str
    candidate_sha256: str

    def __post_init__(self) -> None:
        _identifier(self.product_id, "product_id")
        _sha256(self.candidate_sha256, "candidate_sha256")


@dataclass(frozen=True, slots=True)
class TargetIdentity:
    """Explicit VRChat target. Upload is never inferred from a name or a folder."""

    target_id: str

    def __post_init__(self) -> None:
        _identifier(self.target_id, "target_id")


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    kind: str
    candidate_sha256: str
    status: str
    sha256: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.kind, "evidence kind")
        _sha256(self.candidate_sha256, "evidence candidate_sha256")
        if self.status not in STATUSES:
            raise ValueError(f"unknown evidence status: {self.status!r}")
        if self.sha256 is not None:
            _sha256(self.sha256, "evidence sha256")


@dataclass(frozen=True, slots=True)
class AdapterEvent:
    """Upload outcome delivered by the adapter. A process exit code is not an event."""

    name: str
    candidate_sha256: str | None
    target_id: str | None
    artifact_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class ActionResult:
    action: str
    product_id: str
    candidate_sha256: str
    status: str
    target_id: str | None = None
    sdk_version: str | None = None
    unity_version: str | None = None
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    artifact_sha256: str | None = None
    retry_stage: str | None = None
    evidence: tuple[EvidenceItem, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Machine-readable projection. Raw adapter payloads are never included."""
        return {
            "schemaVersion": 1,
            "projection": "runtime",
            "action": self.action,
            "productId": self.product_id,
            "candidateSha256": self.candidate_sha256,
            "targetId": self.target_id,
            "status": self.status,
            "sdkVersion": self.sdk_version,
            "unityVersion": self.unity_version,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "artifactSha256": self.artifact_sha256,
            "retryStage": self.retry_stage,
            "evidence": [
                {
                    "kind": item.kind,
                    "candidateSha256": item.candidate_sha256,
                    "status": item.status,
                    "sha256": item.sha256,
                }
                for item in self.evidence
            ],
        }


class VrcSdkAdapter(Protocol):
    """Boundary matching the official VRChat SDK actions and their events.

    Validation, build, and capture return a mapping with ``status`` and optional
    ``errors``, ``warnings``, ``artifactSha256``, ``evidence``, ``sdkVersion``, and
    ``unityVersion``. Upload returns an AdapterEvent.
    """

    def sdk_status(self) -> Mapping[str, Any]: ...

    def validate_avatar(
        self, candidate: CandidateBinding, target: TargetIdentity
    ) -> Mapping[str, Any]: ...

    def build_and_test(
        self, candidate: CandidateBinding, target: TargetIdentity
    ) -> Mapping[str, Any]: ...

    def capture_evidence(
        self, candidate: CandidateBinding, target: TargetIdentity
    ) -> Mapping[str, Any]: ...

    def build_and_upload(
        self, candidate: CandidateBinding, target: TargetIdentity
    ) -> AdapterEvent: ...


class UnavailableVrcSdkAdapter:
    """Adapter used when no Unity/VRCSDK session is available. Everything is NOT_RUN."""

    def __init__(self, reason: str = "vrc_sdk_unavailable") -> None:
        self.reason = _identifier(reason, "reason")

    def sdk_status(self) -> Mapping[str, Any]:
        return {"available": False, "warnings": [self.reason]}

    def validate_avatar(
        self, candidate: CandidateBinding, target: TargetIdentity
    ) -> Mapping[str, Any]:
        return {"status": NOT_RUN, "warnings": [self.reason]}

    def build_and_test(
        self, candidate: CandidateBinding, target: TargetIdentity
    ) -> Mapping[str, Any]:
        return {"status": NOT_RUN, "warnings": [self.reason]}

    def capture_evidence(
        self, candidate: CandidateBinding, target: TargetIdentity
    ) -> Mapping[str, Any]:
        return {"status": NOT_RUN, "warnings": [self.reason]}

    def build_and_upload(
        self, candidate: CandidateBinding, target: TargetIdentity
    ) -> AdapterEvent:
        return AdapterEvent(
            name="upload.not_run", candidate_sha256=None, target_id=None
        )


def _result(
    action: str,
    candidate: CandidateBinding,
    status: str,
    *,
    target: TargetIdentity | None = None,
    **fields: Any,
) -> ActionResult:
    retry_stage = None if status == PASS else action
    return ActionResult(
        action=action,
        product_id=candidate.product_id,
        candidate_sha256=candidate.candidate_sha256,
        status=status,
        target_id=target.target_id if target is not None else None,
        retry_stage=fields.pop("retry_stage", retry_stage),
        **fields,
    )


def _strings(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, str) for item in value
    ):
        raise ValueError("errors and warnings must be lists of strings")
    return tuple(value)


def _evidence_items(
    value: object, candidate: CandidateBinding
) -> tuple[tuple[EvidenceItem, ...], tuple[str, ...]]:
    if value is None:
        return (), ()
    if not isinstance(value, (list, tuple)):
        return (), ("evidence must be a list",)
    items: list[EvidenceItem] = []
    errors: list[str] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            errors.append(f"evidence[{index}] must be an object")
            continue
        bound = raw.get("candidateSha256", candidate.candidate_sha256)
        if bound != candidate.candidate_sha256:
            errors.append(f"evidence[{index}] is bound to a different candidate")
            continue
        try:
            items.append(
                EvidenceItem(
                    kind=raw.get("kind"),  # type: ignore[arg-type]
                    candidate_sha256=candidate.candidate_sha256,
                    status=raw.get("status"),  # type: ignore[arg-type]
                    sha256=raw.get("sha256"),
                )
            )
        except ValueError as exc:
            errors.append(f"evidence[{index}]: {exc}")
    return tuple(items), tuple(errors)


def _run_step(
    action: str,
    candidate: CandidateBinding,
    target: TargetIdentity | None,
    call: Any,
) -> tuple[Mapping[str, Any] | None, ActionResult | None]:
    """Invoke one adapter step. Returns (payload, None) or (None, rejected result)."""
    try:
        payload = call()
    except Exception as exc:  # adapter failures never become success
        return None, _result(
            action,
            candidate,
            FAIL,
            target=target,
            errors=(f"adapter raised {type(exc).__name__}",),
        )
    if not isinstance(payload, Mapping):
        return None, _result(
            action,
            candidate,
            FAIL,
            target=target,
            errors=("adapter returned a non-object payload",),
        )
    findings = find_credential_material(payload)
    if findings:
        return None, _result(
            action,
            candidate,
            BLOCKED,
            target=target,
            errors=(
                "credential-like material in adapter output at " + ", ".join(findings),
            ),
        )
    return payload, None


def vrc_sdk_status(adapter: VrcSdkAdapter, candidate: CandidateBinding) -> ActionResult:
    payload, rejected = _run_step(
        ACTION_SDK_STATUS, candidate, None, adapter.sdk_status
    )
    if rejected is not None:
        return rejected
    try:
        warnings = _strings(payload.get("warnings"))
        errors = _strings(payload.get("errors"))
    except ValueError as exc:
        return _result(ACTION_SDK_STATUS, candidate, FAIL, errors=(str(exc),))
    available = payload.get("available")
    if not isinstance(available, bool):
        return _result(
            ACTION_SDK_STATUS, candidate, FAIL, errors=("available must be a boolean",)
        )
    return _result(
        ACTION_SDK_STATUS,
        candidate,
        PASS if available else NOT_RUN,
        sdk_version=_optional_text(payload.get("sdkVersion")),
        unity_version=_optional_text(payload.get("unityVersion")),
        errors=errors,
        warnings=warnings,
    )


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _step_result(
    action: str,
    candidate: CandidateBinding,
    target: TargetIdentity,
    payload: Mapping[str, Any],
    evidence: tuple[EvidenceItem, ...] = (),
) -> ActionResult:
    status = payload.get("status")
    if status not in STATUSES:
        return _result(
            action,
            candidate,
            FAIL,
            target=target,
            errors=("adapter status is not a known status",),
        )
    try:
        errors = _strings(payload.get("errors"))
        warnings = _strings(payload.get("warnings"))
    except ValueError as exc:
        return _result(action, candidate, FAIL, target=target, errors=(str(exc),))
    artifact = payload.get("artifactSha256")
    if artifact is not None:
        try:
            artifact = _sha256(artifact, "artifactSha256")
        except ValueError as exc:
            return _result(action, candidate, FAIL, target=target, errors=(str(exc),))
    if status == PASS and artifact is None and action == ACTION_BUILD_AND_TEST:
        return _result(
            action,
            candidate,
            FAIL,
            target=target,
            errors=("build passed without an artifact hash",),
        )
    return _result(
        action,
        candidate,
        str(status),
        target=target,
        sdk_version=_optional_text(payload.get("sdkVersion")),
        unity_version=_optional_text(payload.get("unityVersion")),
        errors=errors,
        warnings=warnings,
        artifact_sha256=artifact,
        evidence=evidence,
    )


def vrc_validate_avatar(
    adapter: VrcSdkAdapter, candidate: CandidateBinding, target: TargetIdentity
) -> ActionResult:
    payload, rejected = _run_step(
        ACTION_VALIDATE_AVATAR,
        candidate,
        target,
        lambda: adapter.validate_avatar(candidate, target),
    )
    if rejected is not None:
        return rejected
    return _step_result(ACTION_VALIDATE_AVATAR, candidate, target, payload)


def vrc_build_and_test(
    adapter: VrcSdkAdapter,
    candidate: CandidateBinding,
    target: TargetIdentity,
    validation: ActionResult,
) -> ActionResult:
    """Build & Test runs only after validation passed for the same candidate and target."""
    gate = _prerequisite(validation, candidate, target, "validation")
    if gate is not None:
        return _result(
            ACTION_BUILD_AND_TEST, candidate, gate[0], target=target, errors=(gate[1],)
        )
    payload, rejected = _run_step(
        ACTION_BUILD_AND_TEST,
        candidate,
        target,
        lambda: adapter.build_and_test(candidate, target),
    )
    if rejected is not None:
        return rejected
    return _step_result(ACTION_BUILD_AND_TEST, candidate, target, payload)


def vrc_capture_evidence(
    adapter: VrcSdkAdapter, candidate: CandidateBinding, target: TargetIdentity
) -> ActionResult:
    payload, rejected = _run_step(
        ACTION_CAPTURE_EVIDENCE,
        candidate,
        target,
        lambda: adapter.capture_evidence(candidate, target),
    )
    if rejected is not None:
        return rejected
    evidence, evidence_errors = _evidence_items(payload.get("evidence"), candidate)
    if evidence_errors:
        return _result(
            ACTION_CAPTURE_EVIDENCE,
            candidate,
            BLOCKED,
            target=target,
            errors=evidence_errors,
        )
    return _step_result(
        ACTION_CAPTURE_EVIDENCE, candidate, target, payload, evidence=evidence
    )


def _prerequisite(
    result: ActionResult,
    candidate: CandidateBinding,
    target: TargetIdentity,
    label: str,
) -> tuple[str, str] | None:
    """Return (status, reason) when a prerequisite stops the upload, else None."""
    if (
        result.product_id != candidate.product_id
        or result.candidate_sha256 != candidate.candidate_sha256
    ):
        return BLOCKED, f"{label} result is bound to a different candidate"
    if result.target_id is not None and result.target_id != target.target_id:
        return BLOCKED, f"{label} result is bound to a different target"
    if result.status == PASS:
        return None
    if result.status in NON_EXECUTED:
        return NOT_RUN, f"{label} not executed: {result.status}"
    return BLOCKED, f"{label} did not pass: {result.status}"


def vrc_build_and_upload(
    adapter: VrcSdkAdapter,
    candidate: CandidateBinding,
    target: TargetIdentity | None,
    *,
    validation: ActionResult,
    build_and_test: ActionResult,
    evidence: Sequence[EvidenceItem] = (),
    required_evidence_kinds: Sequence[str] = REQUIRED_UPLOAD_EVIDENCE_KINDS,
) -> ActionResult:
    """Upload only after every gate passes. Success requires an upload.succeeded event."""
    action = ACTION_BUILD_AND_UPLOAD
    if target is None:
        return _result(
            action, candidate, BLOCKED, errors=("explicit target identity is required",)
        )

    for label, prerequisite in (
        ("validation", validation),
        ("build_and_test", build_and_test),
    ):
        gate = _prerequisite(prerequisite, candidate, target, label)
        if gate is not None:
            return _result(action, candidate, gate[0], target=target, errors=(gate[1],))

    for kind in required_evidence_kinds:
        matches = [item for item in evidence if item.kind == kind]
        if not matches:
            return _result(
                action,
                candidate,
                BLOCKED,
                target=target,
                errors=(f"missing evidence: {kind}",),
            )
        for item in matches:
            if item.candidate_sha256 != candidate.candidate_sha256:
                return _result(
                    action,
                    candidate,
                    BLOCKED,
                    target=target,
                    errors=(f"evidence {kind} is bound to a different candidate",),
                )
            if item.status in NON_EXECUTED:
                return _result(
                    action,
                    candidate,
                    NOT_RUN,
                    target=target,
                    errors=(f"evidence {kind} not executed: {item.status}",),
                )
            if item.status != PASS or item.sha256 is None:
                return _result(
                    action,
                    candidate,
                    BLOCKED,
                    target=target,
                    errors=(f"evidence {kind} is not a hash-bound PASS",),
                )

    try:
        event = adapter.build_and_upload(candidate, target)
    except Exception as exc:  # no fallback to success
        return _result(
            action,
            candidate,
            FAIL,
            target=target,
            errors=(f"adapter raised {type(exc).__name__}",),
        )
    if not isinstance(event, AdapterEvent):
        return _result(
            action,
            candidate,
            FAIL,
            target=target,
            errors=("upload returned no adapter event",),
        )

    findings = find_credential_material(
        {
            "name": event.name,
            "candidateSha256": event.candidate_sha256,
            "targetId": event.target_id,
        }
    )
    if findings:
        return _result(
            action,
            candidate,
            BLOCKED,
            target=target,
            errors=("credential-like material in upload event",),
        )
    if event.name == UPLOAD_FAILURE_EVENT:
        return _result(
            action, candidate, FAIL, target=target, errors=("upload failed",)
        )
    if event.name != UPLOAD_SUCCESS_EVENT:
        status = NOT_RUN if event.name == "upload.not_run" else FAIL
        return _result(
            action,
            candidate,
            status,
            target=target,
            errors=(f"upload event is not success: {event.name}",),
        )
    if event.candidate_sha256 != candidate.candidate_sha256:
        return _result(
            action,
            candidate,
            BLOCKED,
            target=target,
            errors=("upload event is bound to a different candidate",),
        )
    if event.target_id != target.target_id:
        return _result(
            action,
            candidate,
            BLOCKED,
            target=target,
            errors=("upload event is bound to a different target",),
        )
    if event.artifact_sha256 is None:
        return _result(
            action,
            candidate,
            FAIL,
            target=target,
            errors=("upload success without an artifact hash",),
        )
    try:
        artifact = _sha256(event.artifact_sha256, "artifact_sha256")
    except ValueError as exc:
        return _result(action, candidate, FAIL, target=target, errors=(str(exc),))
    return _result(action, candidate, PASS, target=target, artifact_sha256=artifact)
