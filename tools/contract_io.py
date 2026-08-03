#!/usr/bin/env python3
"""Small, dependency-free JSON, path, hash, and schema helpers."""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PRODUCT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
STABLE_SCRIPT = re.compile(
    r"(?:^|_)(?:v\d+|entry|refit|legacy)(?:_|$)", re.IGNORECASE
)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(path)


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def repo_path(root: Path, value: str) -> Path:
    candidate = (root / value).resolve()
    root = root.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"path escapes repository: {value}")
    return candidate


def relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def validate_json_schema(
    value: Any, schema: dict[str, Any], path: str = "value"
) -> list[str]:
    """Validate the JSON-Schema subset used by repository contracts."""
    errors: list[str] = []
    expected_type = schema.get("type")
    type_checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float))
        and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    if expected_type in type_checks and not type_checks[expected_type](value):
        return [f"{path} must be {expected_type}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path} must equal {schema['const']!r}")
    if isinstance(value, str):
        minimum = schema.get("minLength")
        if isinstance(minimum, int) and len(value) < minimum:
            errors.append(f"{path} is shorter than {minimum}")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            errors.append(f"{path} does not match {pattern}")
    if isinstance(value, list):
        minimum = schema.get("minItems")
        if isinstance(minimum, int) and len(value) < minimum:
            errors.append(f"{path} must contain at least {minimum} items")
        if schema.get("uniqueItems") is True:
            serialized = [
                json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value
            ]
            if len(serialized) != len(set(serialized)):
                errors.append(f"{path} must contain unique items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(
                    validate_json_schema(item, item_schema, f"{path}[{index}]")
                )
    if isinstance(value, dict):
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            properties = {}
        required = schema.get("required")
        if isinstance(required, list):
            for name in required:
                if name not in value:
                    errors.append(f"{path}.{name} is required")
        additional = schema.get("additionalProperties", True)
        for name, item in value.items():
            child_path = f"{path}.{name}"
            if name in properties:
                errors.extend(
                    validate_json_schema(item, properties[name], child_path)
                )
            elif additional is False:
                errors.append(f"{child_path} is not allowed")
            elif isinstance(additional, dict):
                errors.extend(validate_json_schema(item, additional, child_path))
    return errors


def validate_schema_file(value: Any, schema_path: Path, path: str) -> list[str]:
    try:
        schema = read_json(schema_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [f"schema unreadable: {schema_path}: {exc}"]
    return validate_json_schema(value, schema, path)


def canonical_product_root(product_id: str) -> str:
    return f"Assets/GenWorks/{product_id}"


def canonical_manifest_path(product_id: str) -> str:
    return f"{canonical_product_root(product_id)}/ProductManifest.json"


def required_pose_paths(
    job: dict[str, Any], policy: dict[str, Any]
) -> dict[str, str]:
    product_root = str(job.get("productRoot", ""))
    poses = policy.get("requiredPoses")
    if not isinstance(poses, list) or not poses or not all(
        isinstance(value, str) and value for value in poses
    ):
        raise ValueError(
            "release-policy.requiredPoses must be a non-empty string list"
        )
    return {
        pose: f"{product_root}/Previews/Poses/{pose}.png" for pose in poses
    }


def valid_review_reference(value: Any, allowed_hosts: set[str]) -> bool:
    if not isinstance(value, str) or not value:
        return False
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname in allowed_hosts
        and "/pull/" in parsed.path
        and (
            "pullrequestreview-" in parsed.fragment
            or "/reviews/" in parsed.path
        )
    )
