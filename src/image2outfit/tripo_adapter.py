"""Minimal Tripo OpenAPI adapter for blueprint-guided garment experiments."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any

API_ROOT = "https://api.tripo3d.ai/v2/openapi"
BASE_MODEL_VERSION = "v3.1-20260211"
SMART_MESH_MODEL_VERSION = "P-v2.0-20251225"
TEXTURE_MODEL_VERSION = "v3.0-20250812"
SMART_MESH_FACE_LIMIT_MAX = 20000
FINAL_STATUSES = frozenset(
    {"success", "failed", "banned", "expired", "cancelled", "unknown"}
)


class TripoError(RuntimeError):
    pass


def _file_ref(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    ref = dict(value)
    selectors = [name for name in ("file_token", "url", "object") if name in ref]
    if len(selectors) != 1:
        raise ValueError(
            "Tripo file ref requires exactly one of file_token, url, object"
        )
    file_type = ref.get("type")
    if not isinstance(file_type, str) or not file_type:
        raise ValueError("Tripo file ref type is required")
    if "url" in ref and (
        not isinstance(ref["url"], str) or not ref["url"].startswith("https://")
    ):
        raise ValueError("Tripo input URL must use https")
    if "object" in ref:
        obj = ref["object"]
        if not isinstance(obj, dict) or not all(
            isinstance(obj.get(key), str) and obj[key] for key in ("bucket", "key")
        ):
            raise ValueError("Tripo object ref requires bucket and key")
    return ref


def build_multiview_request(
    *,
    front: Mapping[str, Any],
    left: Mapping[str, Any] | None = None,
    back: Mapping[str, Any] | None = None,
    right: Mapping[str, Any] | None = None,
    model_version: str = BASE_MODEL_VERSION,
) -> dict[str, Any]:
    """Build the documented [front, left, back, right] multiview request."""
    files = [_file_ref(item) for item in (front, left, back, right)]
    if not files[0]:
        raise ValueError("front view is required")
    if sum(bool(item) for item in files) < 2:
        raise ValueError("Tripo multiview generation requires at least two views")
    return {
        "type": "multiview_to_model",
        "model_version": model_version,
        "files": files,
        "texture": False,
        "pbr": False,
    }


def build_smart_mesh_request(
    original_model_task_id: str,
    *,
    face_limit: int = 8000,
    quad: bool = True,
    bake: bool = True,
) -> dict[str, Any]:
    """Build the documented Smart LowPoly P2.0 post-process request."""
    if not original_model_task_id:
        raise ValueError("original_model_task_id is required")
    if not 500 <= face_limit <= SMART_MESH_FACE_LIMIT_MAX:
        raise ValueError(
            f"face_limit must be between 500 and {SMART_MESH_FACE_LIMIT_MAX}"
        )
    return {
        "type": "highpoly_to_lowpoly",
        "original_model_task_id": original_model_task_id,
        "model_version": SMART_MESH_MODEL_VERSION,
        "quad": quad,
        "face_limit": face_limit,
        "bake": bake,
    }


def build_import_model_request(file_ref: Mapping[str, Any]) -> dict[str, Any]:
    """Build an import request for a Blender-adjusted model already uploaded to Tripo."""
    return {"type": "import_model", "file": _file_ref(file_ref)}


def build_texture_model_request(
    original_model_task_id: str,
    *,
    reference_images: Sequence[Mapping[str, Any]] = (),
    prompt_text: str | None = None,
    model_version: str = TEXTURE_MODEL_VERSION,
    texture_quality: str = "detailed",
) -> dict[str, Any]:
    """Build geometry-aligned retexturing for downstream mask authoring.

    Tripo returns a textured model, not a semantic mask. A shading-only or region
    reference image can be projected here, then extracted or edited downstream.
    """
    if not original_model_task_id:
        raise ValueError("original_model_task_id is required")
    if texture_quality not in {"standard", "detailed", "extreme"}:
        raise ValueError("texture_quality is not supported")
    prompt: dict[str, Any] = {}
    if prompt_text is not None:
        if not prompt_text.strip():
            raise ValueError("prompt_text must not be blank")
        prompt["text"] = prompt_text
    images = [_file_ref(image) for image in reference_images]
    if images:
        prompt["images"] = images
    if not prompt:
        raise ValueError("reference texture requires prompt_text or reference_images")
    return {
        "type": "texture_model",
        "original_model_task_id": original_model_task_id,
        "model_version": model_version,
        "texture": True,
        "pbr": False,
        "texture_quality": texture_quality,
        "texture_alignment": "geometry",
        "bake": True,
        "texture_prompt": prompt,
    }


class TripoClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = API_ROOT,
        request_timeout_seconds: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError("Tripo API key is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._request_timeout_seconds = request_timeout_seconds

    def _json(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        body = None if payload is None else json.dumps(dict(payload)).encode("utf-8")
        request = urllib.request.Request(
            self._base_url + path,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self._request_timeout_seconds
            ) as response:
                raw = response.read().decode("utf-8")
                trace_id = response.headers.get("X-Tripo-Trace-ID")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            raise TripoError(f"Tripo request failed: {exc}") from exc
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TripoError("Tripo returned non-JSON response") from exc
        if not isinstance(value, dict) or value.get("code") != 0:
            message = value.get("message") if isinstance(value, dict) else None
            raise TripoError(f"Tripo API error: {message or value!r}")
        data = value.get("data")
        if not isinstance(data, dict):
            raise TripoError("Tripo response is missing data")
        return data, trace_id

    def submit(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data, trace_id = self._json("POST", "/task", payload)
        task_id = data.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise TripoError("Tripo submit response is missing task_id")
        return {"taskId": task_id, "traceId": trace_id}

    def get_task(self, task_id: str) -> dict[str, Any]:
        data, trace_id = self._json("GET", f"/task/{task_id}")
        return {**data, "traceId": trace_id}

    def wait_for_task(
        self,
        task_id: str,
        *,
        timeout_seconds: float = 600.0,
        poll_seconds: float = 2.0,
    ) -> dict[str, Any]:
        if timeout_seconds <= 0 or poll_seconds <= 0:
            raise ValueError("timeout_seconds and poll_seconds must be positive")
        deadline = time.monotonic() + timeout_seconds
        while True:
            task = self.get_task(task_id)
            status = task.get("status")
            if status in FINAL_STATUSES:
                if status != "success":
                    raise TripoError(
                        f"Tripo task {task_id} ended with status {status}: "
                        f"{task.get('error_msg') or task.get('error_code') or ''}"
                    )
                return task
            if time.monotonic() >= deadline:
                raise TripoError(f"Tripo task {task_id} timed out")
            time.sleep(poll_seconds)

    def _run_task(
        self,
        payload: Mapping[str, Any],
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        submitted = self.submit(payload)
        task = self.wait_for_task(submitted["taskId"], timeout_seconds=timeout_seconds)
        output = task.get("output")
        return {
            "taskId": submitted["taskId"],
            "submitTraceId": submitted["traceId"],
            "pollTraceId": task.get("traceId"),
            "consumedCredit": task.get("consumed_credit"),
            "output": output if isinstance(output, dict) else {},
        }

    def _run_model_task(
        self,
        payload: Mapping[str, Any],
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        result = self._run_task(payload, timeout_seconds=timeout_seconds)
        output = result["output"]
        if not any(
            isinstance(output.get(key), str) and output[key]
            for key in ("model", "pbr_model", "base_model")
        ):
            raise TripoError("successful Tripo task has no documented model output")
        return result

    def generate_smart_mesh(
        self,
        views: Mapping[str, Mapping[str, Any]],
        *,
        face_limit: int = 8000,
        timeout_seconds: float = 600.0,
    ) -> dict[str, Any]:
        front = views.get("front")
        if not isinstance(front, Mapping):
            raise ValueError("front view is required")
        multiview_payload = build_multiview_request(
            front=front,
            left=views.get("left"),
            back=views.get("back"),
            right=views.get("right"),
        )
        base_submit = self.submit(multiview_payload)
        base_task = self.wait_for_task(
            base_submit["taskId"], timeout_seconds=timeout_seconds
        )
        mesh_payload = build_smart_mesh_request(
            base_submit["taskId"], face_limit=face_limit, quad=True, bake=True
        )
        mesh = self._run_model_task(mesh_payload, timeout_seconds=timeout_seconds)
        return {
            "schemaVersion": 1,
            "provider": "tripo",
            "baseGeneration": {
                "taskId": base_submit["taskId"],
                "submitTraceId": base_submit["traceId"],
                "pollTraceId": base_task.get("traceId"),
                "modelVersion": BASE_MODEL_VERSION,
                "consumedCredit": base_task.get("consumed_credit"),
            },
            "smartMesh": {
                **mesh,
                "modelVersion": SMART_MESH_MODEL_VERSION,
                "quad": True,
                "faceLimit": face_limit,
            },
        }

    def import_model(
        self,
        file_ref: Mapping[str, Any],
        *,
        timeout_seconds: float = 600.0,
    ) -> dict[str, Any]:
        """Import an uploaded Blender-adjusted model for post-process operations."""
        return self._run_task(
            build_import_model_request(file_ref), timeout_seconds=timeout_seconds
        )

    def texture_model(
        self,
        original_model_task_id: str,
        *,
        reference_images: Sequence[Mapping[str, Any]] = (),
        prompt_text: str | None = None,
        texture_quality: str = "detailed",
        timeout_seconds: float = 600.0,
    ) -> dict[str, Any]:
        """Project reference texture information onto an existing Tripo task model."""
        payload = build_texture_model_request(
            original_model_task_id,
            reference_images=reference_images,
            prompt_text=prompt_text,
            texture_quality=texture_quality,
        )
        result = self._run_model_task(payload, timeout_seconds=timeout_seconds)
        return {**result, "modelVersion": TEXTURE_MODEL_VERSION}
