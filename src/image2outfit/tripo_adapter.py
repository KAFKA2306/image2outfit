"""Pure contracts for the opt-in Tripo multi-view hypothesis adapter."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from image2outfit.hypothesis_contracts import stable_sha256

VIEW_ORDER = ("front", "left", "back", "right")
SUPPORTED_IMAGE_TYPES = frozenset({"jpg", "jpeg", "png"})
TERMINAL_STATUSES = frozenset(
    {"success", "failed", "banned", "expired", "cancelled", "unknown"}
)
DEFAULT_MODEL_VERSION = "P1-20260311"


def _mapping(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _sha256(value: object, *, label: str) -> str:
    text = _string(value, label=label)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return text


def validate_multiview_request(
    payload: Mapping[str, Any],
    *,
    expected_product_id: str | None = None,
) -> dict[str, Any]:
    """Validate local-only input without retaining credentials or private file references."""
    if payload.get("schemaVersion") != 1:
        raise ValueError("Tripo request schemaVersion must be 1")
    product_id = _string(payload.get("productId"), label="productId")
    if expected_product_id is not None and product_id != expected_product_id:
        raise ValueError("Tripo request product identity mismatch")

    blueprint_path = _string(payload.get("blueprintPath"), label="blueprintPath")
    authority_path = _string(
        payload.get("targetAvatarAuthorityPath"), label="targetAvatarAuthorityPath"
    )
    model_version = _string(
        payload.get("modelVersion", DEFAULT_MODEL_VERSION), label="modelVersion"
    )
    face_limit = payload.get("faceLimit", 4000)
    if (
        isinstance(face_limit, bool)
        or not isinstance(face_limit, int)
        or face_limit < 48
        or face_limit > 20000
    ):
        raise ValueError("faceLimit must be an integer between 48 and 20000")

    texture = payload.get("texture", False)
    pbr = payload.get("pbr", False)
    if not isinstance(texture, bool) or not isinstance(pbr, bool):
        raise ValueError("texture and pbr must be boolean")
    model_seed = payload.get("modelSeed")
    if model_seed is not None and (
        isinstance(model_seed, bool) or not isinstance(model_seed, int)
    ):
        raise ValueError("modelSeed must be an integer when provided")

    views = _mapping(payload.get("views"), label="views")
    unknown_views = sorted(set(views).difference(VIEW_ORDER))
    if unknown_views:
        raise ValueError(f"unknown Tripo views: {unknown_views}")

    normalized_views: dict[str, dict[str, Any] | None] = {}
    supplied = 0
    for name in VIEW_ORDER:
        raw = views.get(name)
        if raw is None:
            normalized_views[name] = None
            continue
        item = _mapping(raw, label=f"views.{name}")
        digest = _sha256(item.get("sha256"), label=f"views.{name}.sha256")
        file_value = _mapping(item.get("file"), label=f"views.{name}.file")
        image_type = _string(file_value.get("type"), label=f"views.{name}.file.type")
        if image_type.lower() not in SUPPORTED_IMAGE_TYPES:
            raise ValueError(f"views.{name}.file.type is unsupported")

        source_keys = [
            key
            for key in ("file_token", "url", "object")
            if file_value.get(key) is not None
        ]
        if len(source_keys) != 1:
            raise ValueError(
                f"views.{name}.file must contain exactly one of file_token/url/object"
            )
        source_key = source_keys[0]
        source_value = file_value[source_key]
        if source_key in {"file_token", "url"}:
            _string(source_value, label=f"views.{name}.file.{source_key}")
        else:
            object_value = _mapping(source_value, label=f"views.{name}.file.object")
            _string(
                object_value.get("bucket"), label=f"views.{name}.file.object.bucket"
            )
            _string(object_value.get("key"), label=f"views.{name}.file.object.key")

        normalized_views[name] = {
            "sha256": digest,
            "file": dict(file_value),
        }
        supplied += 1

    if normalized_views["front"] is None:
        raise ValueError("front view is required")
    if supplied < 2:
        raise ValueError("Tripo multiview requires at least two supplied views")

    poll_seconds = payload.get("pollSeconds", 2.0)
    timeout_seconds = payload.get("timeoutSeconds", 300.0)
    for value, label in (
        (poll_seconds, "pollSeconds"),
        (timeout_seconds, "timeoutSeconds"),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError(f"{label} must be a positive finite number")

    return {
        "schemaVersion": 1,
        "productId": product_id,
        "blueprintPath": blueprint_path,
        "targetAvatarAuthorityPath": authority_path,
        "modelVersion": model_version,
        "faceLimit": face_limit,
        "texture": texture,
        "pbr": pbr,
        "modelSeed": model_seed,
        "views": normalized_views,
        "pollSeconds": float(poll_seconds),
        "timeoutSeconds": float(timeout_seconds),
    }


def build_multiview_task(request: Mapping[str, Any]) -> dict[str, Any]:
    """Build the documented Tripo API payload without persisting local-only hashes."""
    files: list[dict[str, Any]] = []
    for name in VIEW_ORDER:
        item = request["views"][name]
        files.append({} if item is None else dict(item["file"]))
    task: dict[str, Any] = {
        "type": "multiview_to_model",
        "model_version": request["modelVersion"],
        "files": files,
        "face_limit": request["faceLimit"],
        "texture": request["texture"],
        "pbr": request["pbr"],
    }
    if request.get("modelSeed") is not None:
        task["model_seed"] = request["modelSeed"]
    return task


def sanitized_input_hashes(request: Mapping[str, Any]) -> dict[str, str | None]:
    """Return view hashes only, never file tokens, URLs, object keys, or credentials."""
    return {
        name: (
            None if request["views"][name] is None else request["views"][name]["sha256"]
        )
        for name in VIEW_ORDER
    }


def build_hypothesis_set(
    *,
    product_id: str,
    blueprint_sha256: str,
    authority_sha256: str,
    task_id: str,
    model_version: str,
    artifact_sha256: str,
) -> dict[str, Any]:
    hypothesis_id = f"tripo-{task_id}"
    return {
        "schemaVersion": 1,
        "productId": product_id,
        "blueprintSha256": blueprint_sha256,
        "targetAvatarAuthoritySha256": authority_sha256,
        "hypotheses": [
            {
                "hypothesisId": hypothesis_id,
                "source": "tripo-draft",
                "artifactSha256": artifact_sha256,
                "targetAvatarAuthoritySha256": authority_sha256,
                "canonicalSource": False,
                "generatorProvenance": {
                    "tool": "Tripo API",
                    "version": model_version,
                },
            }
        ],
        "selectedHypothesisId": hypothesis_id,
        "silentFallbackUsed": False,
    }


def build_provenance(
    *,
    request: Mapping[str, Any],
    blueprint_sha256: str,
    authority_sha256: str,
    task_id: str,
    artifact_sha256: str,
    elapsed_seconds: float,
    api_data: Mapping[str, Any],
) -> dict[str, Any]:
    output = api_data.get("output")
    output_map = output if isinstance(output, Mapping) else {}
    return {
        "schemaVersion": 1,
        "productId": request["productId"],
        "inputSha256": sanitized_input_hashes(request),
        "blueprintSha256": blueprint_sha256,
        "targetAvatarAuthoritySha256": authority_sha256,
        "taskId": task_id,
        "traceId": api_data.get("trace_id"),
        "model": "Tripo",
        "version": request["modelVersion"],
        "generationMode": "multiview_to_model",
        "quadRequestedDuringGeneration": False,
        "faceLimit": request["faceLimit"],
        "seed": request.get("modelSeed"),
        "outputSha256": artifact_sha256,
        "generationStatus": api_data.get("status"),
        "failureReason": None,
        "elapsedSeconds": elapsed_seconds,
        "apiMetadata": {
            "consumedCredit": api_data.get("consumed_credit"),
            "progress": api_data.get("progress"),
            "topology": output_map.get("topology"),
            "riggable": output_map.get("riggable"),
        },
        "provenanceSha256": stable_sha256(
            {
                "taskId": task_id,
                "artifactSha256": artifact_sha256,
                "blueprintSha256": blueprint_sha256,
                "authoritySha256": authority_sha256,
            }
        ),
    }
