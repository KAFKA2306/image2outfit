"""Validation for reopened Blender cloth-cache evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _hash(value: object, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def validate_reopened_cloth_evidence(
    cloth_report: Mapping[str, Any],
    reopened: Mapping[str, Any],
) -> dict[str, Any]:
    applicability = cloth_report.get("applicability")
    if applicability not in {"REQUIRED", "NOT_REQUIRED"}:
        raise ValueError("cloth applicability is invalid")
    if reopened.get("schemaVersion") != 1:
        raise ValueError("reopened cloth evidence schemaVersion must be 1")
    if reopened.get("productId") != cloth_report.get("productId"):
        raise ValueError("reopened cloth evidence product identity mismatch")
    if reopened.get("applicability") != applicability:
        raise ValueError("reopened cloth applicability mismatch")

    if applicability == "NOT_REQUIRED":
        if reopened.get("objects") not in ([], None):
            raise ValueError("NOT_REQUIRED cloth evidence must not contain objects")
        return {
            "applicability": applicability,
            "objectCount": 0,
            "reopenValidated": True,
        }

    expected_snapshot = _hash(
        cloth_report.get("cacheSnapshotSha256"),
        label="cloth report cacheSnapshotSha256",
    )
    if _hash(
        reopened.get("cacheSnapshotSha256"),
        label="reopened cacheSnapshotSha256",
    ) != expected_snapshot:
        raise ValueError("reopened cloth snapshot hash mismatch")

    expected_contracts = cloth_report.get("contracts")
    actual_objects = reopened.get("objects")
    if not isinstance(expected_contracts, list) or not expected_contracts:
        raise ValueError("required cloth report contracts are missing")
    if not isinstance(actual_objects, list) or not actual_objects:
        raise ValueError("reopened cloth objects are missing")

    expected = {}
    for index, contract in enumerate(expected_contracts):
        if not isinstance(contract, Mapping):
            raise ValueError(f"cloth report contract {index} must be an object")
        name = contract.get("object")
        if not isinstance(name, str) or not name:
            raise ValueError(f"cloth report contract {index} object is required")
        frames = contract.get("frameMeshSha256")
        if not isinstance(frames, Mapping) or len(frames) < 3:
            raise ValueError(f"cloth report contract {name} frame hashes are incomplete")
        expected[name] = {
            str(frame): _hash(digest, label=f"{name} frame {frame}")
            for frame, digest in frames.items()
        }

    actual = {}
    for index, item in enumerate(actual_objects):
        if not isinstance(item, Mapping):
            raise ValueError(f"reopened cloth object {index} must be an object")
        name = item.get("object")
        if not isinstance(name, str) or not name:
            raise ValueError(f"reopened cloth object {index} name is required")
        if item.get("cacheBakedActual") is not True:
            raise ValueError(f"reopened cloth cache is not baked: {name}")
        if item.get("finiteGeometry") is not True:
            raise ValueError(f"reopened cloth geometry is not finite: {name}")
        bounds_extent = item.get("maximumExtentM")
        if not isinstance(bounds_extent, (int, float)) or not 0 < bounds_extent < 10:
            raise ValueError(f"reopened cloth geometry bounds are invalid: {name}")
        frames = item.get("frameMeshSha256")
        if not isinstance(frames, Mapping):
            raise ValueError(f"reopened cloth frame hashes are missing: {name}")
        actual[name] = {
            str(frame): _hash(digest, label=f"{name} reopened frame {frame}")
            for frame, digest in frames.items()
        }

    if set(actual) != set(expected):
        raise ValueError("reopened cloth object set does not match build report")
    for name, frames in expected.items():
        if actual[name] != frames:
            raise ValueError(f"reopened cloth frame hash mismatch: {name}")

    return {
        "applicability": applicability,
        "objectCount": len(actual),
        "reopenValidated": True,
        "cacheSnapshotSha256": expected_snapshot,
    }
