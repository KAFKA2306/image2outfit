"""Auditable source-image sets for the ingest-reference stage."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Mapping

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_EXTENSION = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)+$")


class ReferenceAssetKind(StrEnum):
    ORIGINAL = "original"
    DERIVED = "derived"
    GENERATED = "generated"


class ReferenceView(StrEnum):
    FRONT = "front"
    BACK = "back"
    LEFT = "left"
    RIGHT = "right"
    THREE_QUARTER = "three-quarter"
    DETAIL = "detail"
    UNKNOWN = "unknown"


def _require_identifier(value: str, label: str) -> None:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must be kebab-case: {value!r}")


def _require_repo_path(value: str, label: str) -> None:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be a repository-relative POSIX path")


@dataclass(frozen=True, slots=True)
class ImageTransform:
    operation: str
    parameters: Mapping[str, str | int | float | bool]

    def __post_init__(self) -> None:
        _require_identifier(self.operation, "transform operation")
        for key, value in self.parameters.items():
            _require_identifier(key, "transform parameter")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("transform parameters must be finite")
            if not isinstance(value, (str, int, float, bool)):
                raise ValueError("transform parameters must be scalar JSON values")


@dataclass(frozen=True, slots=True)
class ReferenceAsset:
    asset_id: str
    garment_id: str
    view_id: str
    view: ReferenceView
    kind: ReferenceAssetKind
    path: str
    sha256: str
    acquired_at: str
    license_note: str
    usage_note: str
    source_url: str | None = None
    parent_asset_id: str | None = None
    transforms: tuple[ImageTransform, ...] = ()
    unknown_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for label, value in (
            ("asset_id", self.asset_id),
            ("garment_id", self.garment_id),
            ("view_id", self.view_id),
        ):
            _require_identifier(value, label)
        _require_repo_path(self.path, "reference asset path")
        if not _SHA256.fullmatch(self.sha256):
            raise ValueError("reference asset sha256 must be a lowercase digest")
        try:
            datetime.fromisoformat(self.acquired_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("acquired_at must be ISO 8601") from exc
        if not self.license_note.strip() or not self.usage_note.strip():
            raise ValueError("license_note and usage_note are required")
        if self.kind is ReferenceAssetKind.ORIGINAL:
            if not self.source_url:
                raise ValueError("original assets require source_url")
            if self.parent_asset_id is not None or self.transforms:
                raise ValueError("original assets cannot declare parent transforms")
        else:
            if self.parent_asset_id is None:
                raise ValueError("derived and generated assets require parent_asset_id")
            if not self.transforms:
                raise ValueError("derived and generated assets require transforms")
        if self.parent_asset_id == self.asset_id:
            raise ValueError("reference asset cannot be its own parent")
        if len(self.unknown_fields) != len(set(self.unknown_fields)):
            raise ValueError("unknown_fields must be unique")
        for name in self.unknown_fields:
            _require_identifier(name, "unknown field")

    def verify_file(self, repository_root: str | Path) -> None:
        artifact = Path(repository_root) / self.path
        if not artifact.is_file():
            raise ValueError(f"reference asset is missing: {self.path}")
        actual = hashlib.sha256(artifact.read_bytes()).hexdigest()
        if actual != self.sha256:
            raise ValueError(
                f"reference asset hash mismatch: {actual} != {self.sha256}"
            )


@dataclass(frozen=True, slots=True)
class ReferenceSet:
    reference_set_id: str
    garment_id: str
    assets: tuple[ReferenceAsset, ...]
    extensions: Mapping[str, object] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        _require_identifier(self.reference_set_id, "reference_set_id")
        _require_identifier(self.garment_id, "garment_id")
        if self.schema_version != 1:
            raise ValueError("unsupported ReferenceSet schema_version")
        if not self.assets:
            raise ValueError("ReferenceSet requires at least one asset")
        identifiers = [item.asset_id for item in self.assets]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("reference asset IDs must be unique")
        if any(item.garment_id != self.garment_id for item in self.assets):
            raise ValueError("all reference assets must belong to the same garment")
        by_id = {item.asset_id: item for item in self.assets}
        if not any(item.kind is ReferenceAssetKind.ORIGINAL for item in self.assets):
            raise ValueError("ReferenceSet requires an original asset")
        for asset in self.assets:
            if asset.parent_asset_id is not None:
                parent = by_id.get(asset.parent_asset_id)
                if parent is None:
                    raise ValueError(
                        f"asset {asset.asset_id!r} has an unknown parent"
                    )
                if parent.kind is ReferenceAssetKind.GENERATED:
                    raise ValueError("generated assets cannot be provenance parents")
        for namespace in self.extensions:
            if not _EXTENSION.fullmatch(namespace):
                raise ValueError("ReferenceSet extensions must be namespaced")

    @property
    def downstream_reference_ids(self) -> tuple[str, ...]:
        return tuple(sorted(item.asset_id for item in self.assets))

    @property
    def unknown_fields(self) -> tuple[str, ...]:
        return tuple(
            sorted({name for item in self.assets for name in item.unknown_fields})
        )

    def verify_files(self, repository_root: str | Path) -> None:
        for asset in self.assets:
            asset.verify_file(repository_root)

    def stage_result_evidence(self) -> list[dict[str, str]]:
        return [
            {"path": item.path, "sha256": item.sha256}
            for item in sorted(self.assets, key=lambda asset: asset.asset_id)
        ]
