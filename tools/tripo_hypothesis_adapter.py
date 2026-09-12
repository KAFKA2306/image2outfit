#!/usr/bin/env python3
"""Execute an opt-in Tripo multi-view draft as an initialize-3d hypothesis."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from image2outfit.hypothesis_contracts import (
    validate_blueprint,
    validate_hypothesis_set,
    validate_target_avatar_authority,
)
from image2outfit.tripo_adapter import (
    TERMINAL_STATUSES,
    build_hypothesis_set,
    build_multiview_task,
    build_provenance,
    validate_multiview_request,
)

API_ROOT = "https://api.tripo3d.ai/v2/openapi"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    return parser.parse_args()


def repo_path(value: str | Path, *, label: str) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise ValueError(f"{label} escapes repository: {value}")
    return resolved


def read_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def api_json(
    method: str,
    endpoint: str,
    *,
    api_key: str,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    data = None
    headers = {"Authorization": f"Bearer {api_key}"}
    if payload is not None:
        data = json.dumps(dict(payload)).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{API_ROOT}{endpoint}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Tripo HTTP {exc.code}: {detail[:500]}") from exc
    if not isinstance(body, dict) or body.get("code") != 0:
        raise RuntimeError(f"Tripo API rejected request: {body}")
    result = body.get("data")
    if not isinstance(result, dict):
        raise RuntimeError("Tripo API response data is missing")
    return result


def download_file(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with (
        urllib.request.urlopen(url, timeout=60) as response,
        temporary.open("wb") as output,
    ):
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            output.write(block)
    if temporary.stat().st_size == 0:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("Tripo model download was empty")
    temporary.replace(path)


def write_failed_result(
    result_path: Path,
    *,
    product_id: str,
    failure_reason: str,
    task_id: str | None = None,
) -> None:
    write_json(
        result_path,
        {
            "schemaVersion": 1,
            "stage": "initialize-3d",
            "productId": product_id,
            "status": "FAILED",
            "evidence": [],
            "taskId": task_id,
            "failureReason": failure_reason,
            "externalDraftCanonicalSource": False,
            "silentFallbackUsed": False,
        },
    )


def execute(args: argparse.Namespace) -> int:
    request_path = repo_path(args.request, label="request")
    result_path = repo_path(args.result, label="result")
    runtime_root = (ROOT / ".image2outfit").resolve()
    if result_path != runtime_root and runtime_root not in result_path.parents:
        raise ValueError("result must be inside .image2outfit runtime state")

    raw_request = read_object(request_path, "Tripo request")
    request = validate_multiview_request(raw_request)
    product_id = request["productId"]

    blueprint_path = repo_path(request["blueprintPath"], label="blueprint")
    authority_path = repo_path(
        request["targetAvatarAuthorityPath"], label="target avatar authority"
    )
    blueprint = read_object(blueprint_path, "blueprint")
    authority = read_object(authority_path, "target avatar authority")
    authority_summary = validate_target_avatar_authority(authority)
    blueprint_summary = validate_blueprint(
        blueprint,
        expected_product_id=product_id,
        expected_avatar_id=authority_summary["avatarId"],
    )
    if (
        blueprint_summary["targetAvatarAuthoritySha256"]
        != authority_summary["authoritySha256"]
    ):
        raise ValueError("blueprint target-avatar authority does not match authority file")
    if blueprint_summary["consumingStage"] != "initialize-3d":
        raise ValueError("Tripo mesh-draft blueprint must consume initialize-3d")

    api_key = os.environ.get("TRIPO_API_KEY", "").strip()
    if not api_key:
        write_failed_result(
            result_path,
            product_id=product_id,
            failure_reason="TRIPO_API_KEY is not configured",
        )
        return 2

    task_id: str | None = None
    started = time.monotonic()
    try:
        created = api_json(
            "POST",
            "/task",
            api_key=api_key,
            payload=build_multiview_task(request),
        )
        task_id_value = created.get("task_id")
        if not isinstance(task_id_value, str) or not task_id_value:
            raise RuntimeError("Tripo task_id is missing")
        task_id = task_id_value

        deadline = started + request["timeoutSeconds"]
        final: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            task = api_json("GET", f"/task/{task_id}", api_key=api_key)
            status = task.get("status")
            if status in TERMINAL_STATUSES:
                final = task
                break
            time.sleep(request["pollSeconds"])
        if final is None:
            raise TimeoutError("Tripo task did not reach a terminal status")
        if final.get("status") != "success":
            raise RuntimeError(f"Tripo task finalized as {final.get('status')!r}")

        output = final.get("output")
        if not isinstance(output, Mapping):
            raise RuntimeError("Tripo task output is missing")
        model_url = next(
            (
                value
                for key in ("model", "base_model", "pbr_model")
                if isinstance((value := output.get(key)), str) and value
            ),
            None,
        )
        if model_url is None:
            raise RuntimeError("Tripo task did not return a model URL")

        output_root = (
            ROOT
            / ".image2outfit"
            / "products"
            / product_id
            / "hypotheses"
            / "tripo"
            / task_id
        )
        suffix = Path(urllib.parse.urlparse(model_url).path).suffix.lower()
        if suffix not in {".glb", ".gltf", ".fbx", ".obj", ".zip"}:
            suffix = ".glb"
        model_path = output_root / f"draft{suffix}"
        download_file(model_url, model_path)
        artifact_sha = file_sha256(model_path)
        elapsed = time.monotonic() - started

        hypothesis_set = build_hypothesis_set(
            product_id=product_id,
            blueprint_sha256=blueprint_summary["blueprintSha256"],
            authority_sha256=authority_summary["authoritySha256"],
            task_id=task_id,
            model_version=request["modelVersion"],
            artifact_sha256=artifact_sha,
        )
        hypothesis_summary = validate_hypothesis_set(
            hypothesis_set,
            expected_product_id=product_id,
            expected_blueprint_sha256=blueprint_summary["blueprintSha256"],
        )
        hypothesis_path = output_root / "hypothesis-set.json"
        write_json(hypothesis_path, hypothesis_set)

        provenance = build_provenance(
            request=request,
            blueprint_sha256=blueprint_summary["blueprintSha256"],
            authority_sha256=authority_summary["authoritySha256"],
            task_id=task_id,
            artifact_sha256=artifact_sha,
            elapsed_seconds=elapsed,
            api_data=final,
        )
        provenance_path = output_root / "provenance.json"
        write_json(provenance_path, provenance)

        evidence_paths = [model_path, hypothesis_path, provenance_path]
        stage_result = {
            "schemaVersion": 1,
            "stage": "initialize-3d",
            "productId": product_id,
            "status": "PASS",
            "evidence": [
                {"path": relative(path), "sha256": file_sha256(path)}
                for path in evidence_paths
            ],
            "hypothesisContractValidated": True,
            "blueprintBound": True,
            "targetAvatarAuthorityValidated": True,
            "externalDraftCanonicalSource": False,
            "silentFallbackUsed": False,
            "taskId": task_id,
            "modelVersion": request["modelVersion"],
            "hypothesisSetSha256": hypothesis_summary["hypothesisSetSha256"],
            "outputArtifactSha256": artifact_sha,
            "elapsedSeconds": elapsed,
        }
        write_json(result_path, stage_result)
        return 0
    except Exception as exc:
        write_failed_result(
            result_path,
            product_id=product_id,
            failure_reason=str(exc),
            task_id=task_id,
        )
        print(str(exc), file=sys.stderr)
        return 1


def main() -> int:
    args = parse_args()
    try:
        return execute(args)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
