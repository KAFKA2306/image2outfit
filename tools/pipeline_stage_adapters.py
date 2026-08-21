#!/usr/bin/env python3
"""Executable adapters and capability-based selection for pipeline tools."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from image2outfit.execution import (
    StageExecutionBinding,
    StageResultRequirement,
    validate_stage_result,
)
from image2outfit.pipeline import PIPELINE_STAGES, PipelineStage
from image2outfit.tooling import ToolDescriptor, ToolRegistry, choose_tool


class PlannedStageAdapter:
    def __init__(
        self,
        *,
        tool_name: str,
        purpose: str,
        command: Sequence[str] = (),
        result_path: str = "",
        required_in_execute: bool,
    ) -> None:
        self.tool_name = tool_name
        self.purpose = purpose
        self.command = tuple(command)
        self.result_path = result_path
        self.required_in_execute = required_in_execute

    def __call__(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "mode": "planned",
            "toolName": self.tool_name,
            "purpose": self.purpose,
            "command": list(self.command),
            "resultPath": self.result_path,
            "bound": bool(self.command and self.result_path),
            "requiredInExecute": self.required_in_execute,
            "productId": state["product_id"],
        }


class MissingExecutionBindingAdapter(PlannedStageAdapter):
    def __call__(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        raise RuntimeError(
            f"required execution binding is incomplete for tool {self.tool_name!r}; "
            "both command and resultPath are required"
        )


class CommandStageAdapter(PlannedStageAdapter):
    def __init__(
        self,
        *,
        stage: PipelineStage,
        tool_name: str,
        purpose: str,
        command: Sequence[str],
        result_path: str,
        execute: bool,
        required_in_execute: bool,
        result_requirement: StageResultRequirement,
    ) -> None:
        super().__init__(
            tool_name=tool_name,
            purpose=purpose,
            command=command,
            result_path=result_path,
            required_in_execute=required_in_execute,
        )
        self.stage = stage
        self.execute = execute
        self.result_requirement = result_requirement

    @staticmethod
    def _repo_path(value: str, *, label: str) -> Path:
        path = Path(value)
        resolved = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
        if resolved != ROOT and ROOT not in resolved.parents:
            raise ValueError(f"{label} escapes repository: {value}")
        return resolved

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def __call__(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        planned = dict(super().__call__(state))
        if not self.execute:
            return planned

        result_path = self._repo_path(self.result_path, label="resultPath")
        runtime_root = (ROOT / ".image2outfit").resolve()
        if result_path != runtime_root and runtime_root not in result_path.parents:
            raise ValueError("resultPath must be inside .image2outfit runtime state")
        if result_path.exists():
            if not result_path.is_file():
                raise ValueError(f"resultPath is not a file: {self.result_path}")
            result_path.unlink()
        result_path.parent.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            self.command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"stage command failed with exit code {result.returncode}: "
                f"{' '.join(self.command)}\n{result.stderr}"
            )

        if not result_path.is_file():
            raise FileNotFoundError(
                f"stage result file was not created: {self.result_path}"
            )
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"stage result file is invalid JSON: {self.result_path}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise ValueError("stage result JSON must be an object")
        validated = validate_stage_result(
            payload,
            expected_stage=self.stage.value,
            expected_product_id=str(state["product_id"]),
            requirement=self.result_requirement,
        )
        for item in validated["evidence"]:
            evidence_path = self._repo_path(item["path"], label="evidence path")
            if not evidence_path.is_file():
                raise FileNotFoundError(
                    f"stage evidence file is missing: {item['path']}"
                )
            actual = self._sha256(evidence_path)
            if actual != item["sha256"]:
                raise ValueError(
                    f"stage evidence hash mismatch for {item['path']}: "
                    f"expected {item['sha256']}, found {actual}"
                )
        return {
            **planned,
            "mode": "executed",
            "returnCode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "result": validated,
        }


def _string_list(value: object, *, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ValueError(f"{label} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{label} must not contain duplicates")
    return list(value)


def _tool_options(stage: Mapping[str, Any]) -> list[dict[str, Any]]:
    declared = stage.get("tools")
    if declared is None:
        return [
            {
                "toolName": stage.get("toolName"),
                "purpose": stage.get("purpose"),
                "requiredInExecute": stage.get("requiredInExecute"),
                "minimumEvidenceCount": stage.get("minimumEvidenceCount"),
                "requiredResultFields": stage.get("requiredResultFields", {}),
                "capabilities": stage.get("capabilities", []),
                "requires": stage.get("requires", []),
                "provides": stage.get("provides", []),
                "runtime": stage.get("runtime", "python"),
                "priority": stage.get("priority", 100),
                "deterministic": stage.get("deterministic", True),
            }
        ]
    if not isinstance(declared, list) or not declared:
        raise ValueError(f"stage {stage.get('stage')!r} tools must be a non-empty list")
    options: list[dict[str, Any]] = []
    for raw in declared:
        if not isinstance(raw, Mapping):
            raise ValueError(f"stage {stage.get('stage')!r} tool entries must be objects")
        options.append(
            {
                "toolName": raw.get("toolName"),
                "purpose": raw.get("purpose", stage.get("purpose")),
                "requiredInExecute": raw.get(
                    "requiredInExecute", stage.get("requiredInExecute")
                ),
                "minimumEvidenceCount": raw.get(
                    "minimumEvidenceCount", stage.get("minimumEvidenceCount")
                ),
                "requiredResultFields": raw.get(
                    "requiredResultFields", stage.get("requiredResultFields", {})
                ),
                "capabilities": raw.get("capabilities", stage.get("capabilities", [])),
                "requires": raw.get("requires", stage.get("requires", [])),
                "provides": raw.get("provides", stage.get("provides", [])),
                "runtime": raw.get("runtime", stage.get("runtime", "python")),
                "priority": raw.get("priority", stage.get("priority", 100)),
                "deterministic": raw.get(
                    "deterministic", stage.get("deterministic", True)
                ),
            }
        )
    return options


def _validate_tool_option(stage_name: str, option: Mapping[str, Any]) -> None:
    tool_name = option.get("toolName")
    if not isinstance(tool_name, str) or not tool_name:
        raise ValueError(f"stage {stage_name!r} toolName is required")
    if not isinstance(option.get("purpose"), str) or not option["purpose"]:
        raise ValueError(f"tool {tool_name!r} purpose is required")
    if not isinstance(option.get("requiredInExecute"), bool):
        raise ValueError(f"tool {tool_name!r} must declare requiredInExecute")
    minimum = option.get("minimumEvidenceCount")
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 0:
        raise ValueError(f"tool {tool_name!r} minimumEvidenceCount is invalid")
    required_fields = option.get("requiredResultFields", {})
    if not isinstance(required_fields, dict):
        raise ValueError(f"tool {tool_name!r} requiredResultFields must be an object")
    for key in ("capabilities", "requires", "provides"):
        _string_list(option.get(key, []), label=f"tool {tool_name!r} {key}")
    if not isinstance(option.get("runtime"), str) or not option["runtime"]:
        raise ValueError(f"tool {tool_name!r} runtime is required")
    priority = option.get("priority")
    if isinstance(priority, bool) or not isinstance(priority, int):
        raise ValueError(f"tool {tool_name!r} priority must be an integer")
    if not isinstance(option.get("deterministic"), bool):
        raise ValueError(f"tool {tool_name!r} deterministic must be boolean")


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
        options = _tool_options(item)
        names = []
        for option in options:
            _validate_tool_option(str(item["stage"]), option)
            names.append(str(option["toolName"]))
        if len(names) != len(set(names)):
            raise ValueError(f"stage {item['stage']!r} declares duplicate tool names")
        outputs = item.get("managedOutputs")
        if not isinstance(outputs, list) or not outputs:
            raise ValueError(f"stage {item['stage']!r} managedOutputs are required")
    return profile


def _known_binding_keys(profile: Mapping[str, Any]) -> set[str]:
    result = {stage.value for stage in PIPELINE_STAGES}
    for item in profile["stages"]:
        result.update(str(option["toolName"]) for option in _tool_options(item))
    return result


def _normalized_bindings(
    bindings: Mapping[str, Any], known: set[str]
) -> dict[str, StageExecutionBinding]:
    unknown = sorted(set(bindings).difference(known))
    if unknown:
        raise ValueError(f"unknown stage/tool bindings: {unknown}")
    normalized: dict[str, StageExecutionBinding] = {}
    for binding_name, raw_binding in bindings.items():
        if not isinstance(raw_binding, Mapping):
            raise ValueError(f"binding {binding_name!r} must be an object")
        command = raw_binding.get("command")
        result_path = raw_binding.get("resultPath")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(argument, str) and argument for argument in command)
        ):
            raise ValueError(
                f"binding {binding_name!r} command must be a non-empty string list"
            )
        if not isinstance(result_path, str) or not result_path:
            raise ValueError(f"binding {binding_name!r} resultPath is required")
        normalized[binding_name] = StageExecutionBinding(tuple(command), result_path)
    return normalized


def _policy_string_lists(
    value: Mapping[str, Any] | None, *, label: str
) -> dict[str, list[str]]:
    known = {stage.value for stage in PIPELINE_STAGES}
    result: dict[str, list[str]] = {}
    for stage_name, raw in (value or {}).items():
        if stage_name not in known:
            raise ValueError(f"unknown stage in {label}: {stage_name!r}")
        result[stage_name] = _string_list(raw, label=f"{label}.{stage_name}")
    return result


def _policy_pins(value: Mapping[str, Any] | None) -> dict[str, str]:
    known = {stage.value for stage in PIPELINE_STAGES}
    result: dict[str, str] = {}
    for stage_name, raw in (value or {}).items():
        if stage_name not in known:
            raise ValueError(f"unknown stage in toolPins: {stage_name!r}")
        if not isinstance(raw, str) or not raw:
            raise ValueError(f"toolPins.{stage_name} must be a non-empty string")
        result[stage_name] = raw
    return result


def build_registry(
    profile: Mapping[str, Any],
    *,
    execute: bool = False,
    bindings: Mapping[str, Any] | None = None,
    variables: Mapping[str, str] | None = None,
    tool_requirements: Mapping[str, Any] | None = None,
    tool_pins: Mapping[str, Any] | None = None,
) -> ToolRegistry:
    """Resolve one compatible tool per stage and bind it to the runtime.

    Selection is deterministic: declared capability requirements filter the toolset,
    prerequisite capabilities must have been provided by earlier selected stages,
    optional pins are validated, and remaining ties use stable priority/name ordering.
    """

    registry = ToolRegistry()
    normalized_bindings = _normalized_bindings(
        bindings or {}, _known_binding_keys(profile)
    )
    normalized_variables = {
        str(key): str(value) for key, value in (variables or {}).items()
    }
    requirements = _policy_string_lists(tool_requirements, label="toolRequirements")
    pins = _policy_pins(tool_pins)
    available_capabilities: set[str] = set()

    for item in profile["stages"]:
        stage = PipelineStage(item["stage"])
        options = _tool_options(item)
        descriptors = [
            ToolDescriptor(
                tool_name=str(option["toolName"]),
                purpose=str(option["purpose"]),
                output_contract=f"pipeline-output/{stage.value}.json",
                capabilities=frozenset(option.get("capabilities", [])),
                requires=frozenset(option.get("requires", [])),
                provides=frozenset(option.get("provides", [])),
                runtime=str(option.get("runtime", "python")),
                priority=int(option.get("priority", 100)),
                deterministic=bool(option.get("deterministic", True)),
            )
            for option in options
        ]
        selection = choose_tool(
            stage,
            descriptors,
            required_capabilities=requirements.get(stage.value, []),
            available_capabilities=sorted(available_capabilities),
            pin=pins.get(stage.value),
        )
        selected = next(
            option
            for option in options
            if option["toolName"] == selection.descriptor.tool_name
        )
        tool_name = selection.descriptor.tool_name
        purpose = selection.descriptor.purpose
        required_in_execute = bool(selected["requiredInExecute"])
        requirement = StageResultRequirement(
            minimum_evidence_count=int(selected["minimumEvidenceCount"]),
            required_fields=selected.get("requiredResultFields", {}),
        )
        binding = normalized_bindings.get(tool_name) or normalized_bindings.get(
            stage.value
        )
        command = binding.expand_command(normalized_variables) if binding else ()
        result_path = (
            binding.expand_result_path(normalized_variables) if binding else ""
        )
        if execute and required_in_execute and not (command and result_path):
            handler = MissingExecutionBindingAdapter(
                tool_name=tool_name,
                purpose=purpose,
                required_in_execute=required_in_execute,
            )
        else:
            handler = CommandStageAdapter(
                stage=stage,
                tool_name=tool_name,
                purpose=purpose,
                command=command,
                result_path=result_path,
                execute=execute and bool(command and result_path),
                required_in_execute=required_in_execute,
                result_requirement=requirement,
            )
        registry.register(stage, handler, selection.descriptor)
        registry.record_selection(stage, selection)
        available_capabilities.update(selection.descriptor.provides)
    return registry
