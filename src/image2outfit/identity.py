"""Product identity claims and append-only evidence for ingest-reference."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

_PRODUCT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_EVIDENCE_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class IdentityStatus(StrEnum):
    VERIFIED = "VERIFIED"
    CANDIDATE = "CANDIDATE"
    UNVERIFIED = "UNVERIFIED"
    REJECTED = "REJECTED"


class IdentityField(StrEnum):
    MANUFACTURER = "manufacturer"
    BRAND = "brand"
    SELLER = "seller"
    OFFICIAL_PRODUCT_NAME = "officialProductName"
    MODEL_NUMBER = "modelNumber"
    SELLER_SKU = "sellerSku"
    GTIN = "gtin"
    JAN = "jan"
    COLOR_CODE = "colorCode"
    SIZE_CODE = "sizeCode"
    SEASON = "season"
    REVISION = "revision"


MARKET_IDENTIFIER_FIELDS = frozenset(
    {
        IdentityField.MODEL_NUMBER,
        IdentityField.SELLER_SKU,
        IdentityField.GTIN,
        IdentityField.JAN,
    }
)


def _require_iso8601(value: str, label: str) -> None:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be ISO 8601") from exc


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _valid_gtin(value: str, lengths: tuple[int, ...]) -> bool:
    if len(value) not in lengths or not value.isdigit():
        return False
    digits = [int(character) for character in value]
    total = 0
    for offset, digit in enumerate(reversed(digits[:-1]), start=1):
        total += digit * (3 if offset % 2 else 1)
    check_digit = (10 - total % 10) % 10
    return check_digit == digits[-1]


@dataclass(frozen=True, slots=True)
class IdentityEvidence:
    evidence_id: str
    evidence_type: str
    source_reference: str
    captured_at: str
    extraction_method: str
    reviewer_role: str
    image_region_px: tuple[int, int, int, int] | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if not _EVIDENCE_ID.fullmatch(self.evidence_id):
            raise ValueError("evidence_id must be kebab-case")
        for label, value in (
            ("evidence_type", self.evidence_type),
            ("source_reference", self.source_reference),
            ("extraction_method", self.extraction_method),
            ("reviewer_role", self.reviewer_role),
        ):
            if not value.strip():
                raise ValueError(f"{label} is required")
        _require_iso8601(self.captured_at, "captured_at")
        if self.image_region_px is not None:
            x, y, width, height = self.image_region_px
            if min(x, y) < 0 or min(width, height) <= 0:
                raise ValueError(
                    "image_region_px must contain non-negative x/y and positive size"
                )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "evidenceId": self.evidence_id,
            "evidenceType": self.evidence_type,
            "sourceReference": self.source_reference,
            "capturedAt": self.captured_at,
            "extractionMethod": self.extraction_method,
            "reviewerRole": self.reviewer_role,
            "imageRegionPx": list(self.image_region_px) if self.image_region_px else None,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class IdentityClaim:
    field: IdentityField
    status: IdentityStatus
    value: str | None
    reason: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError(f"identity claim {self.field.value} requires a reason")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("identity claim evidence_ids must be unique")
        for evidence_id in self.evidence_ids:
            if not _EVIDENCE_ID.fullmatch(evidence_id):
                raise ValueError("identity claim evidence_id must be kebab-case")
        if self.status is IdentityStatus.UNVERIFIED:
            if self.value is not None:
                raise ValueError("UNVERIFIED identity claims must not contain a value")
            return
        if self.value is None or not self.value.strip():
            raise ValueError(f"{self.status.value} identity claims require a value")
        if not self.evidence_ids:
            raise ValueError(f"{self.status.value} identity claims require evidence")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "field": self.field.value,
            "status": self.status.value,
            "value": self.value,
            "reason": self.reason,
            "evidenceIds": list(self.evidence_ids),
        }


@dataclass(frozen=True, slots=True)
class IdentityHistoryEvent:
    sequence: int
    field: IdentityField
    status: IdentityStatus
    value: str | None
    reason: str
    evidence_ids: tuple[str, ...]
    actor_role: str
    recorded_at: str
    previous_digest: str
    event_digest: str

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("identity history sequence must be positive")
        if not self.reason.strip() or not self.actor_role.strip():
            raise ValueError("identity history reason and actor_role are required")
        _require_iso8601(self.recorded_at, "recorded_at")
        if not _DIGEST.fullmatch(self.previous_digest) or not _DIGEST.fullmatch(
            self.event_digest
        ):
            raise ValueError("identity history digests must be lowercase SHA-256")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("identity history evidence_ids must be unique")
        if self.status is IdentityStatus.UNVERIFIED and self.value is not None:
            raise ValueError("UNVERIFIED history events must not contain a value")
        if self.status is not IdentityStatus.UNVERIFIED and (
            self.value is None or not self.value.strip()
        ):
            raise ValueError(f"{self.status.value} history events require a value")

    def digest_payload(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "field": self.field.value,
            "status": self.status.value,
            "value": self.value,
            "reason": self.reason,
            "evidenceIds": list(self.evidence_ids),
            "actorRole": self.actor_role,
            "recordedAt": self.recorded_at,
            "previousDigest": self.previous_digest,
        }

    def to_mapping(self) -> dict[str, Any]:
        return {**self.digest_payload(), "eventDigest": self.event_digest}


def make_identity_history_event(
    *,
    sequence: int,
    field: IdentityField,
    status: IdentityStatus,
    value: str | None,
    reason: str,
    evidence_ids: tuple[str, ...],
    actor_role: str,
    recorded_at: str,
    previous_digest: str,
) -> IdentityHistoryEvent:
    payload = {
        "sequence": sequence,
        "field": field.value,
        "status": status.value,
        "value": value,
        "reason": reason,
        "evidenceIds": list(evidence_ids),
        "actorRole": actor_role,
        "recordedAt": recorded_at,
        "previousDigest": previous_digest,
    }
    return IdentityHistoryEvent(
        sequence=sequence,
        field=field,
        status=status,
        value=value,
        reason=reason,
        evidence_ids=evidence_ids,
        actor_role=actor_role,
        recorded_at=recorded_at,
        previous_digest=previous_digest,
        event_digest=_digest(payload),
    )


@dataclass(frozen=True, slots=True)
class ReferenceIdentityManifest:
    product_id: str
    source_reference: str
    claims: tuple[IdentityClaim, ...]
    evidence: tuple[IdentityEvidence, ...]
    history: tuple[IdentityHistoryEvent, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported ReferenceIdentityManifest schema_version")
        if not _PRODUCT_ID.fullmatch(self.product_id):
            raise ValueError("product_id must be a repository product identifier")
        if not self.source_reference.strip():
            raise ValueError("source_reference is required")
        fields = [claim.field for claim in self.claims]
        expected_fields = set(IdentityField)
        if set(fields) != expected_fields or len(fields) != len(expected_fields):
            raise ValueError("identity claims must contain every field exactly once")
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("identity evidence IDs must be unique")
        known_evidence = set(evidence_ids)
        for claim in self.claims:
            missing = set(claim.evidence_ids) - known_evidence
            if missing:
                raise ValueError(
                    f"identity claim references unknown evidence: {sorted(missing)}"
                )
            if (
                claim.field in MARKET_IDENTIFIER_FIELDS
                and claim.value is not None
                and claim.value.casefold() == self.product_id.casefold()
            ):
                raise ValueError("internal product_id cannot be a market identifier")
            if claim.status in {IdentityStatus.VERIFIED, IdentityStatus.CANDIDATE}:
                if claim.field is IdentityField.GTIN and not _valid_gtin(
                    claim.value or "", (8, 12, 13, 14)
                ):
                    raise ValueError("GTIN claim has an invalid format or check digit")
                if claim.field is IdentityField.JAN and not _valid_gtin(
                    claim.value or "", (8, 13)
                ):
                    raise ValueError("JAN claim has an invalid format or check digit")
        self._validate_history(known_evidence)

    def _validate_history(self, known_evidence: set[str]) -> None:
        previous = "0" * 64
        latest: dict[IdentityField, IdentityHistoryEvent] = {}
        for expected_sequence, event in enumerate(self.history, start=1):
            if event.sequence != expected_sequence:
                raise ValueError("identity history sequence must be contiguous")
            if event.previous_digest != previous:
                raise ValueError("identity history previous digest mismatch")
            if event.event_digest != _digest(event.digest_payload()):
                raise ValueError("identity history event digest mismatch")
            missing = set(event.evidence_ids) - known_evidence
            if missing:
                raise ValueError(
                    f"identity history references unknown evidence: {sorted(missing)}"
                )
            previous = event.event_digest
            latest[event.field] = event
        if set(latest) != set(IdentityField):
            raise ValueError("identity history must assess every identity field")
        claims = {claim.field: claim for claim in self.claims}
        for field, event in latest.items():
            claim = claims[field]
            if (
                event.status is not claim.status
                or event.value != claim.value
                or event.evidence_ids != claim.evidence_ids
            ):
                raise ValueError(f"identity history is stale for {field.value}")

    @property
    def status_summary(self) -> dict[str, int]:
        return {
            status.value: sum(claim.status is status for claim in self.claims)
            for status in IdentityStatus
        }

    @property
    def verified_market_identifiers(self) -> dict[str, str]:
        return {
            claim.field.value: claim.value
            for claim in self.claims
            if claim.field in MARKET_IDENTIFIER_FIELDS
            and claim.status is IdentityStatus.VERIFIED
            and claim.value is not None
        }

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "productId": self.product_id,
            "sourceReference": self.source_reference,
            "claims": [claim.to_mapping() for claim in self.claims],
            "evidence": [item.to_mapping() for item in self.evidence],
            "history": [event.to_mapping() for event in self.history],
        }

    @property
    def manifest_digest(self) -> str:
        return _digest(self.to_mapping())

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ReferenceIdentityManifest":
        claims = tuple(
            IdentityClaim(
                field=IdentityField(item["field"]),
                status=IdentityStatus(item["status"]),
                value=item.get("value"),
                reason=str(item["reason"]),
                evidence_ids=tuple(item.get("evidenceIds", ())),
            )
            for item in payload.get("claims", ())
        )
        evidence = tuple(
            IdentityEvidence(
                evidence_id=str(item["evidenceId"]),
                evidence_type=str(item["evidenceType"]),
                source_reference=str(item["sourceReference"]),
                captured_at=str(item["capturedAt"]),
                extraction_method=str(item["extractionMethod"]),
                reviewer_role=str(item["reviewerRole"]),
                image_region_px=(
                    tuple(int(value) for value in item["imageRegionPx"])
                    if item.get("imageRegionPx") is not None
                    else None
                ),
                note=str(item.get("note", "")),
            )
            for item in payload.get("evidence", ())
        )
        history = tuple(
            IdentityHistoryEvent(
                sequence=int(item["sequence"]),
                field=IdentityField(item["field"]),
                status=IdentityStatus(item["status"]),
                value=item.get("value"),
                reason=str(item["reason"]),
                evidence_ids=tuple(item.get("evidenceIds", ())),
                actor_role=str(item["actorRole"]),
                recorded_at=str(item["recordedAt"]),
                previous_digest=str(item["previousDigest"]),
                event_digest=str(item["eventDigest"]),
            )
            for item in payload.get("history", ())
        )
        return cls(
            schema_version=int(payload.get("schemaVersion", 0)),
            product_id=str(payload["productId"]),
            source_reference=str(payload["sourceReference"]),
            claims=claims,
            evidence=evidence,
            history=history,
        )


def load_reference_identity(path: str | Path) -> ReferenceIdentityManifest:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("reference identity manifest must be a JSON object")
    return ReferenceIdentityManifest.from_mapping(payload)
