"""Curve primitives shared by canonical pattern and OSS exchange adapters."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

Point2 = tuple[float, float]
DEFAULT_CURVE_TOLERANCE_M = 1e-6


def normalize_curvature(value: Mapping[str, Any], label: str = "curve") -> dict[str, Any]:
    """Validate the relative Bezier and SVG-like circle forms used by GarmentCode."""
    curve_type = value.get("type")
    params = value.get("params")
    if curve_type in {"quadratic", "cubic"}:
        control_count = 1 if curve_type == "quadratic" else 2
        if not isinstance(params, list) or len(params) != control_count:
            raise ValueError(
                f"{label} {curve_type} curvature requires {control_count} control point(s)"
            )
        controls: list[list[float]] = []
        for index, point in enumerate(params):
            if (
                not isinstance(point, (list, tuple))
                or len(point) != 2
                or any(
                    isinstance(number, bool)
                    or not isinstance(number, (int, float))
                    or not math.isfinite(number)
                    for number in point
                )
            ):
                raise ValueError(f"{label} control point {index} must be finite 2D")
            controls.append([float(point[0]), float(point[1])])
        return {"type": curve_type, "params": controls}

    if curve_type == "circle":
        if not isinstance(params, (list, tuple)) or len(params) != 3:
            raise ValueError(f"{label} circle curvature requires radius and two flags")
        radius, large_arc, right = params
        if (
            isinstance(radius, bool)
            or not isinstance(radius, (int, float))
            or not math.isfinite(radius)
            or radius <= 0
        ):
            raise ValueError(f"{label} circle radius must be finite and positive")
        flags: list[int] = []
        for name, flag in (("large-arc", large_arc), ("right", right)):
            if isinstance(flag, bool):
                flag = int(flag)
            if not isinstance(flag, int) or flag not in {0, 1}:
                raise ValueError(f"{label} circle {name} flag must be 0 or 1")
            flags.append(flag)
        return {"type": "circle", "params": [float(radius), *flags]}

    raise ValueError(f"{label} has unsupported curvature type {curve_type!r}")


def scale_curvature(value: Mapping[str, Any], scale: float) -> dict[str, Any]:
    """Scale a curve with its coordinates; Bezier coordinates are edge-relative."""
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("curve scale must be finite and positive")
    curve = normalize_curvature(value)
    if curve["type"] == "circle":
        curve["params"][0] *= scale
    return curve


def reverse_curvature(value: Mapping[str, Any]) -> dict[str, Any]:
    """Express the same curve with its edge endpoints reversed."""
    curve = normalize_curvature(value)
    if curve["type"] == "circle":
        radius, large_arc, right = curve["params"]
        curve["params"] = [radius, large_arc, 1 - right]
    else:
        controls = curve["params"]
        curve["params"] = [
            [1.0 - point[0], -point[1]] for point in reversed(controls)
        ]
    return curve


def _relative_control_points(
    start: Point2, end: Point2, curve: Mapping[str, Any]
) -> list[Point2]:
    normalized = normalize_curvature(curve)
    if normalized["type"] == "circle":
        raise ValueError("circle arcs do not have Bezier control points")
    dx, dy = end[0] - start[0], end[1] - start[1]
    return [
        (
            start[0] + point[0] * dx - point[1] * dy,
            start[1] + point[0] * dy + point[1] * dx,
        )
        for point in normalized["params"]
    ]


def _circle_arc_data(
    start: Point2, end: Point2, curve: Mapping[str, Any]
) -> tuple[Point2, float, float, float]:
    normalized = normalize_curvature(curve)
    if normalized["type"] != "circle":
        raise ValueError("circle arc data requires a circle curve")
    radius, large_arc, right = normalized["params"]
    dx, dy = end[0] - start[0], end[1] - start[1]
    chord = math.hypot(dx, dy)
    if chord <= 0:
        raise ValueError("curved pattern edge must have non-zero chord length")
    if radius + 1e-12 < chord / 2:
        raise ValueError("circle radius is shorter than half of its chord")

    half_chord = chord / 2
    center_offset = math.sqrt(max(0.0, radius * radius - half_chord * half_chord))
    left_normal = (-dy / chord, dx / chord)
    curve_side = -1.0 if right else 1.0
    center_side = curve_side if large_arc else -curve_side
    midpoint = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
    center = (
        midpoint[0] + left_normal[0] * center_side * center_offset,
        midpoint[1] + left_normal[1] * center_side * center_offset,
    )
    start_angle = math.atan2(start[1] - center[1], start[0] - center[0])
    end_angle = math.atan2(end[1] - center[1], end[0] - center[0])
    counterclockwise = (end_angle - start_angle) % (2 * math.pi)
    candidates = (counterclockwise, counterclockwise - 2 * math.pi)
    for sweep in candidates:
        is_large = abs(sweep) > math.pi + 1e-12
        if is_large != bool(large_arc):
            continue
        mid_angle = start_angle + sweep / 2
        arc_midpoint = (
            center[0] + radius * math.cos(mid_angle),
            center[1] + radius * math.sin(mid_angle),
        )
        side_cross = dx * (arc_midpoint[1] - start[1]) - dy * (
            arc_midpoint[0] - start[0]
        )
        if abs(side_cross) <= 1e-12 or (1.0 if side_cross > 0 else -1.0) == curve_side:
            return center, radius, start_angle, sweep
    raise ValueError("circle flags do not identify a valid arc through the declared side")


def curve_point(
    start: Point2, end: Point2, curve: Mapping[str, Any], t: float
) -> Point2:
    """Evaluate a canonical curve at a parameter in the closed unit interval."""
    if not math.isfinite(t) or not 0 <= t <= 1:
        raise ValueError("curve parameter must be finite and between zero and one")
    normalized = normalize_curvature(curve)
    if normalized["type"] == "circle":
        center, radius, start_angle, sweep = _circle_arc_data(start, end, normalized)
        angle = start_angle + t * sweep
        point = (center[0] + radius * math.cos(angle), center[1] + radius * math.sin(angle))
        if t == 0:
            return start
        if t == 1:
            return end
        return point

    points: list[Point2] = [start]
    points.extend(_relative_control_points(start, end, normalized))
    points.append(end)
    work = list(points)
    while len(work) > 1:
        work = [
            (
                (1.0 - t) * first[0] + t * second[0],
                (1.0 - t) * first[1] + t * second[1],
            )
            for first, second in zip(work, work[1:])
        ]
    return work[0]


def _point_segment_distance(point: Point2, start: Point2, end: Point2) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    denominator = dx * dx + dy * dy
    if denominator == 0:
        return math.dist(point, start)
    position = max(
        0.0,
        min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / denominator),
    )
    projection = (start[0] + position * dx, start[1] + position * dy)
    return math.dist(point, projection)


def _split_bezier(points: Sequence[Point2]) -> tuple[list[Point2], list[Point2]]:
    levels = [list(points)]
    while len(levels[-1]) > 1:
        previous = levels[-1]
        levels.append(
            [
                ((first[0] + second[0]) / 2, (first[1] + second[1]) / 2)
                for first, second in zip(previous, previous[1:])
            ]
        )
    left = [level[0] for level in levels]
    right = [level[-1] for level in reversed(levels)]
    return left, right


def flatten_curve(
    start: Point2,
    end: Point2,
    curve: Mapping[str, Any],
    *,
    tolerance: float = DEFAULT_CURVE_TOLERANCE_M,
) -> tuple[tuple[Point2, ...], float]:
    """Flatten a curve and return points plus its conservative deviation bound."""
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("curve flattening tolerance must be finite and positive")
    normalized = normalize_curvature(curve)
    if normalized["type"] == "circle":
        center, radius, start_angle, sweep = _circle_arc_data(start, end, normalized)
        cosine = max(-1.0, min(1.0, 1.0 - tolerance / radius))
        max_segment_angle = 2.0 * math.acos(cosine)
        if max_segment_angle <= 0:
            raise ValueError("circle tolerance is too small for stable subdivision")
        count = max(1, math.ceil(abs(sweep) / max_segment_angle))
        points = [
            (
                center[0] + radius * math.cos(start_angle + sweep * index / count),
                center[1] + radius * math.sin(start_angle + sweep * index / count),
            )
            for index in range(count + 1)
        ]
        points[0], points[-1] = start, end
        deviation = radius * (1.0 - math.cos(abs(sweep) / (2.0 * count)))
        return tuple(points), deviation

    initial = [start, *_relative_control_points(start, end, normalized), end]
    output: list[Point2] = [start]
    max_deviation = 0.0
    stack: list[tuple[list[Point2], int]] = [(initial, 0)]
    while stack:
        control_points, depth = stack.pop()
        deviation = max(
            (_point_segment_distance(point, control_points[0], control_points[-1])
             for point in control_points[1:-1]),
            default=0.0,
        )
        if deviation <= tolerance:
            output.append(control_points[-1])
            max_deviation = max(max_deviation, deviation)
            continue
        if depth >= 24:
            raise ValueError("Bezier curve could not meet the requested flatten tolerance")
        left, right = _split_bezier(control_points)
        stack.append((right, depth + 1))
        stack.append((left, depth + 1))
    return tuple(output), max_deviation


def curve_length(
    start: Point2,
    end: Point2,
    curve: Mapping[str, Any],
    *,
    tolerance: float = DEFAULT_CURVE_TOLERANCE_M,
) -> float:
    """Measure a curve using exact arc length for circles and bounded flattening otherwise."""
    normalized = normalize_curvature(curve)
    if normalized["type"] == "circle":
        _, radius, _, sweep = _circle_arc_data(start, end, normalized)
        return radius * abs(sweep)
    points, _ = flatten_curve(start, end, normalized, tolerance=tolerance)
    return sum(math.dist(first, second) for first, second in zip(points, points[1:]))


def sample_pattern_boundary(
    boundary: Sequence[Point2],
    edges: Sequence[Any],
    *,
    tolerance: float = DEFAULT_CURVE_TOLERANCE_M,
) -> tuple[tuple[Point2, ...], float]:
    """Create a sampled polygon while retaining a bound for every curved segment."""
    if len(boundary) < 3:
        raise ValueError("pattern boundary requires at least three vertices")
    by_pair: dict[tuple[int, int], Mapping[str, Any]] = {}
    for edge in edges:
        curve = getattr(edge, "curvature", None)
        if curve is None:
            continue
        pair = (edge.start_vertex, edge.end_vertex)
        if pair in by_pair:
            raise ValueError("multiple curve records reference the same directed edge")
        by_pair[pair] = curve

    points: list[Point2] = []
    max_deviation = 0.0
    for start_index, start in enumerate(boundary):
        end_index = (start_index + 1) % len(boundary)
        end = boundary[end_index]
        curve = by_pair.get((start_index, end_index))
        reversed_curve = False
        if curve is None:
            curve = by_pair.get((end_index, start_index))
            reversed_curve = curve is not None
        if curve is None:
            segment_points = (start, end)
        else:
            oriented_curve = reverse_curvature(curve) if reversed_curve else curve
            segment_points, deviation = flatten_curve(
                start,
                end,
                oriented_curve,
                tolerance=tolerance,
            )
            max_deviation = max(max_deviation, deviation)
        if not points:
            points.append(start)
        points.extend(segment_points[1:])
    if points and math.dist(points[0], points[-1]) <= 1e-12:
        points.pop()
    return tuple(points), max_deviation
