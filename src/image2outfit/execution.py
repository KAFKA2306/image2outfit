"""Stable execution-binding and stage-result contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from string import Formatter
from typing import Any

_HASH = re.compile(r"^[0-9a-f]{64}$")
_JSON_SCALAR = str | int | float | bool | None


class MissingTemplateVariableError(ValueError):
    """Raised when a command template references an undeclared variable."""


@dataclass(frozen=True, slots=True)
class StageExecutionBinding:
    """A shell-free command and result-file binding for one pipeline stage."""

    command_template: tuple[str, ...]
    result_path_template: str = ""

    def __post_init__(self) -> None:
        if not self.command_template:
            raise ValueError("command_template must contain at least one argument")
        if any(not argument for argument in self.command_template):
            raise ValueError("command_template arguments must be non-empty")

    def expand(self, variables: Mapping[str, str]) -> tuple[str, ...]:
        """Compatibility alias for command expansion."""
        return self.expand_command(variables)

    def expand_command(self, variables: Mapping[str, str]) -> tuple[str, ...]:
        return expand_command_template(self.command_template, variables)

    def expand_result_path(self, variables: Mapping[str, str]) -> str:
        if not self.result_path_template:
            return ""
        return expand_template(self.result_path_template, variables)


@dataclass(frozen=True, slots=True)
class StageResultRequirement:
    minimum_evidence_count: int = 1
    required_fields: Mapping[str, _JSON_SCALAR] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.minimum_evidence_count < 0:
            raise ValueError("minimum_evidence_count must be non-negative")
        if not all(isinstance(key, str) and key for key in self.required_fields):
            raise ValueError("required_fields keys must be non-empty strings")


def _field_names(value: str) -> tuple[str, ...]:
    formatter = Formatter()
    return tuple(
        field_name
        for _, field_name, _, _ in formatter.parse(value)
        if field_name is not None and field_name != ""
    )


def expand_template(value: str, variables: Mapping[str, str]) -> str:
    normalized = {str(key): str(item) for key, item in variables.items()}
    for field_name in _field_names(value):
        if any(token in field_name for token in (".", "[", "]")):
            raise ValueError(
                f"template fields must be simple identifiers: {field_name!r}"
            )
        if field_name not in normalized:
            raise MissingTemplateVariableError(
                f"template variable is missing: {field_name}"
            )
    return value.format_map(normalized)


def expand_command_template(
    command_template: Sequence[str], variables: Mapping[str, str]
) -> tuple[str, ...]:
    """Expand an argv template without invoking a shell or permitting attributes."""
    return tuple(expand_template(argument, variables) for argument in command_template)


def validate_stage_result(
    payload: Mapping[str, Any],
    *,
    expected_stage: str,
    expected_product_id: str,
    requirement: StageResultRequirement,
) -> dict[str, Any]:
    """Validate one external stage result before it can advance the pipeline."""
    if payload.get("schemaVersion") != 1:
        raise ValueError("stage result schemaVersion must be 1")
    if payload.get("stage") != expected_stage:
        raise ValueError(
            f"stage result is for {payload.get('stage')!r}, expected {expected_stage!r}"
        )
    if payload.get("productId") != expected_product_id:
        raise ValueError("stage result productId does not match the pipeline product")
    if payload.get("status") != "PASS":
        raise ValueError("stage result status must be PASS")

    for field_name, expected in requirement.required_fields.items():
        if payload.get(field_name) != expected:
            raise ValueError(
                f"stage result field {field_name!r} must equal {expected!r}"
            )

    evidence = payload.get("evidence")
    if not isinstance(evidence, list):
        raise ValueError("stage result evidence must be a list")
    if len(evidence) < requirement.minimum_evidence_count:
        raise ValueError(
            "stage result evidence count is below the required minimum: "
            f"{len(evidence)} < {requirement.minimum_evidence_count}"
        )

    seen_hashes: set[str] = set()
    normalized_evidence: list[dict[str, str]] = []
    for index, item in enumerate(evidence):
        if not isinstance(item, Mapping):
            raise ValueError(f"stage evidence {index} must be an object")
        path = item.get("path")
        digest = item.get("sha256")
        if not isinstance(path, str) or not path:
            raise ValueError(f"stage evidence {index} path is required")
        if not isinstance(digest, str) or not _HASH.fullmatch(digest):
            raise ValueError(
                f"stage evidence {index} sha256 must be 64 lowercase hex characters"
            )
        if digest in seen_hashes:
            raise ValueError("stage evidence hashes must be unique")
        seen_hashes.add(digest)
        normalized_evidence.append({"path": path, "sha256": digest})

    return {**dict(payload), "evidence": normalized_evidence}
