"""Stable execution specifications for Blender, cloth, rendering, and evidence."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True, slots=True)
class BlenderInvocation:
    executable: str
    python_script: str
    script_arguments: tuple[str, ...] = ()
    blend_file: str | None = None
    background: bool = True

    def argv(self) -> tuple[str, ...]:
        command: list[str] = [self.executable]
        if self.background:
            command.append("--background")
        if self.blend_file:
            command.append(self.blend_file)
        command.extend(("--python", self.python_script))
        if self.script_arguments:
            command.append("--")
            command.extend(self.script_arguments)
        return tuple(command)

    def validate(self) -> None:
        if not self.executable.strip():
            raise ValueError("Blender executable is required")
        if Path(self.python_script).suffix != ".py":
            raise ValueError("Blender python_script must be a Python file")


@dataclass(frozen=True, slots=True)
class ClothSimulationSpec:
    frame_start: int = 1
    frame_end: int = 120
    quality_steps: int = 12
    collision_distance_m: float = 0.004
    self_collision_distance_m: float = 0.004
    air_damping: float = 1.0
    use_self_collision: bool = True

    def validate(self) -> None:
        if self.frame_start < 0 or self.frame_end <= self.frame_start:
            raise ValueError("cloth frame range is invalid")
        if self.quality_steps < 1:
            raise ValueError("cloth quality_steps must be positive")
        for label, value in (
            ("collision_distance_m", self.collision_distance_m),
            ("self_collision_distance_m", self.self_collision_distance_m),
            ("air_damping", self.air_damping),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{label} must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class RenderEvidenceSpec:
    views: tuple[str, ...] = (
        "front",
        "back",
        "left",
        "right",
        "three-quarter",
    )
    poses: tuple[str, ...] = ()
    resolution_x: int = 1024
    resolution_y: int = 1024
    engine: str = "BLENDER_EEVEE_NEXT"
    transparent_background: bool = False
    metadata: Mapping[str, str] | None = None

    def validate(self) -> None:
        if len(self.views) != len(set(self.views)):
            raise ValueError("render views must be unique")
        if len(self.poses) != len(set(self.poses)):
            raise ValueError("render poses must be unique")
        if self.resolution_x < 256 or self.resolution_y < 256:
            raise ValueError("render evidence must be at least 256 by 256 pixels")
        required = {"front", "back", "left", "right", "three-quarter"}
        missing = sorted(required.difference(self.views))
        if missing:
            raise ValueError(f"render evidence is missing required views: {missing}")
