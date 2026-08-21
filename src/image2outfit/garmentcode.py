"""Dependency-free Stage 04 interoperability with GarmentCode/PyGarment JSON.

GarmentCode itself is intentionally not a production dependency of image2outfit.
The external runtime remains isolated; this module only owns deterministic exchange.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .pattern_stage import PatternHypothesis


@dataclass(frozen=True, slots=True)
class ExternalRuntimeDescriptor:
    runtime_id: str
    upstream_repository: str
    upstream_revision: str
    execution_mode: str
    upstream_python: str


GARMENTCODE_RUNTIME = ExternalRuntimeDescriptor(
    runtime_id="garmentcode-pygarment",
    upstream_repository="https://github.com/maria-korosteleva/GarmentCode",
    upstream_revision="d449629979028123a5c4dc9e732a2ec19b7fce31",
    execution_mode="external-isolated",
    upstream_python="3.9",
)


def _panel_edges(vertex_count: int) -> list[dict[str, list[int]]]:
    return [
        {"endpoints": [index, (index + 1) % vertex_count]}
        for index in range(vertex_count)
    ]


def pattern_hypothesis_to_garmentcode(
    hypothesis: PatternHypothesis,
) -> dict[str, Any]:
    """Convert the canonical Stage 04 hypothesis to BasicPattern-compatible JSON.

    image2outfit stores pattern coordinates in metres. GarmentCode's current basic
    pattern representation uses centimetres when ``units_in_meter`` is 100.
    Stage 06 placement is deliberately not exported here, so panel translations and
    rotations remain zero.
    """

    garment = hypothesis.construction.garment
    panels: dict[str, dict[str, Any]] = {}
    edge_indices: dict[tuple[str, int, int], int] = {}
    named_edge_indices: dict[str, dict[str, int]] = {}

    for piece in sorted(garment.pattern_pieces, key=lambda item: item.piece_id):
        vertex_count = len(piece.boundary)
        panels[piece.piece_id] = {
            "translation": [0.0, 0.0, 0.0],
            "rotation": [0.0, 0.0, 0.0],
            "vertices": [[x * 100.0, y * 100.0] for x, y in piece.boundary],
            "edges": _panel_edges(vertex_count),
        }
        for index in range(vertex_count):
            start = index
            end = (index + 1) % vertex_count
            edge_indices[(piece.piece_id, start, end)] = index
            edge_indices[(piece.piece_id, end, start)] = index

        piece_named_edges: dict[str, int] = {}
        for edge in piece.edges:
            try:
                edge_index = edge_indices[
                    (piece.piece_id, edge.start_vertex, edge.end_vertex)
                ]
            except KeyError as exc:
                raise ValueError(
                    f"named edge {edge.edge_id!r} is not a boundary-loop edge"
                ) from exc
            piece_named_edges[edge.edge_id] = edge_index
        named_edge_indices[piece.piece_id] = piece_named_edges

    stitches: list[list[dict[str, str | int]]] = []
    for stitch in sorted(garment.stitches, key=lambda item: item.stitch_id):
        pair: list[dict[str, str | int]] = []
        for stitch_edge in (stitch.first, stitch.second):
            try:
                edge_index = edge_indices[
                    (
                        stitch_edge.piece_id,
                        stitch_edge.start_vertex,
                        stitch_edge.end_vertex,
                    )
                ]
            except KeyError as exc:
                raise ValueError(
                    f"stitch {stitch.stitch_id!r} does not reference a boundary-loop edge"
                ) from exc
            pair.append({"panel": stitch_edge.piece_id, "edge": edge_index})
        stitches.append(pair)

    return {
        "pattern": {
            "panels": panels,
            "stitches": stitches,
            "panel_order": sorted(panels),
        },
        "parameters": {
            "image2outfit": {
                "product_id": garment.product_id,
                "hypothesis_id": hypothesis.hypothesis_id,
                "decomposition_hypothesis_id": hypothesis.decomposition_hypothesis_id,
                "source_reference": garment.source_reference,
                "named_edge_indices": named_edge_indices,
            }
        },
        "parameter_order": [],
        "properties": {
            "curvature_coords": "relative",
            "normalize_panel_translation": False,
            "normalized_edge_loops": True,
            "units_in_meter": 100,
        },
    }


def garmentcode_json(hypothesis: PatternHypothesis) -> str:
    """Serialize a Stage 04 exchange document deterministically."""

    return json.dumps(
        pattern_hypothesis_to_garmentcode(hypothesis),
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
