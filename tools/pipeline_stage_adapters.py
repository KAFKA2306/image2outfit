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

from image2outfit.pipeline import PIPELINE_STAGES, PipelineStage
from image2outfit.tooling import ToolDescriptor, ToolRegistry


class PlannedStageAdapter:
    def __init__(self, *, tool_name: str, purpose: str, command: Sequence[str] = ()):
        self.tool_name = tool_name
        self.purpose = purpose
        self.command = tuple(command)

    def __call__(self, state: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "mode": "planned",
            "toolName": self.tool_name,
            "purpose": self.purpose,
            "command": list(self.command),
            "productId": state["product_id"],
        }


class CommandStageAdapter(PlannedStageAdapter):
    def __init__(
        self,
        *,
        tool_name: str,
        purpose: str,
        command: Sequence[str],
        execute: bool,
    ) -> None:
        super().__init__(tool_name=tool_name, purpose=purpose, command=command)
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
    return profile


def build_registry(
    profile: Mapping[str, Any], *, execute: bool = False
) -> ToolRegistry:
    registry = ToolRegistry()
    for item in profile["stages"]:
        stage = PipelineStage(item["stage"])
        tool_name = str(item["toolName"])
        purpose = str(item["purpose"])
        command = tuple(str(value) for value in item.get("command", []))
        handler = CommandStageAdapter(
            tool_name=tool_name,
            purpose=purpose,
            command=command,
            execute=execute and bool(command),
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
