"""Auditable 2D placement checks for overlays attached to a host panel surface."""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

_EPSILON = 1e-10


def _cross(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> bool:
    return (
        abs(_cross(start, end, point)) <= _EPSILON
        and min(start[0], end[0]) - _EPSILON <= point[0] <= max(start[0], end[0]) + _EPSILON
        and min(start[1], end[1]) - _EPSILON <= point[1] <= max(start[1], end[1]) + _EPSILON
    )


def _segments_intersect(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    ab_c = _cross(a, b, c)
    ab_d = _cross(a, b, d)
    cd_a = _cross(c, d, a)
    cd_b = _cross(c, d, b)
    if (
        ((ab_c > _EPSILON and ab_d < -_EPSILON) or (ab_c < -_EPSILON and ab_d > _EPSILON))
        and ((cd_a > _EPSILON and cd_b < -_EPSILON) or (cd_a < -_EPSILON and cd_b > _EPSILON))
    ):
        return True
    return (
        (abs(ab_c) <= _EPSILON and _on_segment(c, a, b))
        or (abs(ab_d) <= _EPSILON and _on_segment(d, a, b))
        or (abs(cd_a) <= _EPSILON and _on_segment(a, c, d))
        or (abs(cd_b) <= _EPSILON and _on_segment(b, c, d))
    )


def _point_location(
    point: tuple[float, float], polygon: list[tuple[float, float]]
) -> str:
    inside = False
    for index, first in enumerate(polygon):
        second = polygon[(index + 1) % len(polygon)]
        if _on_segment(point, first, second):
            return "boundary"
        if (first[1] > point[1]) != (second[1] > point[1]):
            crossing_x = (second[0] - first[0]) * (point[1] - first[1]) / (
                second[1] - first[1]
            ) + first[0]
            if point[0] < crossing_x:
                inside = not inside
    return "inside" if inside else "outside"


def _point_segment_distance(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= _EPSILON:
        return math.dist(point, start)
    fraction = max(
        0.0,
        min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared),
    )
    projection = (start[0] + fraction * dx, start[1] + fraction * dy)
    return math.dist(point, projection)


def _segment_distance(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> float:
    if _segments_intersect(a, b, c, d):
        return 0.0
    return min(
        _point_segment_distance(a, c, d),
        _point_segment_distance(b, c, d),
        _point_segment_distance(c, a, b),
        _point_segment_distance(d, a, b),
    )


def _edges(polygon: list[tuple[float, float]]):
    return [
        (point, polygon[(index + 1) % len(polygon)])
        for index, point in enumerate(polygon)
    ]


def _bounds(polygon: list[tuple[float, float]]) -> list[float]:
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return [min(xs), min(ys), max(xs), max(ys)]


def _pattern_piece_map(pattern: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    units = pattern.get("units")
    if units not in {"meter", "millimeter"}:
        raise ValueError("surface attachment audit requires meter or millimeter pattern units")
    unit_scale = 1.0 if units == "meter" else 0.001
    pieces = pattern.get("pieces")
    if not isinstance(pieces, list):
        raise ValueError("surface attachment audit requires pattern pieces")
    result: dict[str, Mapping[str, Any]] = {}
    for piece in pieces:
        if not isinstance(piece, Mapping):
            raise ValueError("surface attachment pattern pieces must be objects")
        piece_id = piece.get("pieceId", piece.get("id"))
        if not isinstance(piece_id, str) or piece_id in result:
            raise ValueError(f"invalid or duplicate pattern piece ID: {piece_id!r}")
        result[piece_id] = piece
    return result


def _boundary(piece: Mapping[str, Any], unit_scale: float) -> list[tuple[float, float]]:
    raw = piece.get("boundary")
    if not isinstance(raw, list) or len(raw) < 3:
        raise ValueError("surface attachment pieces require 2D boundaries")
    points: list[tuple[float, float]] = []
    for point in raw:
        if (
            not isinstance(point, list)
            or len(point) != 2
            or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in point)
        ):
            raise ValueError("surface attachment boundaries require finite 2D coordinates")
        points.append((float(point[0]) * unit_scale, float(point[1]) * unit_scale))
    return points


def _edge_map(piece: Mapping[str, Any], piece_id: str) -> dict[str, Mapping[str, Any]]:
    raw_edges = piece.get("edges")
    if not isinstance(raw_edges, list):
        raise ValueError(f"pattern piece {piece_id!r} requires explicit edges")
    result: dict[str, Mapping[str, Any]] = {}
    for edge in raw_edges:
        if not isinstance(edge, Mapping) or not isinstance(edge.get("edgeId"), str):
            raise ValueError(f"pattern piece {piece_id!r} contains an invalid edge")
        edge_id = str(edge["edgeId"])
        if edge_id in result:
            raise ValueError(f"pattern piece {piece_id!r} has duplicate edge {edge_id!r}")
        result[edge_id] = edge
    return result


def _placed_boundary(
    boundary: list[tuple[float, float]], transform: Mapping[str, Any], overlay_id: str
) -> list[tuple[float, float]]:
    anchor = transform.get("anchorLocalM")
    target = transform.get("targetPointOnHostM")
    rotation = transform.get("rotationDegrees")
    mirror_x = transform.get("mirrorX")
    if (
        not isinstance(anchor, list)
        or len(anchor) != 2
        or not isinstance(target, list)
        or len(target) != 2
        or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in [*anchor, *target])
        or not isinstance(rotation, (int, float))
        or not math.isfinite(rotation)
        or not isinstance(mirror_x, bool)
    ):
        raise ValueError(f"overlay {overlay_id!r} has an invalid 2D transform")
    angle = math.radians(float(rotation))
    cosine = math.cos(angle)
    sine = math.sin(angle)
    anchor_x, anchor_y = float(anchor[0]), float(anchor[1])
    target_x, target_y = float(target[0]), float(target[1])
    offset_x = target_x - (cosine * anchor_x - sine * anchor_y)
    offset_y = target_y - (sine * anchor_x + cosine * anchor_y)
    return [
        (
            cosine * (anchor_x + (-1.0 if mirror_x else 1.0) * (x - anchor_x))
            - sine * y
            + offset_x,
            sine * (anchor_x + (-1.0 if mirror_x else 1.0) * (x - anchor_x))
            + cosine * y
            + offset_y,
        )
        for x, y in boundary
    ]


def audit_surface_attachment_graph(
    graph: Mapping[str, Any],
    pattern: Mapping[str, Any],
    stitch_graph: Mapping[str, Any],
    *,
    expected_product_id: str,
) -> dict[str, Any]:
    """Check planned overlays in the pattern plane; this does not assert sewing or 3D attachment."""
    if graph.get("productId") != expected_product_id:
        raise ValueError("surface attachment graph product identity mismatch")
    if graph.get("units") != pattern.get("units"):
        raise ValueError("surface attachment graph and pattern units must match")
    unit_scale = 1.0 if pattern["units"] == "meter" else 0.001
    pieces = _pattern_piece_map(pattern)
    raw_overlays = graph.get("overlays")
    if not isinstance(raw_overlays, list) or not raw_overlays:
        raise ValueError("surface attachment graph requires at least one overlay")

    structural_refs: set[tuple[str, str]] = set()
    stitches = stitch_graph.get("stitches")
    if not isinstance(stitches, list):
        raise ValueError("surface attachment audit requires the structural stitch graph")
    for stitch in stitches:
        if not isinstance(stitch, Mapping):
            raise ValueError("structural stitches must be objects")
        for side in ("first", "second"):
            endpoint = stitch.get(side)
            if isinstance(endpoint, Mapping):
                structural_refs.add((str(endpoint.get("pieceId")), str(endpoint.get("edgeId"))))

    overlay_ids: set[str] = set()
    placed: list[dict[str, Any]] = []
    for raw in raw_overlays:
        if not isinstance(raw, Mapping):
            raise ValueError("surface attachment overlays must be objects")
        overlay_id = raw.get("overlayId")
        host_id = raw.get("hostPieceId")
        overlay_piece_id = raw.get("overlayPieceId")
        if not all(isinstance(value, str) and value for value in (overlay_id, host_id, overlay_piece_id)):
            raise ValueError("surface attachment overlay IDs are required")
        if overlay_id in overlay_ids:
            raise ValueError(f"duplicate surface attachment overlay ID: {overlay_id}")
        overlay_ids.add(overlay_id)
        if host_id not in pieces or overlay_piece_id not in pieces:
            raise ValueError(f"overlay {overlay_id!r} references an unknown pattern piece")
        if host_id == overlay_piece_id:
            raise ValueError(f"overlay {overlay_id!r} cannot attach to itself")

        host = _boundary(pieces[host_id], unit_scale)
        source_overlay = pieces[overlay_piece_id]
        local = _boundary(source_overlay, unit_scale)
        edges = _edge_map(source_overlay, overlay_piece_id)
        opening_id = raw.get("openingEdgeId")
        attachment_ids = raw.get("attachmentEdgeIds")
        if opening_id is None:
            expected_attachment_ids = set(edges)
        else:
            if not isinstance(opening_id, str) or opening_id not in edges:
                raise ValueError(f"overlay {overlay_id!r} references an unknown opening edge")
            if edges[opening_id].get("role") != "open":
                raise ValueError(f"overlay {overlay_id!r} opening edge must have role open")
            expected_attachment_ids = set(edges) - {opening_id}
        if not isinstance(attachment_ids, list) or set(attachment_ids) != expected_attachment_ids:
            raise ValueError(f"overlay {overlay_id!r} attachment path must cover every attachable edge")
        if any(edges[edge_id].get("role") != "attachment" for edge_id in attachment_ids):
            raise ValueError(f"overlay {overlay_id!r} attachment path includes a non-attachment edge")
        if any((overlay_piece_id, edge_id) in structural_refs for edge_id in edges):
            raise ValueError(f"overlay {overlay_id!r} is incorrectly mixed into the structural stitch graph")

        transform = raw.get("transform")
        if not isinstance(transform, Mapping):
            raise ValueError(f"overlay {overlay_id!r} requires a 2D transform")
        polygon = _placed_boundary(local, transform, overlay_id)
        if any(_point_location(point, host) != "inside" for point in polygon):
            raise ValueError(f"overlay {overlay_id!r} boundary is not strictly inside host {host_id!r}")
        host_edges = _edges(host)
        overlay_edges = _edges(polygon)
        intersections = sum(
            _segments_intersect(first, second, third, fourth)
            for first, second in overlay_edges
            for third, fourth in host_edges
        )
        if intersections:
            raise ValueError(f"overlay {overlay_id!r} crosses or touches the host boundary")
        clearance = min(
            _segment_distance(first, second, third, fourth)
            for first, second in overlay_edges
            for third, fourth in host_edges
        )
        placed.append(
            {
                "overlayId": overlay_id,
                "hostPieceId": host_id,
                "overlayPieceId": overlay_piece_id,
                "mirrorGroupId": raw.get("mirrorGroupId"),
                "side": raw.get("side"),
                "placedBoundaryM": [[x, y] for x, y in polygon],
                "boundsM": _bounds(polygon),
                "hostBoundaryClearanceM": clearance,
                "openingEdgeId": opening_id,
                "plannedAttachmentEdgeIds": attachment_ids,
                "attachmentStatus": "PLANNED_NOT_SEWN",
                "hostContainment": "PASS_2D_ONLY",
            }
        )

    for index, first in enumerate(placed):
        first_polygon = [tuple(point) for point in first["placedBoundaryM"]]
        for second in placed[index + 1 :]:
            if first["hostPieceId"] != second["hostPieceId"]:
                continue
            second_polygon = [tuple(point) for point in second["placedBoundaryM"]]
            edge_collision = any(
                _segments_intersect(a, b, c, d)
                for a, b in _edges(first_polygon)
                for c, d in _edges(second_polygon)
            )
            if edge_collision or any(
                _point_location(point, first_polygon) != "outside"
                for point in second_polygon
            ) or any(
                _point_location(point, second_polygon) != "outside"
                for point in first_polygon
            ):
                raise ValueError(
                    f"surface overlays {first['overlayId']!r} and {second['overlayId']!r} overlap"
                )

    mirror_groups: dict[str, list[dict[str, Any]]] = {}
    for overlay in placed:
        group_id = overlay.get("mirrorGroupId")
        if not isinstance(group_id, str) or not group_id:
            raise ValueError(f"overlay {overlay['overlayId']!r} requires a mirrorGroupId")
        mirror_groups.setdefault(group_id, []).append(overlay)
    mirror_records: list[dict[str, Any]] = []
    for group_id, group in sorted(mirror_groups.items()):
        if len(group) != 2 or {item["side"] for item in group} != {"left", "right"}:
            raise ValueError(f"mirror group {group_id!r} must contain one left and one right overlay")
        left = next(item for item in group if item["side"] == "left")
        right = next(item for item in group if item["side"] == "right")
        reflected = sorted((round(-point[0], 9), round(point[1], 9)) for point in left["placedBoundaryM"])
        right_points = sorted((round(point[0], 9), round(point[1], 9)) for point in right["placedBoundaryM"])
        if reflected != right_points:
            raise ValueError(f"mirror group {group_id!r} is not geometrically symmetric")
        mirror_records.append(
            {
                "mirrorGroupId": group_id,
                "leftOverlayId": left["overlayId"],
                "rightOverlayId": right["overlayId"],
                "status": "PASS_2D_REFLECTION_ONLY",
            }
        )

    return {
        "schemaVersion": 1,
        "productId": expected_product_id,
        "status": "PASS_2D_PLACEMENT_ONLY",
        "evaluationBoundary": "Flat-pattern placement, polygon containment, overlay overlap, opening/attachment edge roles, and reflection symmetry only; no sewn surface attachment, avatar fit, fabric simulation, 3D, or visual gate is implied.",
        "overlayCount": len(placed),
        "structuralStitchGraphPocketReferences": 0,
        "overlays": placed,
        "mirrorPairs": mirror_records,
        "threeDGenerated": False,
        "physicalAttachmentEvaluated": False,
    }


def render_surface_attachment_preview(
    pattern: Mapping[str, Any],
    audit: Mapping[str, Any],
    references: Mapping[str, Path],
    output_path: Path,
) -> dict[str, Any]:
    """Render audited flat overlay polygons alongside the front/back references."""
    if pattern.get("units") not in {"meter", "millimeter"}:
        raise ValueError("surface attachment preview requires meter or millimeter pattern units")
    overlays = audit.get("overlays")
    if not isinstance(overlays, list) or not overlays:
        raise ValueError("surface attachment preview requires audited overlay polygons")
    if set(references) != {"front", "back"}:
        raise ValueError("surface attachment preview requires front and back reference images")
    for view, path in references.items():
        if not path.is_file():
            raise FileNotFoundError(f"surface attachment {view} reference is missing: {path}")

    pieces = _pattern_piece_map(pattern)
    unit_scale = 1.0 if pattern["units"] == "meter" else 0.001
    canvas = Image.new("RGB", (1840, 1080), "#f5f2eb")
    draw = ImageDraw.Draw(canvas)

    def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        for name in ("DejaVuSans.ttf", "arial.ttf", "C:/Windows/Fonts/arial.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    title_font = font(29)
    label_font = font(21)
    small_font = font(16)
    draw.text((30, 24), "GARMENTCODE / OPENSEW · 2D HOST-PANEL REVIEW", fill="#202b39", font=title_font)
    draw.text(
        (30, 68),
        "Reference images beside the current surface-attachment graph projected onto each host shell.",
        fill="#495665",
        font=small_font,
    )

    for view, top in (("front", 190), ("back", 545)):
        box = (30, top, 500, top + 318)
        draw.text((box[0], box[1] - 30), f"REFERENCE · {view.upper()}", fill="#202b39", font=label_font)
        with Image.open(references[view]) as source:
            image = source.convert("RGB")
            image.thumbnail((box[2] - box[0] - 12, box[3] - box[1] - 12), Image.Resampling.LANCZOS)
            x = box[0] + (box[2] - box[0] - image.width) // 2
            y = box[1] + (box[3] - box[1] - image.height) // 2
            canvas.paste(image, (x, y))
        draw.rectangle(box, outline="#9ca3ad", width=2)

    overlays_by_host: dict[str, list[Mapping[str, Any]]] = {}
    for item in overlays:
        if not isinstance(item, Mapping) or not isinstance(item.get("hostPieceId"), str):
            raise ValueError("surface attachment preview contains an invalid audited overlay")
        overlays_by_host.setdefault(str(item["hostPieceId"]), []).append(item)

    host_ids = sorted(overlays_by_host)
    if not host_ids:
        raise ValueError("surface attachment preview requires at least one host panel")
    panel_specs = []
    columns = min(2, len(host_ids))
    rows = math.ceil(len(host_ids) / columns)
    panel_left = 560
    panel_right = 1810
    panel_top = 190
    panel_bottom = 870
    column_gap = 24
    row_gap = 38
    panel_width = (panel_right - panel_left - column_gap * (columns - 1)) / columns
    panel_height = (panel_bottom - panel_top - row_gap * (rows - 1)) / rows
    for index, piece_id in enumerate(host_ids):
        column = index % columns
        row = index // columns
        left = round(panel_left + column * (panel_width + column_gap))
        top = round(panel_top + row * (panel_height + row_gap))
        right = round(left + panel_width)
        bottom = round(top + panel_height)
        panel_specs.append((f"HOST PANEL · {piece_id}", piece_id, (left, top, right, bottom)))

    for label, piece_id, box in panel_specs:
        if piece_id not in pieces:
            raise ValueError(f"surface attachment preview is missing host panel {piece_id!r}")
        boundary = _boundary(pieces[piece_id], unit_scale)
        min_x = min(point[0] for point in boundary)
        max_x = max(point[0] for point in boundary)
        min_y = min(point[1] for point in boundary)
        max_y = max(point[1] for point in boundary)
        span_x = max_x - min_x
        span_y = max_y - min_y
        if span_x <= _EPSILON or span_y <= _EPSILON:
            raise ValueError(f"surface attachment host panel {piece_id!r} has zero area bounds")
        left, top, right, bottom = box
        scale = min((right - left - 22) / span_x, (bottom - top - 42) / span_y)
        panel_width = span_x * scale
        panel_height = span_y * scale
        x_offset = left + ((right - left) - panel_width) / 2 - min_x * scale
        y_offset = top + 20 + ((bottom - top - 42) - panel_height) / 2 + max_y * scale

        def project(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
            return [(x_offset + x * scale, y_offset - y * scale) for x, y in points]

        draw.text((left, top - 30), label, fill="#202b39", font=label_font)
        draw.polygon(project(boundary), fill="#52657a", outline="#1e2c3b", width=3)
        for overlay in overlays_by_host.get(piece_id, []):
            raw_polygon = overlay.get("placedBoundaryM")
            if not isinstance(raw_polygon, list) or len(raw_polygon) < 3:
                raise ValueError("surface attachment preview requires an audited polygon boundary")
            polygon: list[tuple[float, float]] = []
            for point in raw_polygon:
                if (
                    not isinstance(point, list)
                    or len(point) != 2
                    or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in point)
                ):
                    raise ValueError("surface attachment preview polygon coordinates must be finite pairs")
                polygon.append((float(point[0]), float(point[1])))
            draw.polygon(project(polygon), fill="#e7aa47", outline="#fff0c2", width=2)

    draw.rectangle((560, 920, 585, 940), fill="#52657a", outline="#1e2c3b", width=2)
    draw.text((596, 916), "HOST PANEL", fill="#52657a", font=small_font)
    draw.rectangle((740, 920, 765, 940), fill="#e7aa47", outline="#fff0c2", width=2)
    draw.text(
        (776, 916),
        f"{len(overlays)} PROVISIONAL OVERLAYS · 2D CONTAINMENT ONLY",
        fill="#8a5a12",
        font=small_font,
    )
    draw.text(
        (30, 1000),
        "2D placement only: these patches are not interlaced linework, stitches, sewn surface attachment, fit, or a 3D garment.",
        fill="#7a3d20",
        font=small_font,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="PNG", optimize=True)
    return {
        "status": "RENDERED_2D_ONLY",
        "overlayCount": len(overlays),
        "hostPanelCount": len(panel_specs),
        "referenceViews": sorted(references),
        "physicalAttachmentEvaluated": False,
        "visualAppearanceGateChanged": False,
    }
