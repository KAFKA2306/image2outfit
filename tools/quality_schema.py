#!/usr/bin/env python3
"""Load and apply the declarative JSON Schema contracts for candidate quality."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "contracts" / "quality"


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict[str, Any]:
    schema = json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8-sig"))
    Draft202012Validator.check_schema(schema)
    return schema


def violations(schema: dict[str, Any], instance: Any) -> list[ValidationError]:
    errors = Draft202012Validator(schema).iter_errors(instance)
    return sorted(
        errors, key=lambda error: (list(map(str, error.absolute_path)), error.message)
    )


def path_label(*parts: Any) -> str:
    """Render a JSON path as the dotted form used in quality failure labels."""
    text = ""
    for part in parts:
        if isinstance(part, int):
            text += f"[{part}]"
        else:
            text = f"{text}.{part}" if text else str(part)
    return text


def violation_labels(schema: dict[str, Any], instance: Any) -> list[str]:
    """Return one label per failing field, naming missing required keys."""
    labels: list[str] = []
    for error in violations(schema, instance):
        if error.validator == "required":
            labels.extend(
                path_label(*error.absolute_path, name)
                for name in error.validator_value
                if name not in error.instance
            )
        else:
            labels.append(path_label(*error.absolute_path))
    return labels
