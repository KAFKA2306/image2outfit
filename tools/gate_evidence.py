#!/usr/bin/env python3
"""Keep PASS and VERIFIED GenWorks gates tied to evidence that exists on disk.

A gate may stay PASS or VERIFIED only when every evidence file it claims exists
and, for hashed evidence, matches its recorded SHA-256. Claims come from:

- fiveViewEvidence / fiveViewRender: the canonical preview PNG for each view in
  config/release-policy.json (minimumPreview.requiredViews);
- poseEvidence / poseRender: the canonical pose PNG for each pose in
  config/release-policy.json (requiredPoses);
- output-backed gates: the manifest paths listed in OUTPUT_CLAIMS;
- releaseReadiness entries that carry evidencePath and evidenceSha256.

Completion gates required by config/genworks-handoff-policy.json must also claim
at least one evidence file, as product_manifest_gate.py already requires.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

# Deliberately not importing contract_io: its write path pulls in the
# product_manifest_state chain, which breaks the product import-depth audit.
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ROOT = Path(__file__).resolve().parents[1]
PASS = "PASS"
UNVERIFIED = "UNVERIFIED"
PASSING = ("PASS", "VERIFIED")
VIEW_GATES = ("fiveViewEvidence", "fiveViewRender")
POSE_GATES = ("poseEvidence", "poseRender")
# Gate -> manifest field paths whose string values are that gate's evidence.
OUTPUT_CLAIMS: dict[str, tuple[tuple[str, ...], ...]] = {
    "blender": (("outputs", "blend"),),
    "editableSource": (("outputs", "blend"),),
    "fbx": (("outputs", "fbx"),),
    "prefabDeclared": (
        ("outputs", "prefab"),
        ("outputs", "integratedPrefab"),
        ("outfitPrefabPath",),
        ("integratedPrefabPath",),
    ),
    "clothSimulation": (("outputs", "clothSimulation"), ("clothSimulation",)),
    "unityImport": (("outputs", "unityValidation"),),
    "modularAvatar": (("outputs", "unityValidation"),),
    "ndmf": (("outputs", "ndmfBakedPrefab"),),
}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _repo_path(root: Path, value: str) -> Path:
    candidate = (root / value).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError(f"path escapes repository: {value}")
    return candidate


def load_policies(root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (handoff policy, release policy) read from the tracked config."""
    handoff = _read_json(root / "config" / "genworks-handoff-policy.json")
    release = _read_json(root / "config" / "release-policy.json")
    return handoff, release


def canonical_view_paths(product_root: str, release: dict[str, Any]) -> list[str]:
    views = release["minimumPreview"]["requiredViews"]
    return [f"{product_root}/Previews/{view}.png" for view in views]


def canonical_pose_paths(product_root: str, release: dict[str, Any]) -> list[str]:
    poses = release["requiredPoses"]
    if not isinstance(poses, list) or not poses:
        raise ValueError("release-policy.requiredPoses must be a non-empty list")
    return [f"{product_root}/Previews/Poses/{pose}.png" for pose in poses]


def _dig(manifest: dict[str, Any], keys: tuple[str, ...]) -> Any:
    value: Any = manifest
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def claims_for(
    gate: str, manifest: dict[str, Any], release: dict[str, Any]
) -> list[str]:
    product_root = str(manifest.get("productRoot", ""))
    if gate in VIEW_GATES:
        return canonical_view_paths(product_root, release)
    if gate in POSE_GATES:
        return canonical_pose_paths(product_root, release)
    claims: list[str] = []
    for keys in OUTPUT_CLAIMS.get(gate, ()):
        value = _dig(manifest, keys)
        if isinstance(value, str) and value.strip():
            claims.append(value)
    return list(dict.fromkeys(claims))


def _existing(root: Path, value: str) -> Path | None:
    try:
        path = _repo_path(root, value)
    except ValueError:
        return None
    return path if path.is_file() else None


def _gate_row(
    root: Path,
    section: str,
    gate: str,
    declared: str,
    claims: list[str],
    required: bool,
) -> dict[str, Any] | None:
    missing = [value for value in claims if _existing(root, value) is None]
    reasons = [f"claimed evidence is missing: {value}" for value in missing]
    if required and section == "completionGates" and not claims:
        reasons.append("required completion gate PASS claims no evidence")
    if not reasons:
        return None
    return {
        "section": section,
        "gate": gate,
        "declared": declared,
        "missing": missing,
        "reasons": reasons,
    }


def _hashed_row(root: Path, name: str, entry: dict[str, Any]) -> dict[str, Any] | None:
    value = entry.get("evidencePath")
    expected = entry.get("evidenceSha256")
    path = _existing(root, value) if isinstance(value, str) else None
    reasons: list[str] = []
    if path is None:
        reasons.append(f"claimed evidence is missing: {value}")
    if not isinstance(expected, str) or not SHA256.fullmatch(expected):
        reasons.append("evidenceSha256 must be a lowercase SHA-256")
    elif path is not None and _digest(path) != expected:
        reasons.append(f"evidenceSha256 mismatch: {value}")
    if not reasons:
        return None
    return {
        "section": "releaseReadiness",
        "gate": name,
        "declared": entry.get("status"),
        "missing": [value] if path is None and isinstance(value, str) else [],
        "reasons": reasons,
    }


def violations(
    manifest: dict[str, Any],
    handoff: dict[str, Any],
    release: dict[str, Any],
    root: Path = ROOT,
) -> list[dict[str, Any]]:
    """Return one row per PASS/VERIFIED gate whose claimed evidence is not on disk."""
    required = set(handoff.get("requiredCompletionGates", []))
    rows: list[dict[str, Any]] = []
    for section in ("completionGates", "technicalGates"):
        gates = manifest.get(section)
        if not isinstance(gates, dict):
            continue
        for gate, declared in gates.items():
            if declared not in PASSING:
                continue
            row = _gate_row(
                root,
                section,
                gate,
                declared,
                claims_for(gate, manifest, release),
                gate in required,
            )
            if row:
                rows.append(row)
    readiness = manifest.get("releaseReadiness")
    if isinstance(readiness, dict):
        for name, entry in readiness.items():
            if (
                isinstance(entry, dict)
                and entry.get("status") in PASSING
                and "evidencePath" in entry
            ):
                row = _hashed_row(root, f"releaseReadiness.{name}", entry)
                if row:
                    rows.append(row)
    return rows


def _status(root: Path, claims: list[str]) -> str:
    if claims and all(_existing(root, value) is not None for value in claims):
        return PASS
    return UNVERIFIED


def view_gate_status(root: Path, product_root: str) -> str:
    """Value a build script may record for fiveViewEvidence: PASS only if all views exist."""
    release = load_policies(root)[1]
    return _status(root, canonical_view_paths(product_root, release))


def pose_gate_status(root: Path, product_root: str) -> str:
    """Value a build script may record for poseEvidence: PASS only if all poses exist."""
    release = load_policies(root)[1]
    return _status(root, canonical_pose_paths(product_root, release))
