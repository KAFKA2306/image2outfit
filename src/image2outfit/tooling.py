"""Tool contracts, deterministic selection, and stage registry orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol


class StageName(Protocol):
    @property
    def value(self) -> str: ...


StageHandler = Callable[[Mapping[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    """Describe one selectable implementation for a pipeline stage."""

    tool_name: str
    purpose: str
    output_contract: str
    capabilities: frozenset[str] = field(default_factory=frozenset)
    requires: frozenset[str] = field(default_factory=frozenset)
    provides: frozenset[str] = field(default_factory=frozenset)
    runtime: str = "python"
    priority: int = 100
    deterministic: bool = True

    def __post_init__(self) -> None:
        if not self.tool_name:
            raise ValueError("tool_name is required")
        if not self.purpose:
            raise ValueError("purpose is required")
        if not self.output_contract:
            raise ValueError("output_contract is required")
        if not self.runtime:
            raise ValueError("runtime is required")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise ValueError("priority must be an integer")
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        object.__setattr__(self, "requires", frozenset(self.requires))
        object.__setattr__(self, "provides", frozenset(self.provides))
        for label, values in (
            ("capabilities", self.capabilities),
            ("requires", self.requires),
            ("provides", self.provides),
        ):
            if not all(isinstance(value, str) and value for value in values):
                raise ValueError(f"{label} must contain non-empty strings")


@dataclass(frozen=True, slots=True)
class ToolSelection:
    """Auditable result of selecting one implementation from a stage toolset."""

    stage: str
    descriptor: ToolDescriptor
    required_capabilities: frozenset[str]
    available_capabilities: frozenset[str]
    pinned: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "toolName": self.descriptor.tool_name,
            "runtime": self.descriptor.runtime,
            "priority": self.descriptor.priority,
            "deterministic": self.descriptor.deterministic,
            "requiredCapabilities": sorted(self.required_capabilities),
            "capabilities": sorted(self.descriptor.capabilities),
            "requires": sorted(self.descriptor.requires),
            "provides": sorted(self.descriptor.provides),
            "availableCapabilitiesBefore": sorted(self.available_capabilities),
            "pinned": self.pinned,
            "reason": self.reason,
        }


def _stage_name(stage: StageName | str) -> str:
    return stage if isinstance(stage, str) else stage.value


def choose_tool(
    stage: StageName | str,
    candidates: Sequence[ToolDescriptor],
    *,
    required_capabilities: Sequence[str] = (),
    available_capabilities: Sequence[str] = (),
    pin: str | None = None,
) -> ToolSelection:
    """Choose a compatible tool by contract, then stable priority and name.

    Agentic planners may propose requirements or a pin upstream, but this selector
    never lets an agent bypass capability or prerequisite contracts. A single
    compatible implementation is selected without an LLM; ties are resolved
    deterministically.
    """

    name = _stage_name(stage)
    required = frozenset(required_capabilities)
    available = frozenset(available_capabilities)
    if not candidates:
        raise ValueError(f"no tools are declared for stage {name!r}")
    by_name = {item.tool_name: item for item in candidates}
    if len(by_name) != len(candidates):
        raise ValueError(f"duplicate tool names are declared for stage {name!r}")
    if pin is not None and pin not in by_name:
        raise ValueError(
            f"pinned tool {pin!r} is not declared for stage {name!r}; "
            f"available: {', '.join(sorted(by_name))}"
        )

    pool = [by_name[pin]] if pin is not None else list(candidates)
    eligible: list[ToolDescriptor] = []
    rejected: list[str] = []
    for descriptor in pool:
        missing_capabilities = sorted(required - descriptor.capabilities)
        missing_prerequisites = sorted(descriptor.requires - available)
        if missing_capabilities or missing_prerequisites:
            reasons = []
            if missing_capabilities:
                reasons.append("missing capabilities=" + ",".join(missing_capabilities))
            if missing_prerequisites:
                reasons.append(
                    "missing prerequisites=" + ",".join(missing_prerequisites)
                )
            rejected.append(f"{descriptor.tool_name} ({'; '.join(reasons)})")
            continue
        eligible.append(descriptor)

    if not eligible:
        detail = "; ".join(rejected) if rejected else "no compatible candidate"
        raise ValueError(f"no compatible tool for stage {name!r}: {detail}")

    selected = min(eligible, key=lambda item: (item.priority, item.tool_name))
    if pin is not None:
        reason = "explicit tool pin after capability validation"
    elif len(eligible) == 1:
        reason = "only compatible implementation"
    else:
        reason = "lowest stable priority among compatible implementations"
    return ToolSelection(
        stage=name,
        descriptor=selected,
        required_capabilities=required,
        available_capabilities=available,
        pinned=pin is not None,
        reason=reason,
    )


class ToolRegistry:
    """Runtime registry containing exactly the selected tool for each stage."""

    def __init__(self) -> None:
        self._handlers: dict[str, StageHandler] = {}
        self._descriptors: dict[str, ToolDescriptor] = {}
        self._selections: dict[str, ToolSelection] = {}
        self._selection_order: list[str] = []

    def register(
        self,
        stage: StageName | str,
        handler: StageHandler,
        descriptor: ToolDescriptor,
    ) -> None:
        stage_name = _stage_name(stage)
        if stage_name in self._handlers:
            raise ValueError(f"stage already registered: {stage_name}")
        self._handlers[stage_name] = handler
        self._descriptors[stage_name] = descriptor

    def record_selection(
        self, stage: StageName | str, selection: ToolSelection
    ) -> None:
        stage_name = _stage_name(stage)
        if selection.stage != stage_name:
            raise ValueError("tool selection stage does not match registry stage")
        if stage_name not in self._handlers:
            raise KeyError(f"stage is not registered: {stage_name}")
        if self._descriptors[stage_name] != selection.descriptor:
            raise ValueError("tool selection descriptor does not match registered tool")
        if stage_name not in self._selections:
            self._selection_order.append(stage_name)
        self._selections[stage_name] = selection

    def invoke(
        self, stage: StageName | str, state: Mapping[str, Any]
    ) -> dict[str, Any]:
        stage_name = _stage_name(stage)
        try:
            handler = self._handlers[stage_name]
        except KeyError as exc:
            raise KeyError(f"no tool is registered for stage {stage_name!r}") from exc
        result = handler(state)
        if not isinstance(result, Mapping):
            raise TypeError(f"stage {stage_name!r} returned a non-mapping result")
        return dict(result)

    def descriptor(self, stage: StageName | str) -> ToolDescriptor:
        return self._descriptors[_stage_name(stage)]

    def selection(self, stage: StageName | str) -> ToolSelection | None:
        return self._selections.get(_stage_name(stage))

    def selection_plan(self) -> list[dict[str, Any]]:
        return [self._selections[name].as_dict() for name in self._selection_order]

    def missing(self, stages: tuple[StageName, ...]) -> tuple[str, ...]:
        return tuple(
            stage.value for stage in stages if stage.value not in self._handlers
        )
