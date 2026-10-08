#!/usr/bin/env python3
"""Evaluate tracked GenWorks ProductManifest completion deterministically.

The gate intentionally covers only the completion scope declared by
``config/genworks-handoff-policy.json``. Runtime/release checks that the policy
marks out of scope are reported but never promoted into completion evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PASS = "PASS"
FAIL = "FAIL"
UNVERIFIED = "UNVERIFIED"
EXIT_CODES = {PASS: 0, FAIL: 1, UNVERIFIED: 2}
ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _resolve_evidence_path(root: Path, product_root: Path, value: str) -> Path:
    raw = Path(value)
    if raw.is_absolute():
        return raw
    repo_candidate = root / raw
    if repo_candidate.exists():
        return repo_candidate
    return product_root / raw


def _gate_evidence(
    gate: str, manifest: dict[str, Any], root: Path, product_root: Path
) -> list[str]:
    outputs = manifest.get("outputs")
    outputs = outputs if isinstance(outputs, dict) else {}
    mapping = {
        "blender": ["blend"],
        "editableSource": ["blend"],
        "fbx": ["fbx"],
        "prefabDeclared": ["prefab", "integratedPrefab"],
        "fiveViewEvidence": ["multiview"],
        "poseEvidence": ["poseReview"],
    }
    paths: list[str] = []
    for key in mapping.get(gate, []):
        value = outputs.get(key)
        if isinstance(value, str) and value.strip():
            resolved = _resolve_evidence_path(root, product_root, value)
            if resolved.is_file():
                paths.append(
                    str(resolved.relative_to(root))
                    if root in resolved.parents
                    else str(resolved)
                )

    if gate == "visualAppearanceReview":
        review = manifest.get("visualAppearanceReview")
        if isinstance(review, dict):
            evidence = review.get("evidence")
            if isinstance(evidence, dict):
                for value in evidence.values():
                    if not isinstance(value, str) or not value.strip():
                        continue
                    resolved = _resolve_evidence_path(root, product_root, value)
                    if resolved.is_file():
                        paths.append(
                            str(resolved.relative_to(root))
                            if root in resolved.parents
                            else str(resolved)
                        )
    return list(dict.fromkeys(paths))


def evaluate_manifest(
    manifest: dict[str, Any], policy: dict[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    required = policy.get("requiredCompletionGates")
    if (
        not isinstance(required, list)
        or not required
        or not all(isinstance(x, str) for x in required)
    ):
        raise ValueError(
            "policy.requiredCompletionGates must be a non-empty string array"
        )

    product_root_value = manifest.get("productRoot")
    if not isinstance(product_root_value, str) or not product_root_value.strip():
        raise ValueError("ProductManifest.productRoot must be a non-empty string")
    product_root = (root / product_root_value).resolve()
    if root != product_root and root not in product_root.parents:
        raise ValueError("ProductManifest.productRoot escapes repository")

    technical = manifest.get("technicalGates")
    technical = technical if isinstance(technical, dict) else {}
    rows: list[dict[str, Any]] = []
    has_fail = False
    has_unverified = False

    for gate in required:
        raw_status = technical.get(gate)
        if gate == "visualAppearanceReview":
            review = manifest.get("visualAppearanceReview")
            if isinstance(review, dict) and isinstance(review.get("result"), str):
                raw_status = review["result"]

        evidence = _gate_evidence(gate, manifest, root, product_root)
        if raw_status == FAIL:
            status = FAIL
            has_fail = True
        elif raw_status == PASS and evidence:
            status = PASS
        else:
            status = UNVERIFIED
            has_unverified = True

        reasons: list[str] = []
        if raw_status not in {PASS, FAIL}:
            reasons.append(f"required gate status is not PASS/FAIL: {raw_status!r}")
        if raw_status == PASS and not evidence:
            reasons.append("required PASS gate has no existing evidence")
        rows.append(
            {
                "id": gate,
                "declaredStatus": raw_status,
                "status": status,
                "evidence": evidence,
                "reasons": reasons,
            }
        )

    if has_fail:
        overall = FAIL
    elif has_unverified:
        overall = UNVERIFIED
    else:
        overall = PASS

    return {
        "schemaVersion": 1,
        "productId": manifest.get("productId"),
        "gateStatus": overall,
        "completionStatus": policy.get("completionStatus", "COMPLETE")
        if overall == PASS
        else None,
        "requiredGates": rows,
        "outOfScopeGates": list(policy.get("outOfScopeGates", [])),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a GenWorks ProductManifest completion gate"
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--policy",
        type=Path,
        default=ROOT / "config" / "genworks-handoff-policy.json",
    )
    args = parser.parse_args(argv)
    try:
        manifest = _read_json(args.manifest)
        policy = _read_json(args.policy)
        result = evaluate_manifest(manifest, policy)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(
            json.dumps(
                {"gateStatus": UNVERIFIED, "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return EXIT_CODES[UNVERIFIED]
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return EXIT_CODES[result["gateStatus"]]


if __name__ == "__main__":
    sys.exit(main())
