#!/usr/bin/env python3
"""Executable adapters for the stable image2outfit pipeline contracts."""

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
from image2outfit.tooling import ToolDescriptor, ToolRegistry


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
        if not isinstance(item.get("toolName"), str) or not item["toolName"]:
            raise ValueError(f"stage {item.get('stage')!r} toolName is required")
        if not isinstance(item.get("purpose"), str) or not item["purpose"]:
            raise ValueError(f"stage {item.get('stage')!r} purpose is required")
        if not isinstance(item.get("requiredInExecute"), bool):
            raise ValueError(
                f"stage {item.get('stage')!r} must declare requiredInExecute"
            )
        minimum = item.get("minimumEvidenceCount")
        if not isinstance(minimum, int) or minimum < 0:
            raise ValueError(
                f"stage {item.get('stage')!r} minimumEvidenceCount is invalid"
            )
        required_fields = item.get("requiredResultFields", {})
        if not isinstance(required_fields, dict):
            raise ValueError(
                f"stage {item.get('stage')!r} requiredResultFields must be an object"
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
        result_path = raw_binding.get("resultPath")
        if not isinstance(command, list) or not command or not all(
            isinstance(argument, str) and argument for argument in command
        ):
            raise ValueError(
                f"stage binding {stage_name!r} command must be a non-empty string list"
            )
        if not isinstance(result_path, str) or not result_path:
            raise ValueError(f"stage binding {stage_name!r} resultPath is required")
        normalized[stage_name] = StageExecutionBinding(tuple(command), result_path)
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
        tool_name = item["toolName"]
        purpose = item["purpose"]
        required_in_execute = item["requiredInExecute"]
        requirement = StageResultRequirement(
            minimum_evidence_count=item["minimumEvidenceCount"],
            required_fields=item.get("requiredResultFields", {}),
        )
        binding = normalized_bindings.get(stage.value)
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
