"""Canonical root contract for versioned garment-domain sections.

The detailed payload of each section is intentionally owned by its dedicated
module. This root contract preserves identity, provenance, units, coordinate
system, hypothesis lineage, and evidence hashes across all pipeline stages.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, Mapping

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_EXTENSION = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)+$")
_SECTION_NAMES = (
    "avatar",
    "construction",
    "fit",
    "materials",
    "styling",
    "quality",
)

JSONScalar = str | int | float | bool | None
JSONValue = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


class UnitSystem(StrEnum):
    MILLIMETRE = "millimetre"


class CoordinateSystem(StrEnum):
    RIGHT_HANDED_Z_UP = "right-handed-z-up"


def _require_identifier(value: str, label: str) -> None:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must be kebab-case: {value!r}")


def _require_sha256(value: str, label: str) -> None:
    if not _SHA256.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 hex digest")


def _require_repo_relative_path(value: str, label: str) -> None:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be a repository-relative POSIX path")


def _reject_unknown(data: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(data).difference(allowed))
    if unknown:
        raise ValueError(f"{label} contains unknown fields: {unknown}")


def _validate_json_value(value: JSONValue, label: str = "value") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{label} must not contain non-finite numbers")
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{label}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{label} object keys must be strings")
            _validate_json_value(item, f"{label}.{key}")
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError(f"{label} is not JSON-compatible")


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    path: str
    sha256: str
    role: str

    def __post_init__(self) -> None:
        _require_repo_relative_path(self.path, "evidence path")
        _require_sha256(self.sha256, "evidence sha256")
        _require_identifier(self.role, "evidence role")

    def to_dict(self) -> dict[str, JSONValue]:
        return {"path": self.path, "sha256": self.sha256, "role": self.role}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvidenceRef":
        _reject_unknown(data, {"path", "sha256", "role"}, "EvidenceRef")
        return cls(
            path=str(data["path"]),
            sha256=str(data["sha256"]),
            role=str(data["role"]),
        )


@dataclass(frozen=True, slots=True)
class SpecSection:
    section_id: str
    schema_version: int
    artifact_path: str
    content_sha256: str
    hypothesis_id: str
    confidence: float
    evidence: tuple[EvidenceRef, ...] = ()

    def __post_init__(self) -> None:
        _require_identifier(self.section_id, "section_id")
        _require_repo_relative_path(self.artifact_path, "artifact_path")
        _require_sha256(self.content_sha256, "content_sha256")
        _require_identifier(self.hypothesis_id, "hypothesis_id")
        if self.schema_version < 1:
            raise ValueError("section schema_version must be positive")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("section confidence must be between 0 and 1")
        evidence_paths = [item.path for item in self.evidence]
        if len(evidence_paths) != len(set(evidence_paths)):
            raise ValueError("section evidence paths must be unique")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "section_id": self.section_id,
            "schema_version": self.schema_version,
            "artifact_path": self.artifact_path,
            "content_sha256": self.content_sha256,
            "hypothesis_id": self.hypothesis_id,
            "confidence": self.confidence,
            "evidence": [item.to_dict() for item in self.evidence],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SpecSection":
        allowed = {
            "section_id",
            "schema_version",
            "artifact_path",
            "content_sha256",
            "hypothesis_id",
            "confidence",
            "evidence",
        }
        _reject_unknown(data, allowed, "SpecSection")
        return cls(
            section_id=str(data["section_id"]),
            schema_version=int(data["schema_version"]),
            artifact_path=str(data["artifact_path"]),
            content_sha256=str(data["content_sha256"]),
            hypothesis_id=str(data["hypothesis_id"]),
            confidence=float(data["confidence"]),
            evidence=tuple(
                EvidenceRef.from_dict(item) for item in data.get("evidence", [])
            ),
        )


@dataclass(frozen=True, slots=True)
class ProvenanceSpec:
    source_reference: str
    source_sha256: str
    producer: str
    evidence: tuple[EvidenceRef, ...] = ()

    def __post_init__(self) -> None:
        if not self.source_reference.strip():
            raise ValueError("source_reference is required")
        _require_sha256(self.source_sha256, "source_sha256")
        if not self.producer.strip():
            raise ValueError("producer is required")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "source_reference": self.source_reference,
            "source_sha256": self.source_sha256,
            "producer": self.producer,
            "evidence": [item.to_dict() for item in self.evidence],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProvenanceSpec":
        _reject_unknown(
            data,
            {"source_reference", "source_sha256", "producer", "evidence"},
            "ProvenanceSpec",
        )
        return cls(
            source_reference=str(data["source_reference"]),
            source_sha256=str(data["source_sha256"]),
            producer=str(data["producer"]),
            evidence=tuple(
                EvidenceRef.from_dict(item) for item in data.get("evidence", [])
            ),
        )


@dataclass(frozen=True, slots=True)
class GarmentSpec:
    garment_id: str
    hypothesis_id: str
    avatar: SpecSection
    construction: SpecSection
    fit: SpecSection
    materials: SpecSection
    styling: SpecSection
    quality: SpecSection
    provenance: ProvenanceSpec
    schema_version: int = 1
    unit_system: UnitSystem = UnitSystem.MILLIMETRE
    coordinate_system: CoordinateSystem = CoordinateSystem.RIGHT_HANDED_Z_UP
    parent_hypothesis_id: str | None = None
    extensions: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_identifier(self.garment_id, "garment_id")
        _require_identifier(self.hypothesis_id, "hypothesis_id")
        if self.parent_hypothesis_id is not None:
            _require_identifier(self.parent_hypothesis_id, "parent_hypothesis_id")
            if self.parent_hypothesis_id == self.hypothesis_id:
                raise ValueError("a hypothesis cannot be its own parent")
        if self.schema_version != 1:
            raise ValueError("unsupported garment schema_version")

        for expected_name, section in self.sections.items():
            if section.section_id != expected_name:
                raise ValueError(
                    f"section {expected_name!r} must use section_id {expected_name!r}"
                )
            if section.hypothesis_id != self.hypothesis_id:
                raise ValueError(
                    f"section {expected_name!r} belongs to another hypothesis"
                )

        for namespace, value in self.extensions.items():
            if not _EXTENSION.fullmatch(namespace):
                raise ValueError(
                    "extension keys must be namespaced, for example "
                    f"'image2outfit.example': {namespace!r}"
                )
            _validate_json_value(value, f"extensions.{namespace}")

    @property
    def sections(self) -> dict[str, SpecSection]:
        return {
            "avatar": self.avatar,
            "construction": self.construction,
            "fit": self.fit,
            "materials": self.materials,
            "styling": self.styling,
            "quality": self.quality,
        }

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "schema_version": self.schema_version,
            "garment_id": self.garment_id,
            "hypothesis_id": self.hypothesis_id,
            "parent_hypothesis_id": self.parent_hypothesis_id,
            "unit_system": self.unit_system.value,
            "coordinate_system": self.coordinate_system.value,
            **{name: section.to_dict() for name, section in self.sections.items()},
            "provenance": self.provenance.to_dict(),
            "extensions": dict(self.extensions),
        }

    def to_json(self, *, indent: int = 2) -> str:
        return (
            json.dumps(
                self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True
            )
            + "\n"
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GarmentSpec":
        allowed = {
            "schema_version",
            "garment_id",
            "hypothesis_id",
            "parent_hypothesis_id",
            "unit_system",
            "coordinate_system",
            *_SECTION_NAMES,
            "provenance",
            "extensions",
        }
        _reject_unknown(data, set(allowed), "GarmentSpec")
        missing = sorted(
            {
                "schema_version",
                "garment_id",
                "hypothesis_id",
                "unit_system",
                "coordinate_system",
                *_SECTION_NAMES,
                "provenance",
                "extensions",
            }.difference(data)
        )
        if missing:
            raise ValueError(f"GarmentSpec is missing required fields: {missing}")
        return cls(
            schema_version=int(data["schema_version"]),
            garment_id=str(data["garment_id"]),
            hypothesis_id=str(data["hypothesis_id"]),
            parent_hypothesis_id=(
                None
                if data.get("parent_hypothesis_id") is None
                else str(data["parent_hypothesis_id"])
            ),
            unit_system=UnitSystem(str(data["unit_system"])),
            coordinate_system=CoordinateSystem(str(data["coordinate_system"])),
            avatar=SpecSection.from_dict(data["avatar"]),
            construction=SpecSection.from_dict(data["construction"]),
            fit=SpecSection.from_dict(data["fit"]),
            materials=SpecSection.from_dict(data["materials"]),
            styling=SpecSection.from_dict(data["styling"]),
            quality=SpecSection.from_dict(data["quality"]),
            provenance=ProvenanceSpec.from_dict(data["provenance"]),
            extensions=dict(data["extensions"]),
        )

    @classmethod
    def from_json(cls, content: str) -> "GarmentSpec":
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("GarmentSpec JSON root must be an object")
        return cls.from_dict(parsed)
