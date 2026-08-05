#!/usr/bin/env python3
"""Executable adapters for the stable image2outfit pipeline contracts."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

import sys

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from image2outfit.execution import StageExecutionBinding
from image2outfit.pipeline import PIPELINE_STAGES, PipelineStage
from image2outfit.tooling import ToolDescriptor, ToolRegistry


class PlannedStageAdapter:
    def __init__(
        self,
        *,
        tool_name: str,
        purpose: str,
        command: Sequence[str] = (),
        required_in_execute: bool,
    ) -> None:
        self.tool_name = tool_name
        self.purpose = purpose
        self.command = tuple(command)
        self.required_in_execute = required_in_execute

    def __call__(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "mode": "planned",
            "toolName": self.tool_name,
            "purpose": self.purpose,
            "command": list(self.command),
            "bound": bool(self.command),
            "requiredInExecute": self.required_in_execute,
            "productId": state["product_id"],
        }


class MissingExecutionBindingAdapter(PlannedStageAdapter):
    def __call__(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        raise RuntimeError(
            f"required execution binding is missing for tool {self.tool_name!r}"
        )


class CommandStageAdapter(PlannedStageAdapter):
    def __init__(
        self,
        *,
        tool_name: str,
        purpose: str,
        command: Sequence[str],
        execute: bool,
        required_in_execute: bool,
    ) -> None:
        super().__init__(
            tool_name=tool_name,
            purpose=purpose,
            command=command,
            required_in_execute=required_in_execute,
        )
        self.execute = execute

    def __call__(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        planned = dict(super().__call__(state))
        if not self.execute:
            return planned
        result = subprocess.run(
            self.command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        planned.update(
            {
                "mode": "executed",
                "returnCode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"stage command failed with exit code {result.returncode}: "
                f"{' '.join(self.command)}"
            )
        return planned


def load_profile(path: Path) -> dict[str, Any]:
    profile = json.loads(path.read_text(encoding="utf-8"))
    if profile.get("schemaVersion") != 1:
        raise ValueError("pipeline profile schemaVersion must be 1")
    declared = profile.get("stages")
    if not isinstance(declared, list):
        raise ValueError("pipeline profile stages must be a list")
    names = [item.get("stage") for item in declared if isinstance(item, dict)]
    expected = [stage.value for stage in PIPELINE_STAGES]
    if names != expected:
        raise ValueError("pipeline profile stages do not match the canonical order")
    for item in declared:
        if not isinstance(item, dict):
            raise ValueError("pipeline profile stage entries must be objects")
        if not isinstance(item.get("requiredInExecute"), bool):
            raise ValueError(
                f"stage {item.get('stage')!r} must declare requiredInExecute"
            )
    return profile


def _normalized_bindings(
    bindings: Mapping[str, Any],
) -> dict[str, StageExecutionBinding]:
    known = {stage.value for stage in PIPELINE_STAGES}
    unknown = sorted(set(bindings).difference(known))
    if unknown:
        raise ValueError(f"unknown stage bindings: {unknown}")
    normalized: dict[str, StageExecutionBinding] = {}
    for stage_name, raw_binding in bindings.items():
        if not isinstance(raw_binding, Mapping):
            raise ValueError(f"stage binding {stage_name!r} must be an object")
        command = raw_binding.get("command")
        if not isinstance(command, list) or not all(
            isinstance(argument, str) and argument for argument in command
        ):
            raise ValueError(
                f"stage binding {stage_name!r} command must be a non-empty string list"
            )
        normalized[stage_name] = StageExecutionBinding(tuple(command))
    return normalized


def build_registry(
    profile: Mapping[str, Any],
    *,
    execute: bool = False,
    bindings: Mapping[str, Any] | None = None,
    variables: Mapping[str, str] | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    normalized_bindings = _normalized_bindings(bindings or {})
    normalized_variables = {
        str(key): str(value) for key, value in (variables or {}).items()
    }
    for item in profile["stages"]:
        stage = PipelineStage(item["stage"])
        tool_name = str(item["toolName"])
        purpose = str(item["purpose"])
        required_in_execute = bool(item["requiredInExecute"])
        binding = normalized_bindings.get(stage.value)
        command = binding.expand(normalized_variables) if binding else ()
        if execute and required_in_execute and not command:
            handler = MissingExecutionBindingAdapter(
                tool_name=tool_name,
                purpose=purpose,
                required_in_execute=required_in_execute,
            )
        else:
            handler = CommandStageAdapter(
                tool_name=tool_name,
                purpose=purpose,
                command=command,
                execute=execute and bool(command),
                required_in_execute=required_in_execute,
            )
        registry.register(
            stage,
            handler,
            ToolDescriptor(
                tool_name=tool_name,
                purpose=purpose,
                output_contract=f"pipeline-output/{stage.value}.json",
            ),
        )
    return registry
