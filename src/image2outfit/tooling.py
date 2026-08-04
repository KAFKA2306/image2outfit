"""Ports and registry used by deterministic and LangGraph orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol


class StageName(Protocol):
    @property
    def value(self) -> str: ...


StageHandler = Callable[[Mapping[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    tool_name: str
    purpose: str
    output_contract: str


class ToolRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, StageHandler] = {}
        self._descriptors: dict[str, ToolDescriptor] = {}

    def register(
        self,
        stage: StageName | str,
        handler: StageHandler,
        descriptor: ToolDescriptor,
    ) -> None:
        stage_name = stage if isinstance(stage, str) else stage.value
        if stage_name in self._handlers:
            raise ValueError(f"stage already registered: {stage_name}")
        self._handlers[stage_name] = handler
        self._descriptors[stage_name] = descriptor

    def invoke(
        self, stage: StageName | str, state: Mapping[str, Any]
    ) -> dict[str, Any]:
        stage_name = stage if isinstance(stage, str) else stage.value
        try:
            handler = self._handlers[stage_name]
        except KeyError as exc:
            raise KeyError(f"no tool is registered for stage {stage_name!r}") from exc
        result = handler(state)
        if not isinstance(result, Mapping):
            raise TypeError(f"stage {stage_name!r} returned a non-mapping result")
        return dict(result)

    def descriptor(self, stage: StageName | str) -> ToolDescriptor:
        stage_name = stage if isinstance(stage, str) else stage.value
        return self._descriptors[stage_name]

    def missing(self, stages: tuple[StageName, ...]) -> tuple[str, ...]:
        return tuple(
            stage.value for stage in stages if stage.value not in self._handlers
        )
