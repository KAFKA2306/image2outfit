#!/usr/bin/env python3
"""Run the pinned ComfyUI TRELLIS.2 graph as a bounded 3D hypothesis."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import mimetypes
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from image2outfit.comfyui_workflow import ui_workflow_to_api_prompt
from image2outfit.hypothesis_contracts import (
    stable_sha256,
    validate_blueprint,
    validate_hypothesis_set,
    validate_target_avatar_authority,
)

WORKFLOW_LOCK_PATH = ROOT / "config/workflows/comfyui/pixal3d_trellis2_image_to_model.lock.json"
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
PRODUCT_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,127}\Z")
PROMPT_ID_PATTERN = re.compile(r"[0-9a-fA-F-]{1,64}\Z")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


LOCAL_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    _NoRedirect(),
)


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


def local_api_root(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("comfyuiUrl must be a non-empty URL")
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("ComfyUI must use a loopback HTTP URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("comfyuiUrl must not include credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("comfyuiUrl must identify the ComfyUI server root")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("comfyuiUrl port is invalid")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")


def _open(request: urllib.request.Request, *, timeout: float) -> bytes:
    try:
        with LOCAL_OPENER.open(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ComfyUI HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"ComfyUI is unavailable: {exc.reason}") from exc


def api_json(
    method: str,
    api_root: str,
    endpoint: str,
    *,
    payload: Mapping[str, Any] | None = None,
    timeout: float = 30,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(dict(payload)).encode("utf-8")
    headers = {} if body is None else {"Content-Type": "application/json"}
    request = urllib.request.Request(
        f"{api_root}{endpoint}", data=body, headers=headers, method=method
    )
    response = json.loads(_open(request, timeout=timeout).decode("utf-8"))
    if not isinstance(response, dict):
        raise RuntimeError("ComfyUI response must be a JSON object")
    return response


def upload_image(api_root: str, image_path: Path) -> dict[str, str]:
    extension = image_path.suffix.lower()
    if extension not in {".jpg", ".jpeg", ".png"}:
        raise ValueError("ComfyUI reference image must be JPG or PNG")
    upload_name = f"image2outfit-{uuid.uuid4().hex}{extension}"
    boundary = f"----image2outfit-{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(upload_name)[0] or "application/octet-stream"
    if image_path.stat().st_size > MAX_UPLOAD_BYTES:
        raise ValueError("ComfyUI reference image exceeds the 50 MiB upload limit")
    image_data = image_path.read_bytes()
    body = b"".join(
        (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{upload_name}\"\r\n".encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            image_data,
            f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"type\"\r\n\r\ninput\r\n".encode(),
            f"--{boundary}--\r\n".encode(),
        )
    )
    request = urllib.request.Request(
        f"{api_root}/upload/image",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    response = json.loads(_open(request, timeout=60).decode("utf-8"))
    if not isinstance(response, Mapping):
        raise RuntimeError("ComfyUI image upload response must be an object")
    name = response.get("name")
    subfolder = response.get("subfolder", "")
    file_type = response.get("type")
    if not isinstance(name, str) or not name or file_type != "input":
        raise RuntimeError("ComfyUI did not return an input image reference")
    if not isinstance(subfolder, str):
        raise RuntimeError("ComfyUI upload subfolder is invalid")
    safe_parts = [part for part in subfolder.replace("\\", "/").split("/") if part]
    if any(part in {".", ".."} for part in safe_parts):
        raise RuntimeError("ComfyUI returned an unsafe image subfolder")
    image_name = "/".join([*safe_parts, name])
    return {"imageName": image_name, "uploadedName": name}


def _artifact_references(value: object) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    if isinstance(value, Mapping):
        filename = value.get("filename")
        subfolder = value.get("subfolder", "")
        file_type = value.get("type")
        if (
            isinstance(filename, str)
            and filename.lower().endswith(".glb")
            and isinstance(subfolder, str)
            and file_type in {"output", "temp"}
        ):
            found.append(
                {"filename": filename, "subfolder": subfolder, "type": str(file_type)}
            )
        for nested in value.values():
            found.extend(_artifact_references(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_artifact_references(nested))
    return found


def download_glb(api_root: str, artifact: Mapping[str, str], path: Path) -> None:
    query = urllib.parse.urlencode(
        {
            "filename": artifact["filename"],
            "subfolder": artifact["subfolder"],
            "type": artifact["type"],
        }
    )
    request = urllib.request.Request(f"{api_root}/view?{query}", method="GET")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    total = 0
    try:
        with LOCAL_OPENER.open(request, timeout=60) as response, temporary.open("wb") as output:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > MAX_DOWNLOAD_BYTES:
                    raise ValueError("ComfyUI GLB exceeds the 512 MiB download limit")
                output.write(block)
    except urllib.error.HTTPError as exc:
        temporary.unlink(missing_ok=True)
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ComfyUI GLB download HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"ComfyUI GLB download failed: {exc.reason}") from exc
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    if total == 0:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("ComfyUI returned an empty GLB")
    temporary.replace(path)


def validate_glb(path: Path) -> None:
    with path.open("rb") as handle:
        header = handle.read(12)
    if len(header) != 12 or header[:4] != b"glTF":
        raise ValueError("ComfyUI output is not a binary glTF file")
    version = int.from_bytes(header[4:8], "little")
    declared_size = int.from_bytes(header[8:12], "little")
    if version != 2 or declared_size != path.stat().st_size:
        raise ValueError("ComfyUI output has an invalid GLB header")


def _load_pinned_workflow() -> tuple[dict[str, Any], dict[str, Any]]:
    lock = read_object(WORKFLOW_LOCK_PATH, "ComfyUI workflow lock")
    workflow_path = repo_path(lock.get("workflowPath", ""), label="workflowPath")
    workflow = read_object(workflow_path, "ComfyUI workflow")
    actual_sha = file_sha256(workflow_path)
    if actual_sha != lock.get("workflowSha256"):
        raise ValueError("pinned ComfyUI workflow SHA-256 mismatch")
    return lock, workflow


def _positive_number(value: object, *, label: str, maximum: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
        or value > maximum
    ):
        raise ValueError(f"{label} must be a positive number no greater than {maximum}")
    return float(value)


def write_failed_result(
    result_path: Path, *, product_id: str | None, failure_reason: str, prompt_id: str | None
) -> None:
    write_json(
        result_path,
        {
            "schemaVersion": 1,
            "stage": "initialize-3d",
            "productId": product_id,
            "status": "FAILED",
            "evidence": [],
            "promptId": prompt_id,
            "failureReason": failure_reason[:1000],
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

    raw_request = read_object(request_path, "ComfyUI request")
    product_id_value = raw_request.get("productId")
    product_id = product_id_value if isinstance(product_id_value, str) else None
    prompt_id: str | None = None
    try:
        if raw_request.get("schemaVersion") != 1:
            raise ValueError("ComfyUI request schemaVersion must be 1")
        if product_id is None or PRODUCT_ID_PATTERN.fullmatch(product_id) is None:
            raise ValueError("productId must be a lowercase product slug")
        blueprint_path = repo_path(raw_request.get("blueprintPath", ""), label="blueprint")
        authority_path = repo_path(
            raw_request.get("targetAvatarAuthorityPath", ""),
            label="target avatar authority",
        )
        image_path = repo_path(raw_request.get("referenceImagePath", ""), label="reference image")
        if not image_path.is_file():
            raise FileNotFoundError(f"ComfyUI reference image is missing: {relative(image_path)}")
        if not blueprint_path.is_file() or not authority_path.is_file():
            raise FileNotFoundError("ComfyUI blueprint or target-avatar authority is missing")

        blueprint = read_object(blueprint_path, "blueprint")
        authority = read_object(authority_path, "target avatar authority")
        authority_summary = validate_target_avatar_authority(authority)
        blueprint_summary = validate_blueprint(
            blueprint,
            expected_product_id=product_id,
            expected_avatar_id=authority_summary["avatarId"],
        )
        if blueprint_summary["targetAvatarAuthoritySha256"] != authority_summary["authoritySha256"]:
            raise ValueError("blueprint target-avatar authority does not match authority file")
        if blueprint_summary["consumingStage"] != "initialize-3d":
            raise ValueError("ComfyUI mesh-draft blueprint must consume initialize-3d")

        api_root = local_api_root(raw_request.get("comfyuiUrl", "http://127.0.0.1:8188"))
        poll_seconds = _positive_number(raw_request.get("pollSeconds", 2), label="pollSeconds", maximum=30)
        timeout_seconds = _positive_number(
            raw_request.get("timeoutSeconds", 1800), label="timeoutSeconds", maximum=7200
        )
        generation_started = time.monotonic()
        deadline = generation_started + timeout_seconds
        lock, workflow = _load_pinned_workflow()
        workflow_path = repo_path(lock["workflowPath"], label="workflowPath")
        workflow_sha = file_sha256(workflow_path)
        target_resolution = lock.get("targetResolution")
        if target_resolution != 512:
            raise ValueError("pinned ComfyUI target resolution must be 512")

        object_info = api_json("GET", api_root, "/object_info", timeout=60)
        execution_id = uuid.uuid4().hex
        node_ids = lock.get("nodeIds")
        if not isinstance(node_ids, Mapping):
            raise ValueError("ComfyUI workflow lock nodeIds must be an object")
        image_node_id = str(node_ids.get("inputImage", ""))
        trellis_selector_node_id = str(node_ids.get("trellisSelector", ""))
        upsample_node_id = str(node_ids.get("upsample", ""))
        output_node_id = str(node_ids.get("saveOutput", ""))
        prompt = ui_workflow_to_api_prompt(
            workflow,
            object_info,
            image_node_id=image_node_id,
            image_name="__IMAGE2OUTFIT_UPLOAD__",
            trellis_selector_node_id=trellis_selector_node_id,
            upsample_node_id=upsample_node_id,
            output_node_id=output_node_id,
            output_prefix=f"image2outfit/{product_id}/{execution_id}",
            target_resolution=target_resolution,
        )
        uploaded = upload_image(api_root, image_path)
        prompt[image_node_id]["inputs"]["image"] = uploaded["imageName"]

        queued = api_json(
            "POST",
            api_root,
            "/prompt",
            payload={"prompt": prompt, "client_id": execution_id},
            timeout=60,
        )
        prompt_id_value = queued.get("prompt_id")
        if (
            not isinstance(prompt_id_value, str)
            or PROMPT_ID_PATTERN.fullmatch(prompt_id_value) is None
        ):
            raise RuntimeError("ComfyUI did not return a prompt_id")
        prompt_id = prompt_id_value

        history: Mapping[str, Any] | None = None
        while time.monotonic() < deadline:
            response = api_json(
                "GET", api_root, f"/history/{urllib.parse.quote(prompt_id, safe='')}", timeout=60
            )
            entry = response.get(prompt_id)
            if isinstance(entry, Mapping):
                status = entry.get("status", {})
                status_map = status if isinstance(status, Mapping) else {}
                status_name = status_map.get("status_str")
                if status_name in {"error", "failed"}:
                    raise RuntimeError("ComfyUI workflow execution failed")
                if status_map.get("completed") is True or status_name in {"success", "completed"}:
                    history = entry
                    break
            time.sleep(poll_seconds)
        if history is None:
            raise TimeoutError("ComfyUI workflow did not complete before timeout")

        outputs = history.get("outputs")
        if not isinstance(outputs, Mapping):
            raise RuntimeError("ComfyUI history has no workflow outputs")
        artifact_candidates: list[dict[str, str]] = []
        for candidate_node_id in (output_node_id, str(node_ids.get("meshFile", ""))):
            artifact_candidates.extend(_artifact_references(outputs.get(candidate_node_id)))
            if artifact_candidates:
                break
        if not artifact_candidates:
            raise RuntimeError("ComfyUI output node did not produce a GLB file")

        output_root = (
            ROOT / ".image2outfit" / "products" / product_id / "hypotheses" / "comfyui" / prompt_id
        )
        model_path = output_root / "draft.glb"
        download_glb(api_root, artifact_candidates[0], model_path)
        try:
            validate_glb(model_path)
        except Exception:
            model_path.unlink(missing_ok=True)
            raise
        artifact_sha = file_sha256(model_path)
        elapsed = time.monotonic() - generation_started
        image_sha = file_sha256(image_path)

        hypothesis_id = f"comfyui-trellis2-{prompt_id}"
        hypothesis_set = {
            "schemaVersion": 1,
            "productId": product_id,
            "blueprintSha256": blueprint_summary["blueprintSha256"],
            "targetAvatarAuthoritySha256": authority_summary["authoritySha256"],
            "hypotheses": [
                {
                    "hypothesisId": hypothesis_id,
                    "source": "comfyui-trellis2-draft",
                    "artifactSha256": artifact_sha,
                    "targetAvatarAuthoritySha256": authority_summary["authoritySha256"],
                    "canonicalSource": False,
                    "generatorProvenance": {
                        "tool": "ComfyUI official Pixal3D/TRELLIS.2 workflow",
                        "version": lock["sourceCommit"],
                    },
                }
            ],
            "selectedHypothesisId": hypothesis_id,
            "silentFallbackUsed": False,
        }
        hypothesis_summary = validate_hypothesis_set(
            hypothesis_set,
            expected_product_id=product_id,
            expected_blueprint_sha256=blueprint_summary["blueprintSha256"],
        )
        hypothesis_path = output_root / "hypothesis-set.json"
        write_json(hypothesis_path, hypothesis_set)
        provenance = {
            "schemaVersion": 1,
            "productId": product_id,
            "inputImageSha256": image_sha,
            "blueprintSha256": blueprint_summary["blueprintSha256"],
            "targetAvatarAuthoritySha256": authority_summary["authoritySha256"],
            "workflowId": lock["workflowId"],
            "workflowSourceRepository": lock["sourceRepository"],
            "workflowSourceCommit": lock["sourceCommit"],
            "workflowSha256": workflow_sha,
            "comfyuiUrl": api_root,
            "promptId": prompt_id,
            "targetResolution": target_resolution,
            "blueprintBindingMode": "validated-request-lineage-only; not model conditioning",
            "targetAvatarConditioningApplied": False,
            "outputSha256": artifact_sha,
            "elapsedSeconds": elapsed,
            "canonicalSource": False,
            "provenanceSha256": stable_sha256(
                {
                    "promptId": prompt_id,
                    "artifactSha256": artifact_sha,
                    "workflowSha256": workflow_sha,
                    "blueprintSha256": blueprint_summary["blueprintSha256"],
                    "authoritySha256": authority_summary["authoritySha256"],
                }
            ),
        }
        provenance_path = output_root / "provenance.json"
        write_json(provenance_path, provenance)

        evidence_paths = [model_path, hypothesis_path, provenance_path]
        write_json(
            result_path,
            {
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
                "promptId": prompt_id,
                "workflowSha256": workflow_sha,
                "hypothesisSetSha256": hypothesis_summary["hypothesisSetSha256"],
                "outputArtifactSha256": artifact_sha,
                "elapsedSeconds": elapsed,
            },
        )
        return 0
    except Exception as exc:
        write_failed_result(
            result_path,
            product_id=product_id,
            failure_reason=str(exc),
            prompt_id=prompt_id,
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
