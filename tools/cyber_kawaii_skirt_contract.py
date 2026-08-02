#!/usr/bin/env python3
"""Contract utilities for the Cyber Kawaii pattern-first skirt pipeline."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

PRODUCT_ID = "siroino-cyber-kawaii-large"
REQUIRED_LAYER_IDS = (
    "Black_Skirt_Waistband",
    "Black_Pink_Plaid_Pleated_Skirt",
    "White_Ruffle_Underskirt",
    "Pink_Underskirt_Hem",
)
REQUIRED_STAGE_IDS = ("garmentCode", "zozoContactSolver", "materialMaker", "blender")


@dataclass(frozen=True)
class RingSpec:
    z: float
    anchor: str
    ease_x: float
    ease_y: float


@dataclass(frozen=True)
class LayerSpec:
    object_name: str
    order: int
    pleats: int
    thickness: float
    rings: tuple[RingSpec, ...]


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    return float(value)


def _ring(raw: dict[str, Any], label: str) -> RingSpec:
    anchor = raw.get("anchor")
    if anchor not in {"waist", "hip"}:
        raise ValueError(f"{label}.anchor must be waist or hip")
    return RingSpec(
        z=_number(raw.get("z"), f"{label}.z"),
        anchor=anchor,
        ease_x=_number(raw.get("easeX"), f"{label}.easeX"),
        ease_y=_number(raw.get("easeY"), f"{label}.easeY"),
    )


def load_contract(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_contract(data)
    return data


def contract_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_contract(data: dict[str, Any]) -> None:
    if data.get("schemaVersion") != 1:
        raise ValueError("pattern contract schemaVersion must be 1")
    if data.get("productId") != PRODUCT_ID:
        raise ValueError(f"pattern contract productId must be {PRODUCT_ID}")
    if data.get("units") != "m":
        raise ValueError("pattern contract units must be m")

    stages = data.get("stages")
    if not isinstance(stages, dict) or tuple(stages) != REQUIRED_STAGE_IDS:
        raise ValueError(f"stages must be ordered as {REQUIRED_STAGE_IDS}")
    for stage_id in REQUIRED_STAGE_IDS:
        stage = stages[stage_id]
        if not isinstance(stage, dict) or not stage.get("source"):
            raise ValueError(f"stage {stage_id} requires a primary source URL")

    anchors = data.get("bodyAnchors")
    if not isinstance(anchors, dict) or set(anchors) != {"waist", "hip"}:
        raise ValueError("bodyAnchors must contain exactly waist and hip")
    for anchor_id, anchor in anchors.items():
        _number(anchor.get("z"), f"bodyAnchors.{anchor_id}.z")
        band = _number(anchor.get("halfBand"), f"bodyAnchors.{anchor_id}.halfBand")
        if band <= 0.0:
            raise ValueError(f"bodyAnchors.{anchor_id}.halfBand must be positive")

    layers = data.get("layers")
    if not isinstance(layers, list):
        raise ValueError("layers must be a list")
    names = tuple(layer.get("objectName") for layer in layers)
    if names != REQUIRED_LAYER_IDS:
        raise ValueError(f"layers must be ordered as {REQUIRED_LAYER_IDS}")
    orders = [layer.get("order") for layer in layers]
    if orders != list(range(len(REQUIRED_LAYER_IDS))):
        raise ValueError("layer orders must be contiguous from zero")

    for index, raw in enumerate(layers):
        layer = parse_layer(raw)
        if layer.pleats < 8:
            raise ValueError(f"layers[{index}].pleats must be at least 8")
        if not 0.0002 <= layer.thickness <= 0.005:
            raise ValueError(f"layers[{index}].thickness is outside cloth range")
        if len(layer.rings) < 2:
            raise ValueError(f"layers[{index}] requires at least two rings")
        if any(a.z <= b.z for a, b in zip(layer.rings, layer.rings[1:])):
            raise ValueError(f"layers[{index}] rings must descend in z")
        if any(ring.ease_y > ring.ease_x for ring in layer.rings):
            raise ValueError(
                f"layers[{index}] front/back ease must not exceed side ease"
            )

    acceptance = data.get("acceptance")
    if not isinstance(acceptance, dict):
        raise ValueError("acceptance must be an object")
    for key in (
        "maximumBodyPenetrationMm",
        "maximumLayerPenetrationMm",
        "maximumStrainPercent",
        "maximumBoneInfluences",
    ):
        _number(acceptance.get(key), f"acceptance.{key}")


def parse_layer(raw: dict[str, Any]) -> LayerSpec:
    rings_raw = raw.get("rings")
    if not isinstance(rings_raw, list):
        raise ValueError(f"{raw.get('objectName', 'layer')}.rings must be a list")
    return LayerSpec(
        object_name=str(raw.get("objectName")),
        order=int(raw.get("order")),
        pleats=int(raw.get("pleats")),
        thickness=_number(raw.get("thickness"), "layer.thickness"),
        rings=tuple(
            _ring(item, f"{raw.get('objectName', 'layer')}.rings[{index}]")
            for index, item in enumerate(rings_raw)
        ),
    )


def layer_specs(data: dict[str, Any]) -> tuple[LayerSpec, ...]:
    validate_contract(data)
    return tuple(parse_layer(raw) for raw in data["layers"])


def resolve_rings(
    layer: LayerSpec,
    body_sections: dict[str, tuple[float, float]],
) -> tuple[tuple[float, float, float], ...]:
    """Resolve body-relative pattern rings to Blender-space z/rx/ry values."""
    result: list[tuple[float, float, float]] = []
    for ring in layer.rings:
        try:
            body_x, body_y = body_sections[ring.anchor]
        except KeyError as exc:
            raise ValueError(f"missing body section {ring.anchor}") from exc
        rx = body_x + ring.ease_x
        ry = body_y + ring.ease_y
        if rx <= body_x or ry <= body_y:
            raise ValueError(f"{layer.object_name} ring does not clear the body")
        result.append((ring.z, rx, ry))
    return tuple(result)


def material_maker_commands(data: dict[str, Any], root: Path) -> tuple[list[str], ...]:
    validate_contract(data)
    stage = data["stages"]["materialMaker"]
    executable = str(stage.get("executable", "material_maker"))
    result = []
    for material in data.get("materials", []):
        source = root / material["source"]
        output = root / material["output"]
        result.append(
            [
                executable,
                "--export-material",
                "--target",
                str(material.get("target", "Blender")),
                "-o",
                str(output),
                str(source),
            ]
        )
    return tuple(result)
