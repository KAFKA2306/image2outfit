"""Ports and registry used by deterministic and LangGraph orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol


class StageName(Protocol):
    @property
    def value(self) -> str: ...


StageHandler = Callable[[Mapping[str, Any]], Mapping[str, Any]]
DEFAULT_METHOD = "default"


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    tool_name: str
    purpose: str
    output_contract: str


class ToolRegistry:
    """Register one default implementation and optional alternatives per stage."""

    def __init__(self) -> None:
        self._handlers: dict[str, dict[str, StageHandler]] = {}
        self._descriptors: dict[str, dict[str, ToolDescriptor]] = {}
        self._defaults: dict[str, str] = {}

    @staticmethod
    def _stage_name(stage: StageName | str) -> str:
        return stage if isinstance(stage, str) else stage.value

    def register(
        self,
        stage: StageName | str,
        handler: StageHandler,
        descriptor: ToolDescriptor,
        *,
        method_id: str = DEFAULT_METHOD,
        default: bool | None = None,
    ) -> None:
        stage_name = self._stage_name(stage)
        if not method_id or not method_id.strip():
            raise ValueError("method_id must be a non-empty string")
        method_id = method_id.strip()
        handlers = self._handlers.setdefault(stage_name, {})
        descriptors = self._descriptors.setdefault(stage_name, {})
        if method_id in handlers:
            raise ValueError(
                f"method already registered for stage {stage_name!r}: {method_id!r}"
            )
        handlers[method_id] = handler
        descriptors[method_id] = descriptor
        if stage_name not in self._defaults or default is True:
            self._defaults[stage_name] = method_id

    def resolve_method(
        self,
        stage: StageName | str,
        method_id: str | None = None,
    ) -> str:
        stage_name = self._stage_name(stage)
        methods = self._handlers.get(stage_name)
        if not methods:
            raise KeyError(f"no tool is registered for stage {stage_name!r}")
        selected = method_id or self._defaults[stage_name]
        if selected not in methods:
            available = ", ".join(sorted(methods))
            raise KeyError(
                f"no method {selected!r} is registered for stage {stage_name!r}; "
                f"available: {available}"
            )
        return selected

    def invoke(
        self,
        stage: StageName | str,
        state: Mapping[str, Any],
        *,
        method_id: str | None = None,
    ) -> dict[str, Any]:
        stage_name = self._stage_name(stage)
        selected = self.resolve_method(stage_name, method_id)
        handler = self._handlers[stage_name][selected]
        result = handler(state)
        if not isinstance(result, Mapping):
            raise TypeError(f"stage {stage_name!r} returned a non-mapping result")
        return dict(result)

    def descriptor(
        self,
        stage: StageName | str,
        method_id: str | None = None,
    ) -> ToolDescriptor:
        stage_name = self._stage_name(stage)
        selected = self.resolve_method(stage_name, method_id)
        return self._descriptors[stage_name][selected]

    def available_methods(self, stage: StageName | str) -> tuple[str, ...]:
        stage_name = self._stage_name(stage)
        return tuple(sorted(self._handlers.get(stage_name, {})))

    def missing(self, stages: tuple[StageName, ...]) -> tuple[str, ...]:
        return tuple(stage.value for stage in stages if stage.value not in self._defaults)
