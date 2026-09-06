"""Deterministic projection of canonical 2D pattern pieces into build coordinates."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any


def _finite_number(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _fingerprint(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def project_pattern_piece(
    piece: Mapping[str, Any],
    *,
    x_scale: float,
    z_scale: float,
    z_offset: float,
    width_scale: float = 1.0,
) -> dict[str, Any]:
    """Project a 2D pattern boundary to deterministic X/Z build coordinates.

    The body-surface Y coordinate is intentionally left to the Blender adapter.
    This keeps pattern geometry testable without Blender while preserving an
    explicit vertex mapping from pattern edges to generated mesh vertices.
    """

    x_scale = _finite_number(x_scale, label="x_scale")
    z_scale = _finite_number(z_scale, label="z_scale")
    z_offset = _finite_number(z_offset, label="z_offset")
    width_scale = _finite_number(width_scale, label="width_scale")
    if x_scale <= 0 or z_scale <= 0 or width_scale <= 0:
        raise ValueError("projection scales must be positive")

    piece_id = piece.get("pieceId", piece.get("id"))
    if not isinstance(piece_id, str) or not piece_id:
        raise ValueError("pattern pieceId is required")
    boundary = piece.get("boundary")
    if not isinstance(boundary, list) or len(boundary) < 3:
        raise ValueError(f"pattern piece {piece_id!r} requires a boundary")

    points_xz: list[list[float]] = []
    for index, point in enumerate(boundary):
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError(f"pattern boundary point {index} is invalid")
        x = _finite_number(point[0], label=f"boundary[{index}].x")
        y = _finite_number(point[1], label=f"boundary[{index}].y")
        points_xz.append(
            [
                x * x_scale * width_scale,
                z_offset + y * z_scale,
            ]
        )

    raw_edges = piece.get("edges")
    if not isinstance(raw_edges, list) or not raw_edges:
        raise ValueError(f"pattern piece {piece_id!r} requires explicit edges")
    edge_vertex_map: dict[str, list[int]] = {}
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, Mapping):
            raise ValueError("pattern edges must be objects")
        edge_id = raw_edge.get("edgeId")
        start = raw_edge.get("startVertex")
        end = raw_edge.get("endVertex")
        if not isinstance(edge_id, str) or not edge_id:
            raise ValueError("pattern edgeId is required")
        if edge_id in edge_vertex_map:
            raise ValueError(f"duplicate pattern edgeId: {edge_id}")
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or start == end
            or not 0 <= start < len(points_xz)
            or not 0 <= end < len(points_xz)
        ):
            raise ValueError(f"pattern edge {edge_id!r} has invalid vertices")
        edge_vertex_map[edge_id] = [start, end]

    x_values = [point[0] for point in points_xz]
    z_values = [point[1] for point in points_xz]
    projection: dict[str, Any] = {
        "schemaVersion": 1,
        "pieceId": piece_id,
        "pointsXZ": points_xz,
        "edgeVertexMap": edge_vertex_map,
        "transform": {
            "xScale": x_scale,
            "zScale": z_scale,
            "zOffset": z_offset,
            "widthScale": width_scale,
        },
        "bounds": {
            "minX": min(x_values),
            "maxX": max(x_values),
            "minZ": min(z_values),
            "maxZ": max(z_values),
            "width": max(x_values) - min(x_values),
            "height": max(z_values) - min(z_values),
        },
    }
    projection["fingerprint"] = _fingerprint(projection)
    return projection
