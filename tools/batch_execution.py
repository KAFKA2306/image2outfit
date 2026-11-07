#!/usr/bin/env python3
"""Batch orchestration over the canonical per-product execution wrapper."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from image2outfit.batch import BatchManifest, summarize

import runtime_paths


EXECUTOR = "run_product_execution.py"
STATE_NAME = "product-execution-state.json"


def _repo_path(root: Path, value: str | Path, *, label: str) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    root = root.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"{label} escapes repository: {value}")
    return resolved


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def load_manifest(root: Path, path: str | Path) -> BatchManifest:
    manifest_path = _repo_path(root, path, label="batch manifest")
    return BatchManifest.from_mapping(
        _read_object(manifest_path, label="batch manifest")
    )


def _request_identity(root: Path, request_text: str) -> tuple[Path, str]:
    request_path = _repo_path(root, request_text, label="batch request")
    if not request_path.is_file():
        raise FileNotFoundError(f"batch request not found: {request_text}")
    request = _read_object(request_path, label="pipeline request")
    product_id = request.get("productId")
    if not isinstance(product_id, str) or not product_id:
        raise ValueError(f"pipeline request productId is required: {request_text}")
    return request_path, product_id


def _no_state(
    request: str,
    *,
    product_id: str = "",
    scheduler_state: str = "NO_STATE",
    return_code: int = 0,
) -> dict[str, Any]:
    return {
        "request": request,
        "productId": product_id,
        "schedulerState": scheduler_state,
        "currentStage": "",
        "cachedTerminal": False,
        "returnCode": return_code,
    }


def read_request_state(root: Path, request_text: str) -> dict[str, Any]:
    try:
        _request_path, product_id = _request_identity(root, request_text)
    except (OSError, ValueError, json.JSONDecodeError):
        return _no_state(
            request_text,
            scheduler_state="BLOCKED",
            return_code=2,
        )

    state_path = runtime_paths.for_product(root, product_id).reports / STATE_NAME
    if not state_path.is_file():
        return _no_state(request_text, product_id=product_id)

    try:
        state = _read_object(state_path, label="product execution state")
    except (OSError, ValueError, json.JSONDecodeError):
        return _no_state(
            request_text,
            product_id=product_id,
            scheduler_state="BLOCKED",
            return_code=2,
        )

    if state.get("productId") != product_id:
        return _no_state(
            request_text,
            product_id=product_id,
            scheduler_state="BLOCKED",
            return_code=2,
        )

    return {
        "request": request_text,
        "productId": product_id,
        "schedulerState": str(state.get("schedulerState") or "BLOCKED"),
        "currentStage": str(state.get("currentStage") or ""),
        "cachedTerminal": bool(state.get("cachedTerminal", False)),
        "returnCode": 0,
    }


def execute_request(root: Path, request_text: str) -> dict[str, Any]:
    try:
        request_path, product_id = _request_identity(root, request_text)
    except (OSError, ValueError, json.JSONDecodeError):
        return _no_state(
            request_text,
            scheduler_state="BLOCKED",
            return_code=2,
        )

    tools = root / "tools"
    completed = subprocess.run(
        [
            sys.executable,
            str(tools / EXECUTOR),
            "--request",
            str(request_path),
        ],
        cwd=root,
        check=False,
    )
    item = read_request_state(root, request_text)
    item["productId"] = product_id
    item["returnCode"] = completed.returncode

    if item["schedulerState"] == "NO_STATE":
        item["schedulerState"] = "FAILED" if completed.returncode else "BLOCKED"
    return item


def run_batch(
    root: Path,
    manifest_path: str | Path,
    *,
    execute: bool,
) -> tuple[dict[str, Any], int]:
    manifest = load_manifest(root, manifest_path)

    items = [
        execute_request(root, request) if execute else read_request_state(root, request)
        for request in manifest.requests
    ]
    report = summarize(manifest, items)
    return_code = {
        "SUCCEEDED": 0,
        "REVIEW_REQUIRED": 2,
        "FAILED": 1,
    }[report["status"]]
    return report, return_code
