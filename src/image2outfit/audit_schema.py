"""Schema authority helpers for pipeline audit records and manifests."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_SUPPORTED_SCHEMA = "https://json-schema.org/draft/2020-12/schema"


def resolve_schema_path(root: Path, value: str, *, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty repository-relative path")
    path = Path(value)
    if path.is_absolute():
        raise ValueError(f"{label} must be repository-relative")
    resolved_root = root.resolve()
    resolved = (resolved_root / path).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"{label} escapes repository")
    if not resolved.is_file():
        raise ValueError(f"{label} does not exist: {value}")
    return resolved


def load_schema(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not readable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    if value.get("$schema") != _SUPPORTED_SCHEMA:
        raise ValueError(f"{label} uses an unsupported JSON Schema version")
    if value.get("type") != "object":
        raise ValueError(f"{label} root type must be object")
    return value


def _type_matches(value: Any, expected: str) -> bool:
    checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    return checks.get(expected, lambda _item: True)(value)


def validate_schema(value: Any, schema: dict[str, Any], *, path: str) -> None:
    errors: list[str] = []

    def visit(item: Any, rule: dict[str, Any], location: str) -> None:
        expected = rule.get("type")
        if isinstance(expected, str) and not _type_matches(item, expected):
            errors.append(f"{location} must be {expected}")
            return
        if "const" in rule and item != rule["const"]:
            errors.append(f"{location} must equal {rule['const']!r}")
        enum = rule.get("enum")
        if isinstance(enum, list) and item not in enum:
            errors.append(f"{location} must be one of {enum!r}")
        if isinstance(item, str):
            minimum = rule.get("minLength")
            if isinstance(minimum, int) and len(item) < minimum:
                errors.append(f"{location} is shorter than {minimum}")
            pattern = rule.get("pattern")
            if isinstance(pattern, str) and re.search(pattern, item) is None:
                errors.append(f"{location} does not match {pattern}")
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            minimum = rule.get("minimum")
            maximum = rule.get("maximum")
            if isinstance(minimum, (int, float)) and item < minimum:
                errors.append(f"{location} must be >= {minimum}")
            if isinstance(maximum, (int, float)) and item > maximum:
                errors.append(f"{location} must be <= {maximum}")
        if isinstance(item, list):
            minimum = rule.get("minItems")
            maximum = rule.get("maxItems")
            if isinstance(minimum, int) and len(item) < minimum:
                errors.append(f"{location} must contain at least {minimum} items")
            if isinstance(maximum, int) and len(item) > maximum:
                errors.append(f"{location} must contain at most {maximum} items")
            if rule.get("uniqueItems") is True:
                encoded = [json.dumps(v, sort_keys=True, ensure_ascii=False) for v in item]
                if len(encoded) != len(set(encoded)):
                    errors.append(f"{location} must contain unique items")
            child = rule.get("items")
            if isinstance(child, dict):
                for index, value_item in enumerate(item):
                    visit(value_item, child, f"{location}[{index}]")
        if isinstance(item, dict):
            properties = rule.get("properties")
            if not isinstance(properties, dict):
                properties = {}
            required = rule.get("required")
            if isinstance(required, list):
                for name in required:
                    if name not in item:
                        errors.append(f"{location}.{name} is required")
            additional = rule.get("additionalProperties", True)
            for name, value_item in item.items():
                child_location = f"{location}.{name}"
                child = properties.get(name)
                if isinstance(child, dict):
                    visit(value_item, child, child_location)
                elif additional is False:
                    errors.append(f"{child_location} is not allowed")
                elif isinstance(additional, dict):
                    visit(value_item, additional, child_location)

    visit(value, schema, path)
    if errors:
        raise ValueError("; ".join(errors))


def load_audit_schemas(
    root: Path, audit_contract: dict[str, Any]
) -> tuple[Path, dict[str, Any], Path, dict[str, Any]]:
    record_path = resolve_schema_path(
        root, audit_contract.get("recordSchema"), label="auditContract.recordSchema"
    )
    manifest_path = resolve_schema_path(
        root, audit_contract.get("manifestSchema"), label="auditContract.manifestSchema"
    )
    return (
        record_path,
        load_schema(record_path, label="audit record schema"),
        manifest_path,
        load_schema(manifest_path, label="audit manifest schema"),
    )
