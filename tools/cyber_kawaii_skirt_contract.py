#!/usr/bin/env python3
"""Validate and expose the Cyber Kawaii skirt production contract."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

PRODUCT_ID = "siroino-cyber-kawaii-large"
REQUIRED_STAGES = (
    "garmentCode",
    "zozoContactSolver",
    "materialMaker",
    "blender",
)
REQUIRED_LAYERS = (
    "Black_Pink_Plaid_Pleated_Skirt",
    "White_Ruffle_Underskirt",
    "Black_Skirt_Waistband",
    "Pink_Underskirt_Hem",
)
PROFILE_FIELDS = ("topScale", "bottomScale", "pleatScale", "zOffset")


@dataclass(frozen=True)
class PipelineEvidence:
    pattern_contract: str
    pattern_sha256: str
    garment_code: str
    zozo_contact_solver: str
    material_maker_source: str
    solver_mesh_present: bool
    solver_report_present: bool
    material_sources_present: bool


def load_contract(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_contract(data)
    return data


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    return float(value)


def validate_contract(data: dict[str, Any]) -> None:
    if data.get("schemaVersion") != 2:
        raise ValueError("contract schemaVersion must be 2")
    if data.get("productId") != PRODUCT_ID:
        raise ValueError(f"contract productId must be {PRODUCT_ID}")
    if data.get("units") != "m":
        raise ValueError("contract units must be m")

    stages = data.get("stages")
    if not isinstance(stages, dict) or tuple(stages) != REQUIRED_STAGES:
        raise ValueError(f"stages must be ordered as {REQUIRED_STAGES}")
    for stage_id in REQUIRED_STAGES:
        stage = stages[stage_id]
        if not isinstance(stage, dict) or not stage.get("source"):
            raise ValueError(f"stage {stage_id} requires a primary source URL")
        if stage.get("status") not in {"PASS", "PENDING"}:
            raise ValueError(f"stage {stage_id} status must be PASS or PENDING")

    construction = data.get("construction")
    if not isinstance(construction, dict):
        raise ValueError("construction must be an object")
    panels = construction.get("panels")
    seams = construction.get("seams")
    if not isinstance(panels, list) or not panels:
        raise ValueError("construction.panels must be a non-empty list")
    if not isinstance(seams, list) or not seams:
        raise ValueError("construction.seams must be a non-empty list")
    panel_ids = {str(panel.get("id")) for panel in panels}
    if len(panel_ids) != len(panels):
        raise ValueError("panel ids must be unique")
    for seam in seams:
        pair = seam.get("pair")
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError("each seam requires exactly two edge references")
        for edge_ref in pair:
            panel_id = str(edge_ref).split(".", 1)[0]
            if panel_id not in panel_ids:
                raise ValueError(f"seam references missing panel {panel_id}")

    profiles = data.get("silhouetteProfiles")
    if not isinstance(profiles, dict) or tuple(profiles) != REQUIRED_LAYERS:
        raise ValueError(f"silhouetteProfiles must be ordered as {REQUIRED_LAYERS}")
    for layer_id, raw in profiles.items():
        if not isinstance(raw, dict) or set(raw) != set(PROFILE_FIELDS):
            raise ValueError(f"{layer_id} must define {PROFILE_FIELDS}")
        top = _number(raw["topScale"], f"{layer_id}.topScale")
        bottom = _number(raw["bottomScale"], f"{layer_id}.bottomScale")
        pleat = _number(raw["pleatScale"], f"{layer_id}.pleatScale")
        z_offset = _number(raw["zOffset"], f"{layer_id}.zOffset")
        if not 0.5 <= top <= 1.1 or not 0.5 <= bottom <= 1.1:
            raise ValueError(f"{layer_id} scale is outside the reviewed range")
        if not 0.0 <= pleat <= 1.0:
            raise ValueError(f"{layer_id}.pleatScale must be between zero and one")
        if abs(z_offset) > 0.03:
            raise ValueError(f"{layer_id}.zOffset is outside the reviewed range")

    outputs = data.get("expectedOutputs")
    required_outputs = {
        "solverMesh",
        "solverReport",
        "materialSourceRoot",
        "blend",
        "fbx",
        "prefab",
        "multiview",
        "poseReview",
    }
    if not isinstance(outputs, dict) or set(outputs) != required_outputs:
        raise ValueError(f"expectedOutputs must contain {sorted(required_outputs)}")


def silhouette_profiles(data: dict[str, Any]) -> dict[str, dict[str, float]]:
    validate_contract(data)
    return {
        layer_id: {
            field: float(raw[field])
            for field in PROFILE_FIELDS
        }
        for layer_id, raw in data["silhouetteProfiles"].items()
    }


def evidence_state(root: Path, contract_path: Path, data: dict[str, Any]) -> PipelineEvidence:
    validate_contract(data)
    outputs = data["expectedOutputs"]
    solver_mesh = root / outputs["solverMesh"]
    solver_report = root / outputs["solverReport"]
    material_root = root / outputs["materialSourceRoot"]
    material_sources = tuple(material_root.glob("*.ptex")) if material_root.is_dir() else ()
    return PipelineEvidence(
        pattern_contract="PASS",
        pattern_sha256=sha256(contract_path),
        garment_code=data["stages"]["garmentCode"]["status"],
        zozo_contact_solver=(
            "PASS" if solver_mesh.is_file() and solver_report.is_file() else "PENDING"
        ),
        material_maker_source="PASS" if material_sources else "PENDING",
        solver_mesh_present=solver_mesh.is_file(),
        solver_report_present=solver_report.is_file(),
        material_sources_present=bool(material_sources),
    )


def material_maker_commands(data: dict[str, Any], root: Path) -> tuple[list[str], ...]:
    validate_contract(data)
    executable = str(data["stages"]["materialMaker"].get("executable", "material_maker"))
    material_root = root / data["expectedOutputs"]["materialSourceRoot"]
    texture_root = root / "Assets/GenWorks/siroino-cyber-kawaii-large/Textures"
    commands: list[list[str]] = []
    for source_name in data["stages"]["materialMaker"].get("requiredSources", []):
        commands.append(
            [
                executable,
                "--export-material",
                "--target",
                "Blender",
                "-o",
                str(texture_root),
                str(material_root / source_name),
            ]
        )
    return tuple(commands)
