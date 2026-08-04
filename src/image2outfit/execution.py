"""Stable execution-binding contracts for external stage tools."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from string import Formatter


class MissingTemplateVariableError(ValueError):
    """Raised when a command template references an undeclared variable."""


@dataclass(frozen=True, slots=True)
class StageExecutionBinding:
    """A shell-free command binding for one canonical pipeline stage."""

    command_template: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.command_template:
            raise ValueError("command_template must contain at least one argument")
        if any(not argument for argument in self.command_template):
            raise ValueError("command_template arguments must be non-empty")

    def expand(self, variables: Mapping[str, str]) -> tuple[str, ...]:
        return expand_command_template(self.command_template, variables)


def _field_names(value: str) -> tuple[str, ...]:
    formatter = Formatter()
    return tuple(
        field_name
        for _, field_name, _, _ in formatter.parse(value)
        if field_name is not None and field_name != ""
    )


def expand_command_template(
    command_template: Sequence[str], variables: Mapping[str, str]
) -> tuple[str, ...]:
    """Expand an argv template without invoking a shell or permitting attributes."""
    normalized = {str(key): str(value) for key, value in variables.items()}
    expanded: list[str] = []
    for argument in command_template:
        for field_name in _field_names(argument):
            if any(token in field_name for token in (".", "[", "]")):
                raise ValueError(
                    "command template fields must be simple identifiers: "
                    f"{field_name!r}"
                )
            if field_name not in normalized:
                raise MissingTemplateVariableError(
                    f"command template variable is missing: {field_name}"
                )
        expanded.append(argument.format_map(normalized))
    return tuple(expanded)
