"""Contracts that bind image observations, patterns, stitches, and variants."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def normalize_point(
    point: Sequence[object], bbox: Sequence[object]
) -> tuple[float, float]:
    if len(point) != 2 or len(bbox) != 4:
        raise ValueError("point/bbox dimensions are invalid")
    x, y = _number(point[0], "point x"), _number(point[1], "point y")
    left, top, right, bottom = (_number(value, "bbox") for value in bbox)
    if right <= left or bottom <= top:
        raise ValueError("bbox must have positive area")
    if not (left <= x <= right and top <= y <= bottom):
        raise ValueError("point lies outside source bounding box")
    return ((x - left) / (right - left), (y - top) / (bottom - top))


def denormalize_point(
    point: Sequence[object], bbox: Sequence[object]
) -> tuple[float, float]:
    if len(point) != 2 or len(bbox) != 4:
        raise ValueError("point/bbox dimensions are invalid")
    u, v = _number(point[0], "normalized x"), _number(point[1], "normalized y")
    left, top, right, bottom = (_number(value, "bbox") for value in bbox)
    if right <= left or bottom <= top:
        raise ValueError("bbox must have positive area")
    return left + u * (right - left), top + v * (bottom - top)


def validate_reference_observations(
    observations: Mapping[str, Any],
    *,
    product_id: str,
    source_sha256: str,
    source_size: tuple[int, int],
) -> dict[str, Any]:
    if (
        observations.get("schemaVersion") != 1
        or observations.get("productId") != product_id
    ):
        raise ValueError("reference observations schema or product identity mismatch")
    if observations.get("sourceSha256") != source_sha256:
        raise ValueError("reference observations source hash mismatch")
    if observations.get("sourceSizePx") != [source_size[0], source_size[1]]:
        raise ValueError("reference observations source size mismatch")
    views = observations.get("observations")
    if not isinstance(views, list) or not views:
        raise ValueError("reference observations must be non-empty")

    records: list[dict[str, Any]] = []
    maximum_error = 0.0
    for item in views:
        if not isinstance(item, Mapping) or item.get("status") != "OBSERVED":
            raise ValueError("each observation must be an OBSERVED object")
        if item.get("view") != "front":
            raise ValueError("unobserved views cannot be promoted to OBSERVED")
        bbox = item.get("sourceBoundingBoxPx")
        landmarks = item.get("landmarksPx")
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise ValueError("observation bbox is invalid")
        if not isinstance(landmarks, Mapping) or not landmarks:
            raise ValueError("observation landmarks must be non-empty")
        normalized: dict[str, list[float]] = {}
        for name, point in landmarks.items():
            if not isinstance(name, str) or not name or not isinstance(point, list):
                raise ValueError("landmark entry is invalid")
            uv = normalize_point(point, bbox)
            restored = denormalize_point(uv, bbox)
            maximum_error = max(
                maximum_error,
                abs(restored[0] - float(point[0])),
                abs(restored[1] - float(point[1])),
            )
            normalized[name] = [uv[0], uv[1]]
        records.append(
            {
                "variantId": item.get("variantId"),
                "view": "front",
                "evidenceClass": "OBSERVED",
                "sourceBoundingBoxPx": bbox,
                "normalizedLandmarks": normalized,
                "unknownFields": list(item.get("unknownFields", [])),
            }
        )
    if maximum_error > 1.0:
        raise ValueError(
            f"observation round-trip error exceeds one pixel: {maximum_error}"
        )
    return {"records": records, "roundTripMaxErrorPx": maximum_error}


def validate_pattern_contract(
    pattern: Mapping[str, Any], *, product_id: str
) -> dict[str, dict[str, Any]]:
    if pattern.get("schemaVersion") != 1 or pattern.get("productId") != product_id:
        raise ValueError("pattern contract schema or product identity mismatch")
    if pattern.get("units") != "meter":
        raise ValueError("pattern contract units must be meter")
    raw_pieces = pattern.get("pieces")
    if not isinstance(raw_pieces, list) or not raw_pieces:
        raise ValueError("pattern pieces must be non-empty")

    pieces: dict[str, dict[str, Any]] = {}
    for raw in raw_pieces:
        if not isinstance(raw, Mapping):
            raise ValueError("pattern pieces must be objects")
        piece_id = raw.get("pieceId")
        if not isinstance(piece_id, str) or not piece_id or piece_id in pieces:
            raise ValueError("pattern pieceId must be unique and non-empty")
        boundary = raw.get("boundary")
        if not isinstance(boundary, list) or len(boundary) < 3:
            raise ValueError(f"pattern piece {piece_id} boundary is invalid")
        for index, point in enumerate(boundary):
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError(
                    f"pattern piece {piece_id} boundary point {index} is invalid"
                )
            _number(point[0], "boundary x")
            _number(point[1], "boundary y")
        raw_edges = raw.get("edges")
        if not isinstance(raw_edges, Mapping) or not raw_edges:
            raise ValueError(f"pattern piece {piece_id} edges are required")
        edges: dict[str, tuple[int, ...]] = {}
        for edge_id, indices in raw_edges.items():
            if (
                not isinstance(edge_id, str)
                or not edge_id
                or not isinstance(indices, list)
                or len(indices) < 2
                or not all(
                    isinstance(index, int) and not isinstance(index, bool)
                    for index in indices
                )
            ):
                raise ValueError(f"pattern piece {piece_id} edge {edge_id} is invalid")
            if min(indices) < 0 or max(indices) >= len(boundary):
                raise ValueError(
                    f"pattern piece {piece_id} edge {edge_id} references missing vertex"
                )
            edges[edge_id] = tuple(indices)
        pieces[piece_id] = {
            "boundary": boundary,
            "edges": edges,
            "raw": dict(raw),
        }
    return pieces


def validate_stitch_graph(
    stitches: Mapping[str, Any],
    *,
    product_id: str,
    pieces: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if stitches.get("schemaVersion") != 1 or stitches.get("productId") != product_id:
        raise ValueError("stitch graph schema or product identity mismatch")
    raw_stitches = stitches.get("stitches")
    if not isinstance(raw_stitches, list) or not raw_stitches:
        raise ValueError("stitches must be non-empty")

    seen: set[str] = set()
    resolved: list[dict[str, Any]] = []
    for raw in raw_stitches:
        if not isinstance(raw, Mapping):
            raise ValueError("stitch entries must be objects")
        stitch_id = raw.get("stitchId")
        if not isinstance(stitch_id, str) or not stitch_id or stitch_id in seen:
            raise ValueError("stitchId must be unique and non-empty")
        seen.add(stitch_id)
        orientation = raw.get("orientation")
        if orientation not in {"opposed", "same"}:
            raise ValueError(
                f"stitch {stitch_id} orientation must be opposed or same"
            )
        entry: dict[str, Any] = {
            "stitchId": stitch_id,
            "orientation": orientation,
        }
        for side in ("first", "second"):
            reference = raw.get(side)
            if not isinstance(reference, Mapping):
                raise ValueError(f"stitch {stitch_id} {side} reference is invalid")
            piece_id = reference.get("pieceId")
            edge_id = reference.get("edge")
            if piece_id not in pieces:
                raise ValueError(
                    f"stitch {stitch_id} references missing piece {piece_id!r}"
                )
            if edge_id not in pieces[piece_id]["edges"]:
                raise ValueError(
                    f"stitch {stitch_id} references missing edge {piece_id}.{edge_id}"
                )
            entry[side] = {
                "pieceId": piece_id,
                "edge": edge_id,
                "vertexPath": list(pieces[piece_id]["edges"][edge_id]),
            }
        resolved.append(entry)
    return resolved


def edge_length(piece: Mapping[str, Any], edge_id: str) -> float:
    indices = piece["edges"][edge_id]
    boundary = piece["boundary"]
    total = 0.0
    for first, second in zip(indices, indices[1:]):
        ax, ay = boundary[first]
        bx, by = boundary[second]
        total += math.hypot(float(bx) - float(ax), float(by) - float(ay))
    return total


def ring_dimensions_from_pattern(
    piece: Mapping[str, Any],
    *,
    waist_edge: str,
    hem_edge: str,
    aspect_ratio_y: float,
    width_scale: float = 1.0,
) -> dict[str, float]:
    aspect = _number(aspect_ratio_y, "aspect_ratio_y")
    scale = _number(width_scale, "width_scale")
    if not 0.1 <= aspect <= 1.0 or not 0.5 <= scale <= 2.0:
        raise ValueError("ring pattern mapping parameters are out of bounds")
    top_circumference = edge_length(piece, waist_edge) * scale
    bottom_circumference = edge_length(piece, hem_edge) * scale
    top_rx = top_circumference / (2.0 * math.pi)
    bottom_rx = bottom_circumference / (2.0 * math.pi)
    return {
        "topCircumferenceM": top_circumference,
        "bottomCircumferenceM": bottom_circumference,
        "topRxM": top_rx,
        "topRyM": top_rx * aspect,
        "bottomRxM": bottom_rx,
        "bottomRyM": bottom_rx * aspect,
    }


def variant_invalidation(variant: Mapping[str, Any]) -> dict[str, Any]:
    if variant.get("kind") == "color":
        return {
            "reuseGeometry": True,
            "invalidateStages": [
                "build-blender:materials",
                "render-evidence",
                "visual-review",
                "finalize-candidate",
            ],
            "requiredRechecks": [
                "material-region-binding",
                "render-evidence",
                "visual-review",
            ],
        }
    if variant.get("kind") == "size":
        return {
            "reuseGeometry": False,
            "invalidateStages": [
                "initialize-3d",
                "build-blender",
                "simulate-cloth",
                "skin-and-export",
                "render-evidence",
                "audit-geometry",
                "visual-review",
                "finalize-candidate",
            ],
            "requiredRechecks": [
                "fit",
                "weights",
                "poses",
                "render-evidence",
                "visual-review",
            ],
        }
    raise ValueError(f"unsupported variant kind: {variant.get('kind')!r}")
