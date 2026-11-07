#!/usr/bin/env python3
"""Create an endpoint-aware, 2D-only OpenSew panel mesh comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import bpy
import bmesh
from mathutils import Vector


def parse_args() -> argparse.Namespace:
    tail = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--pattern", required=True, type=Path)
    parser.add_argument("--stitches", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--opensew-root", required=True, type=Path)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--expected-blender-version", required=True)
    parser.add_argument("--target-grid-meters", required=True, type=float)
    parser.add_argument("--endpoint-tolerance-mm", required=True, type=float)
    return parser.parse_args(tail)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def distance_mm(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1]) * 1000.0


def point_segment_distance(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-24:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    parameter = max(
        0.0,
        min(
            1.0,
            ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy)
            / length_sq,
        ),
    )
    nearest = (start[0] + parameter * dx, start[1] + parameter * dy)
    return math.hypot(point[0] - nearest[0], point[1] - nearest[1])


def polyline_length(points: list[tuple[float, float]]) -> float:
    return sum(
        math.hypot(second[0] - first[0], second[1] - first[1])
        for first, second in zip(points, points[1:])
    )


def quadratic_boundary_polyline(
    start: tuple[float, float],
    end: tuple[float, float],
    curvature: object,
    *,
    flatness_tolerance_m: float,
    maximum_chord_m: float,
) -> tuple[list[tuple[float, float]], float, bool]:
    if curvature is None:
        return [start, end], 0.0, False
    if (
        not isinstance(curvature, dict)
        or curvature.get("type") != "quadratic"
        or not isinstance(curvature.get("params"), list)
        or len(curvature["params"]) != 1
        or not isinstance(curvature["params"][0], list)
        or len(curvature["params"][0]) != 2
    ):
        raise ValueError("OpenSew preview supports only relative quadratic edge curves")
    control = curvature["params"][0]
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        for value in control
    ):
        raise ValueError("OpenSew quadratic curve control point must be finite")
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    control_point = (
        start[0] + float(control[0]) * dx - float(control[1]) * dy,
        start[1] + float(control[0]) * dy + float(control[1]) * dx,
    )
    points = [start]
    maximum_flatness_bound = 0.0

    def subdivide(
        first: tuple[float, float],
        handle: tuple[float, float],
        last: tuple[float, float],
        depth: int,
    ) -> None:
        nonlocal maximum_flatness_bound
        chord_length = math.hypot(last[0] - first[0], last[1] - first[1])
        flatness_bound = point_segment_distance(handle, first, last)
        if flatness_bound <= flatness_tolerance_m and chord_length <= maximum_chord_m:
            maximum_flatness_bound = max(maximum_flatness_bound, flatness_bound)
            points.append(last)
            return
        if depth >= 24:
            raise ValueError("OpenSew quadratic curve exceeded adaptive tessellation depth")
        first_handle = ((first[0] + handle[0]) * 0.5, (first[1] + handle[1]) * 0.5)
        handle_last = ((handle[0] + last[0]) * 0.5, (handle[1] + last[1]) * 0.5)
        midpoint = (
            (first_handle[0] + handle_last[0]) * 0.5,
            (first_handle[1] + handle_last[1]) * 0.5,
        )
        subdivide(first, first_handle, midpoint, depth + 1)
        subdivide(midpoint, handle_last, last, depth + 1)

    subdivide(start, control_point, end, 0)
    return points, maximum_flatness_bound, True


def path_cumulative_lengths(points: list[tuple[float, float]]) -> list[float]:
    cumulative = [0.0]
    for first, second in zip(points, points[1:]):
        cumulative.append(
            cumulative[-1]
            + math.hypot(second[0] - first[0], second[1] - first[1])
        )
    return cumulative


def point_at_path_station(
    points: list[tuple[float, float]], cumulative: list[float], station: float
) -> tuple[float, float]:
    if len(points) < 2 or cumulative[-1] <= 0.0:
        raise ValueError("OpenSew edge path must have positive length")
    station = max(0.0, min(cumulative[-1], station))
    low = 0
    high = len(cumulative) - 1
    while low + 1 < high:
        middle = (low + high) // 2
        if cumulative[middle] <= station:
            low = middle
        else:
            high = middle
    segment_length = cumulative[low + 1] - cumulative[low]
    if segment_length <= 1e-15:
        return points[low]
    fraction = (station - cumulative[low]) / segment_length
    first = points[low]
    second = points[low + 1]
    return (
        first[0] + fraction * (second[0] - first[0]),
        first[1] + fraction * (second[1] - first[1]),
    )


def resample_path_by_count(
    points: list[tuple[float, float]], segment_count: int
) -> list[tuple[float, float]]:
    if segment_count < 1:
        raise ValueError("OpenSew curve sample count must be positive")
    cumulative = path_cumulative_lengths(points)
    if cumulative[-1] <= 0.0:
        raise ValueError("OpenSew curve path has zero length")
    return [
        point_at_path_station(points, cumulative, cumulative[-1] * index / segment_count)
        for index in range(segment_count + 1)
    ]


def path_resampling_deviation(
    source_points: list[tuple[float, float]], sampled_points: list[tuple[float, float]]
) -> float:
    source_cumulative = path_cumulative_lengths(source_points)
    sampled_cumulative = path_cumulative_lengths(sampled_points)
    if source_cumulative[-1] <= 0.0 or sampled_cumulative[-1] <= 0.0:
        raise ValueError("OpenSew curve paths must have positive length")
    maximum_deviation = 0.0
    for index, point in enumerate(source_points):
        resampled_point = point_at_path_station(
            sampled_points,
            sampled_cumulative,
            sampled_cumulative[-1] * source_cumulative[index] / source_cumulative[-1],
        )
        maximum_deviation = max(
            maximum_deviation,
            math.hypot(point[0] - resampled_point[0], point[1] - resampled_point[1]),
        )
    return maximum_deviation


def build_edge_sampling_plan(
    source_path: list[tuple[float, float]],
    flatness_bound_m: float,
    *,
    target_grid_meters: float,
    maximum_segment_fraction: float,
    maximum_deviation_fraction: float,
    minimum_segment_count: int = 1,
) -> dict[str, Any]:
    source_length_m = polyline_length(source_path)
    if source_length_m <= 1e-12:
        raise ValueError("OpenSew edge has zero source length")
    tolerance_m = target_grid_meters * maximum_deviation_fraction
    segment_limit_m = target_grid_meters * maximum_segment_fraction
    segment_count = max(
        1,
        minimum_segment_count,
        math.ceil(source_length_m / segment_limit_m),
    )
    while True:
        sampled_path = resample_path_by_count(source_path, segment_count)
        resampling_deviation_m = path_resampling_deviation(source_path, sampled_path)
        if resampling_deviation_m + flatness_bound_m <= tolerance_m:
            break
        if segment_count >= 65536:
            raise ValueError("OpenSew curve sampling exceeded 65536 edge segments")
        segment_count = min(65536, segment_count * 2)
    return {
        "sourcePath": source_path,
        "sampledPath": sampled_path,
        "sourceLengthM": source_length_m,
        "flatnessBoundM": flatness_bound_m,
        "resamplingDeviationM": resampling_deviation_m,
        "segmentCount": segment_count,
        "maximumDeviationM": flatness_bound_m + resampling_deviation_m,
    }


def boundary_data(mesh: bpy.types.Mesh) -> tuple[set[int], set[tuple[int, int]], dict[int, set[int]], int, int]:
    face_counts: dict[tuple[int, int], int] = {}
    for polygon in mesh.polygons:
        for edge_key in polygon.edge_keys:
            key = tuple(sorted(edge_key))
            face_counts[key] = face_counts.get(key, 0) + 1
    boundary_edges = {edge for edge, count in face_counts.items() if count == 1}
    boundary_vertices = {index for edge in boundary_edges for index in edge}
    boundary_neighbors: dict[int, set[int]] = {index: set() for index in boundary_vertices}
    for first, second in boundary_edges:
        boundary_neighbors[first].add(second)
        boundary_neighbors[second].add(first)
    all_edges = {tuple(sorted(edge.vertices)) for edge in mesh.edges}
    loose_edges = sum(edge not in face_counts for edge in all_edges)
    nonmanifold_edges = sum(count > 2 for count in face_counts.values())
    return boundary_vertices, boundary_edges, boundary_neighbors, loose_edges, nonmanifold_edges


def ordered_boundary_chain(
    boundary_neighbors: dict[int, set[int]], members: set[int]
) -> list[int]:
    """Order one named OpenSew edge group using its precomputed panel boundary."""
    adjacency = {
        index: sorted(boundary_neighbors.get(index, set()) & members)
        for index in members
    }
    ends = [index for index, neighbors in adjacency.items() if len(neighbors) == 1]
    start = ends[0] if ends else (min(members) if members else None)
    if start is None:
        return []
    chain = [start]
    previous = None
    current = start
    while True:
        following = [index for index in adjacency[current] if index != previous]
        if not following:
            break
        previous, current = current, following[0]
        if current in chain:
            break
        chain.append(current)
    return chain


def bmesh_vertex_position_key(vert: bmesh.types.BMVert) -> tuple[float, float, float]:
    return tuple(round(float(value), 12) for value in vert.co)


def bmesh_boundary_chain(
    panel_bmesh: bmesh.types.BMesh,
    member_positions: set[tuple[float, float, float]],
) -> list[bmesh.types.BMVert]:
    panel_bmesh.verts.ensure_lookup_table()
    panel_bmesh.verts.index_update()
    vertex_by_position = {
        bmesh_vertex_position_key(vert): vert
        for vert in panel_bmesh.verts
        if vert.is_valid
    }
    members = {
        vertex_by_position[position]
        for position in member_positions
        if position in vertex_by_position
    }
    boundary_neighbors: dict[bmesh.types.BMVert, set[bmesh.types.BMVert]] = {}
    for edge in panel_bmesh.edges:
        if not edge.is_boundary:
            continue
        first, second = edge.verts
        boundary_neighbors.setdefault(first, set()).add(second)
        boundary_neighbors.setdefault(second, set()).add(first)
    valid_members = members
    adjacency = {
        vert: sorted(boundary_neighbors.get(vert, set()) & valid_members, key=lambda item: item.index)
        for vert in valid_members
    }
    ends = [vert for vert, neighbors in adjacency.items() if len(neighbors) == 1]
    candidates = ends or list(valid_members)
    if not candidates:
        return []
    start = min(candidates, key=lambda item: item.index)
    chain = [start]
    previous = None
    current = start
    while True:
        following = [vert for vert in adjacency[current] if vert is not previous]
        if not following:
            break
        previous, current = current, following[0]
        if current in chain:
            break
        chain.append(current)
    return chain


def subdivide_boundary_chain_to_count(
    panel_bmesh: bmesh.types.BMesh,
    chain: list[bmesh.types.BMVert],
    member_positions: set[tuple[float, float, float]],
    target_count: int,
) -> set[tuple[float, float, float]]:
    missing_count = target_count - len(chain)
    if missing_count <= 0:
        return set()
    chain_positions = [bmesh_vertex_position_key(vert) for vert in chain]
    chain_edges = list(zip(chain_positions, chain_positions[1:]))
    if not chain_edges:
        raise ValueError("cannot refine an OpenSew stitch chain with fewer than two vertices")
    cuts_by_edge: dict[int, int] = {}
    for insertion in range(missing_count):
        edge_index = min(
            len(chain_edges) - 1,
            int((insertion + 0.5) * len(chain_edges) / missing_count),
        )
        cuts_by_edge[edge_index] = cuts_by_edge.get(edge_index, 0) + 1

    inserted_positions: set[tuple[float, float, float]] = set()
    for edge_index, cuts in sorted(cuts_by_edge.items()):
        first_position, second_position = chain_edges[edge_index]
        panel_bmesh.verts.ensure_lookup_table()
        vertex_by_position = {
            bmesh_vertex_position_key(vert): vert
            for vert in panel_bmesh.verts
            if vert.is_valid
        }
        if first_position not in vertex_by_position or second_position not in vertex_by_position:
            raise ValueError("OpenSew boundary refinement could not recover edge endpoint coordinates")
        first = vertex_by_position[first_position]
        second = vertex_by_position[second_position]
        edge = next(
            (
                candidate
                for candidate in panel_bmesh.edges
                if candidate.is_valid
                and len(candidate.verts) == 2
                and {candidate.verts[0], candidate.verts[1]} == {first, second}
            ),
            None,
        )
        if edge is None or not edge.is_boundary:
            raise ValueError("OpenSew stitch refinement could not find its boundary edge")
        subdivision = bmesh.ops.subdivide_edges(
            panel_bmesh,
            edges=[edge],
            cuts=cuts,
            use_grid_fill=False,
        )
        created = {
            element
            for element in subdivision.get("geom_inner", [])
            if isinstance(element, bmesh.types.BMVert)
        }
        if len(created) != cuts:
            raise RuntimeError(
                f"OpenSew boundary split created {len(created)} vertices; expected {cuts}"
            )
        created_positions = {bmesh_vertex_position_key(vert) for vert in created}
        inserted_positions.update(created_positions)
        member_positions.update(created_positions)
    panel_bmesh.verts.ensure_lookup_table()
    panel_bmesh.verts.index_update()
    refined_chain = bmesh_boundary_chain(panel_bmesh, member_positions)
    if len(refined_chain) != target_count:
        current_members = {
            bmesh_vertex_position_key(vert)
            for vert in panel_bmesh.verts
            if vert.is_valid
        }
        valid_member_positions = member_positions & current_members
        valid_members = {
            vert
            for vert in panel_bmesh.verts
            if bmesh_vertex_position_key(vert) in valid_member_positions
        }
        linked_boundary_edges = [
            edge
            for edge in panel_bmesh.edges
            if edge.is_boundary and edge.verts[0] in valid_members and edge.verts[1] in valid_members
        ]
        degree_counts: dict[int, int] = {}
        for edge in linked_boundary_edges:
            degree_counts[edge.verts[0]] = degree_counts.get(edge.verts[0], 0) + 1
            degree_counts[edge.verts[1]] = degree_counts.get(edge.verts[1], 0) + 1
        raise RuntimeError(
            f"OpenSew refined chain has {len(refined_chain)} vertices; expected {target_count} "
            f"(members={len(member_positions)}, valid={len(valid_members)}, "
            f"linkedBoundaryEdges={len(linked_boundary_edges)}, "
            f"degreeCounts={[degree_counts.get(vert, 0) for vert in valid_members]}, "
            f"inserted={len(inserted_positions)})"
        )
    return inserted_positions

def ordered_parameters(
    obj: bpy.types.Object,
    indices: list[int],
    edge_path: list[tuple[float, float]],
    label: str,
) -> tuple[list[float], list[tuple[float, float]], float]:
    cumulative = path_cumulative_lengths(edge_path)
    total_length = cumulative[-1]
    if total_length <= 1e-16:
        raise ValueError(f"pattern edge {label} has zero length")
    points = []
    for index in indices:
        coord = obj.data.vertices[index].co
        points.append((float(coord.x), float(coord.z)))
    parameters = []
    maximum_projection_error = 0.0
    for point in points:
        nearest_error = float("inf")
        nearest_station = 0.0
        for segment_index, (first, second) in enumerate(zip(edge_path, edge_path[1:])):
            dx = second[0] - first[0]
            dy = second[1] - first[1]
            length_sq = dx * dx + dy * dy
            if length_sq <= 1e-24:
                continue
            fraction = max(
                0.0,
                min(
                    1.0,
                    ((point[0] - first[0]) * dx + (point[1] - first[1]) * dy)
                    / length_sq,
                ),
            )
            projected = (first[0] + fraction * dx, first[1] + fraction * dy)
            error = math.hypot(point[0] - projected[0], point[1] - projected[1])
            if error < nearest_error:
                nearest_error = error
                nearest_station = cumulative[segment_index] + fraction * math.sqrt(length_sq)
        if not math.isfinite(nearest_error):
            raise ValueError(f"pattern edge {label} has no projectable path segments")
        maximum_projection_error = max(maximum_projection_error, nearest_error)
        parameters.append(nearest_station / total_length)
    if any(second < first - 1e-6 for first, second in zip(parameters, parameters[1:])):
        raise ValueError(f"OpenSew boundary chain for {label} does not follow its curved edge")
    return parameters, points, maximum_projection_error


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir: Path = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "opensew-2d-run.json"
    if result_path.exists():
        raise FileExistsError(f"refusing to overwrite previous OpenSew run: {result_path}")
    if (
        bpy.app.version_string != args.expected_blender_version
        and not bpy.app.version_string.startswith(f"{args.expected_blender_version} ")
    ):
        raise RuntimeError(
            f"expected Blender {args.expected_blender_version}, found {bpy.app.version_string}"
        )
    actual_revision = subprocess.run(
        ["git", "-C", str(args.opensew_root.resolve()), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if actual_revision != args.expected_revision:
        raise RuntimeError(
            f"OpenSew revision mismatch: expected {args.expected_revision}, found {actual_revision}"
        )
    sys.path.insert(0, str(args.opensew_root.resolve()))
    from clothing_design import patterns as open_sew_patterns  # noqa: PLC0415

    pattern_path = args.pattern.resolve()
    stitch_path = args.stitches.resolve()
    pattern = json.loads(pattern_path.read_text(encoding="utf-8-sig"))
    stitch_graph = json.loads(stitch_path.read_text(encoding="utf-8-sig"))
    if pattern.get("productId") != stitch_graph.get("productId"):
        raise ValueError("pattern and stitch graph product IDs do not match")
    if pattern.get("units") != "meter":
        raise ValueError("OpenSew preview accepts only meter-based pattern contracts")
    if not pattern.get("pieces"):
        raise ValueError("pattern contract has no pieces")
    if not math.isfinite(args.target_grid_meters) or args.target_grid_meters <= 0.0:
        raise ValueError("OpenSew target grid must be finite and positive")
    if not math.isfinite(args.endpoint_tolerance_mm) or args.endpoint_tolerance_mm < 0.0:
        raise ValueError("OpenSew endpoint tolerance must be finite and nonnegative")

    piece_by_id: dict[str, dict[str, Any]] = {}
    edge_geometry: dict[tuple[str, str], dict[str, Any]] = {}
    for piece in pattern["pieces"]:
        piece_id = str(piece["pieceId"])
        if piece_id in piece_by_id:
            raise ValueError(f"duplicate piece ID: {piece_id}")
        piece_by_id[piece_id] = piece
        boundary = piece.get("boundary")
        edges = piece.get("edges")
        if not isinstance(boundary, list) or len(boundary) < 3 or not isinstance(edges, list) or not edges:
            raise ValueError(f"pattern piece {piece_id} has no usable boundary or edges")
        parsed_boundary: list[tuple[float, float]] = []
        for point in boundary:
            if not isinstance(point, list) or len(point) != 2 or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in point
            ):
                raise ValueError(f"pattern piece {piece_id} has an invalid boundary coordinate")
            parsed_boundary.append((float(point[0]), float(point[1])))
        piece["_parsedBoundary"] = parsed_boundary
        seen_edge_ids: set[str] = set()
        for edge in edges:
            edge_id = str(edge["edgeId"])
            if edge_id in seen_edge_ids:
                raise ValueError(f"duplicate edge ID {piece_id}/{edge_id}")
            seen_edge_ids.add(edge_id)
            start_index = edge.get("startVertex")
            end_index = edge.get("endVertex")
            if (
                isinstance(start_index, bool)
                or not isinstance(start_index, int)
                or isinstance(end_index, bool)
                or not isinstance(end_index, int)
                or start_index < 0
                or end_index < 0
                or start_index >= len(parsed_boundary)
                or end_index >= len(parsed_boundary)
                or start_index == end_index
            ):
                raise ValueError(f"pattern edge {piece_id}/{edge_id} has invalid endpoint indices")
            start = parsed_boundary[start_index]
            end = parsed_boundary[end_index]
            curve_path, flatness_bound_m, is_curved = quadratic_boundary_polyline(
                start,
                end,
                edge.get("curvature"),
                flatness_tolerance_m=args.target_grid_meters * 0.05,
                maximum_chord_m=args.target_grid_meters * 0.5,
            )
            geometry = build_edge_sampling_plan(
                curve_path,
                flatness_bound_m,
                target_grid_meters=args.target_grid_meters,
                maximum_segment_fraction=0.75,
                maximum_deviation_fraction=0.15,
            )
            geometry.update(
                {
                    "start": start,
                    "end": end,
                    "isCurved": is_curved,
                }
            )
            edge_geometry[(piece_id, edge_id)] = geometry

    stitch_rows = stitch_graph.get("stitches")
    if not isinstance(stitch_rows, list):
        raise ValueError("stitch graph must contain a stitches list")
    stitch_edge_refs: set[tuple[str, str]] = set()
    edge_sample_counts = {
        key: int(geometry["segmentCount"])
        for key, geometry in edge_geometry.items()
    }
    normalized_stitches: list[dict[str, Any]] = []
    for stitch in stitch_rows:
        first_ref = stitch.get("first")
        second_ref = stitch.get("second")
        if not isinstance(first_ref, dict) or not isinstance(second_ref, dict):
            raise ValueError("stitch pair must reference first and second edges")
        first_key = (str(first_ref.get("pieceId")), str(first_ref.get("edgeId")))
        second_key = (str(second_ref.get("pieceId")), str(second_ref.get("edgeId")))
        if first_key not in edge_geometry or second_key not in edge_geometry:
            raise ValueError(f"stitch {stitch.get('stitchId')} references an unknown pattern edge")
        if first_key == second_key:
            raise ValueError(f"stitch {stitch.get('stitchId')} references the same edge twice")
        if first_key in stitch_edge_refs or second_key in stitch_edge_refs:
            raise ValueError("OpenSew preview requires each named edge to occur in at most one stitch pair")
        direction = str(stitch.get("direction"))
        if direction not in {"same", "reversed"}:
            raise ValueError(f"unsupported stitch direction: {direction}")
        stitch_edge_refs.update((first_key, second_key))
        common_count = max(edge_sample_counts[first_key], edge_sample_counts[second_key])
        edge_sample_counts[first_key] = common_count
        edge_sample_counts[second_key] = common_count
        normalized_stitches.append(
            {
                "stitch": stitch,
                "firstKey": first_key,
                "secondKey": second_key,
                "direction": direction,
                "sampleCount": common_count,
            }
        )
    for key, geometry in edge_geometry.items():
        geometry["samplingPlan"] = build_edge_sampling_plan(
            geometry["sourcePath"],
            geometry["flatnessBoundM"],
            target_grid_meters=args.target_grid_meters,
            maximum_segment_fraction=0.75,
            maximum_deviation_fraction=0.15,
            minimum_segment_count=edge_sample_counts[key],
        )
        plan = geometry["samplingPlan"]
        if plan["segmentCount"] != edge_sample_counts[key]:
            raise ValueError(f"shared stitch sample count changed while planning edge {key[0]}/{key[1]}")

    panel_builds: dict[str, dict[str, Any]] = {}
    for piece in pattern["pieces"]:
        piece_id = str(piece["pieceId"])
        boundary = [Vector(point) for point in piece["_parsedBoundary"]]
        segments = []
        for edge in piece["edges"]:
            edge_id = str(edge["edgeId"])
            name = f"{piece_id}__{edge_id}"
            sampled_edge_path = edge_geometry[(piece_id, edge_id)]["samplingPlan"]["sampledPath"]
            segments.append((name, [Vector(point) for point in sampled_edge_path]))
        sampled, labels = open_sew_patterns.resample_loop(segments, args.target_grid_meters)
        if len(sampled) < 3 or len(sampled) != len(labels):
            raise RuntimeError(f"OpenSew returned an invalid outline for {piece_id}")
        panel_bmesh = open_sew_patterns.panel_bmesh(sampled, args.target_grid_meters, labels)
        raw_members = open_sew_patterns.assign_segments(panel_bmesh, sampled, labels)
        panel_bmesh.verts.ensure_lookup_table()
        panel_bmesh.verts.index_update()
        boundary_vertices = [vert for vert in panel_bmesh.verts if vert.is_boundary]
        if not boundary_vertices:
            panel_bmesh.free()
            raise RuntimeError(f"OpenSew returned no boundary vertices for {piece_id}")
        member_positions: dict[str, set[tuple[float, float, float]]] = {}
        endpoint_added_positions: dict[str, set[tuple[float, float, float]]] = {}
        split_added_positions: dict[str, set[tuple[float, float, float]]] = {}
        for edge in piece["edges"]:
            edge_id = str(edge["edgeId"])
            name = f"{piece_id}__{edge_id}"
            members = {
                bmesh_vertex_position_key(panel_bmesh.verts[index])
                for index in raw_members.get(name, [])
                if 0 <= index < len(panel_bmesh.verts)
            }
            extras: set[tuple[float, float, float]] = set()
            geometry = edge_geometry[(piece_id, edge_id)]
            for endpoint in (geometry["start"], geometry["end"]):
                nearest = min(
                    boundary_vertices,
                    key=lambda vert: math.hypot(
                        float(vert.co.x) - endpoint[0],
                        float(vert.co.z) - endpoint[1],
                    ),
                )
                endpoint_error_mm = distance_mm(
                    (float(nearest.co.x), float(nearest.co.z)), endpoint
                )
                nearest_position = bmesh_vertex_position_key(nearest)
                if endpoint_error_mm <= args.endpoint_tolerance_mm and nearest_position not in members:
                    members.add(nearest_position)
                    extras.add(nearest_position)
            member_positions[edge_id] = members
            endpoint_added_positions[edge_id] = extras
            split_added_positions[edge_id] = set()
        panel_builds[piece_id] = {
            "piece": piece,
            "bmesh": panel_bmesh,
            "memberPositions": member_positions,
            "endpointAddedPositions": endpoint_added_positions,
            "splitAddedPositions": split_added_positions,
        }

    for normalized in normalized_stitches:
        first_piece_id, first_edge_id = normalized["firstKey"]
        second_piece_id, second_edge_id = normalized["secondKey"]
        first_build = panel_builds[first_piece_id]
        second_build = panel_builds[second_piece_id]
        first_chain = bmesh_boundary_chain(
            first_build["bmesh"], first_build["memberPositions"][first_edge_id]
        )
        second_chain = bmesh_boundary_chain(
            second_build["bmesh"], second_build["memberPositions"][second_edge_id]
        )
        if len(first_chain) < 2 or len(second_chain) < 2:
            raise RuntimeError(f"OpenSew stitch {normalized['stitch']['stitchId']} has an incomplete boundary chain")
        target_count = max(len(first_chain), len(second_chain))
        if len(first_chain) < target_count:
            first_build["splitAddedPositions"][first_edge_id].update(
                subdivide_boundary_chain_to_count(
                    first_build["bmesh"],
                    first_chain,
                    first_build["memberPositions"][first_edge_id],
                    target_count,
                )
            )
        if len(second_chain) < target_count:
            second_build["splitAddedPositions"][second_edge_id].update(
                subdivide_boundary_chain_to_count(
                    second_build["bmesh"],
                    second_chain,
                    second_build["memberPositions"][second_edge_id],
                    target_count,
                )
            )

    for piece_id, build in panel_builds.items():
        panel_bmesh = build["bmesh"]
        panel_bmesh.verts.ensure_lookup_table()
        panel_bmesh.verts.index_update()
        piece = build["piece"]
        index_by_position = {
            bmesh_vertex_position_key(vert): vert.index
            for vert in panel_bmesh.verts
            if vert.is_valid
        }
        build["segmentVertexIndices"] = {
            str(edge["edgeId"]): sorted(
                index_by_position[position]
                for position in build["memberPositions"][str(edge["edgeId"])]
                if position in index_by_position
            )
            for edge in piece["edges"]
        }
        build["endpointAddedIndices"] = {
            str(edge["edgeId"]): sorted(
                index_by_position[position]
                for position in build["endpointAddedPositions"][str(edge["edgeId"])]
                if position in index_by_position
            )
            for edge in piece["edges"]
        }
        build["splitAddedIndices"] = {
            str(edge["edgeId"]): sorted(
                index_by_position[position]
                for position in build["splitAddedPositions"][str(edge["edgeId"])]
                if position in index_by_position
            )
            for edge in piece["edges"]
        }

    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    edge_records: dict[tuple[str, str], dict[str, Any]] = {}
    panel_records: list[dict[str, Any]] = []
    total_non_quads = 0
    all_boundary_manifold = True

    for piece in pattern["pieces"]:
        piece_id = str(piece["pieceId"])
        build = panel_builds[piece_id]
        boundary = [Vector(point) for point in piece["_parsedBoundary"]]
        segment_ends: dict[str, list[list[float]]] = {}
        for edge in piece["edges"]:
            edge_id = str(edge["edgeId"])
            name = f"{piece_id}__{edge_id}"
            start = boundary[int(edge["startVertex"])]
            end = boundary[int(edge["endVertex"])]
            segment_ends[name] = [[float(start.x), float(start.y)], [float(end.x), float(end.y)]]

        panel_bmesh = build["bmesh"]
        segment_vertex_indices = {
            f"{piece_id}__{edge_id}": indices
            for edge_id, indices in build["segmentVertexIndices"].items()
        }
        mesh = bpy.data.meshes.new(f"OpenSew2D_{piece_id}")
        panel_bmesh.to_mesh(mesh)
        panel_bmesh.free()
        mesh.update()
        obj = bpy.data.objects.new(piece_id, mesh)
        bpy.context.scene.collection.objects.link(obj)
        obj["sourcePieceId"] = piece_id
        obj["sourceUnits"] = "meter"
        obj["openSewPatternGridMeters"] = args.target_grid_meters
        obj["opensewEndpointAwareGroupAdapter"] = True
        obj["cd_seg_ends"] = json.dumps(segment_ends, separators=(",", ":"))

        group_by_edge: dict[str, bpy.types.VertexGroup] = {}
        for edge in piece["edges"]:
            edge_id = str(edge["edgeId"])
            name = f"{piece_id}__{edge_id}"
            group = obj.vertex_groups.new(name="SEG_" + name)
            initial_members = segment_vertex_indices.get(name, [])
            if initial_members:
                group.add(initial_members, 1.0, "REPLACE")
            group_by_edge[edge_id] = group

        boundary_vertices, boundary_edges, boundary_neighbors, loose_edges, nonmanifold_edges = boundary_data(mesh)
        group_stats: list[dict[str, Any]] = []
        for edge in piece["edges"]:
            edge_id = str(edge["edgeId"])
            geometry = edge_geometry[(piece_id, edge_id)]
            sampling_plan = geometry["samplingPlan"]
            source_path = geometry["sourcePath"]
            group = group_by_edge[edge_id]
            start = geometry["start"]
            end = geometry["end"]
            endpoints = (start, end)
            nearest_vertices = []
            for endpoint in endpoints:
                index = min(
                    boundary_vertices,
                    key=lambda candidate: math.hypot(
                        float(mesh.vertices[candidate].co.x) - float(endpoint[0]),
                        float(mesh.vertices[candidate].co.z) - float(endpoint[1]),
                    ),
                )
                coord = mesh.vertices[index].co
                nearest_error = distance_mm(
                    (float(coord.x), float(coord.z)), endpoint
                )
                nearest_vertices.append((index, nearest_error))

            member_set = set(segment_vertex_indices.get(f"{piece_id}__{edge_id}", []))
            added = list(build["endpointAddedIndices"][edge_id])
            for index, endpoint_error in nearest_vertices:
                if endpoint_error > args.endpoint_tolerance_mm:
                    continue
                if index not in member_set:
                    group.add([index], 1.0, "REPLACE")
                    member_set.add(index)
                    added.append(index)

            chain = ordered_boundary_chain(boundary_neighbors, member_set)
            chain = open_sew_patterns.orient_chain(obj, f"{piece_id}__{edge_id}", chain)
            source_length_m = float(geometry["sourceLengthM"])
            if len(chain) >= 2:
                chain_params, chain_points, projection_error_m = ordered_parameters(
                    obj,
                    chain,
                    source_path,
                    f"{piece_id}/{edge_id}",
                )
            else:
                chain_params, chain_points, projection_error_m = [], [], float("inf")
            start_error = distance_mm(chain_points[0], start) if chain_points else float("inf")
            end_error = distance_mm(chain_points[-1], end) if chain_points else float("inf")
            span_m = (max(chain_params) - min(chain_params)) * source_length_m if chain_params else 0.0
            mesh_boundary_length_m = polyline_length(chain_points)
            resampling_deviation_mm = float(sampling_plan["resamplingDeviationM"]) * 1000.0
            maximum_curve_deviation_mm = float(sampling_plan["maximumDeviationM"]) * 1000.0
            covers_group = set(chain) == member_set
            endpoint_inclusive = (
                start_error <= args.endpoint_tolerance_mm
                and end_error <= args.endpoint_tolerance_mm
            )
            record = {
                "pieceId": piece_id,
                "edgeId": edge_id,
                "role": edge.get("role"),
                "stitchReferenced": (piece_id, edge_id) in stitch_edge_refs,
                "sourceLengthMm": round(source_length_m * 1000.0, 6),
                "meshBoundaryLengthMm": round(mesh_boundary_length_m * 1000.0, 6),
                "curvedSourceEdge": bool(geometry["isCurved"]),
                "curveApproximationBoundMm": round(float(geometry["flatnessBoundM"]) * 1000.0, 6),
                "curveResamplingDeviationMm": round(resampling_deviation_mm, 6),
                "curveSamplingErrorBoundMm": round(maximum_curve_deviation_mm, 6),
                "curveSampleSegmentCount": int(sampling_plan["segmentCount"]),
                "maximumBoundaryProjectionErrorMm": round(projection_error_m * 1000.0, 6),
                "chainVertexCount": len(chain),
                "assignedGroupVertexCount": len(member_set),
                "chainCoversEntireGroup": covers_group,
                "chainStartEndpointErrorMm": round(start_error, 6),
                "chainEndEndpointErrorMm": round(end_error, 6),
                "endpointInclusive": endpoint_inclusive,
                "endpointMembershipAddedIndices": added,
                "stitchBoundarySubdivisionVertexCount": len(build["splitAddedIndices"][edge_id]),
                "groupSpanErrorMm": round(abs(span_m - source_length_m) * 1000.0, 6),
                "boundaryChainConnected": len(chain) == len(member_set),
                "boundaryProjectionWithinCurveTolerance": (
                    projection_error_m + float(geometry["flatnessBoundM"])
                    <= args.target_grid_meters * 0.15 + 1e-9
                ),
            }
            edge_records[(piece_id, edge_id)] = {
                "report": record,
                "parameters": chain_params,
                "lengthMm": source_length_m * 1000.0,
                "meshBoundaryLengthMm": mesh_boundary_length_m * 1000.0,
            }
            group_stats.append(record)

        non_quads = sum(len(poly.vertices) != 4 for poly in mesh.polygons)
        total_non_quads += non_quads
        all_boundary_manifold &= not loose_edges and not nonmanifold_edges
        panel_records.append({
            "pieceId": piece_id,
            "vertexCount": len(mesh.vertices),
            "edgeCount": len(mesh.edges),
            "faceCount": len(mesh.polygons),
            "boundaryVertexCount": len(boundary_vertices),
            "boundaryEdgeCount": len(boundary_edges),
            "looseEdgeCount": loose_edges,
            "nonmanifoldEdgeCount": nonmanifold_edges,
            "nonQuadFaceCount": non_quads,
            "flatInXZ": all(abs(float(vertex.co.y)) <= 1e-9 for vertex in mesh.vertices),
            "namedEdgeGroups": group_stats,
        })

    stitch_pairs: list[dict[str, Any]] = []
    for normalized in normalized_stitches:
        stitch = normalized["stitch"]
        first_ref, second_ref = stitch["first"], stitch["second"]
        first_key = normalized["firstKey"]
        second_key = normalized["secondKey"]
        first = edge_records[first_key]
        second = edge_records[second_key]
        direction = normalized["direction"]
        first_params = first["parameters"]
        second_params = second["parameters"]
        aligned_second = second_params if direction == "same" else [1.0 - value for value in reversed(second_params)]
        paired_count = min(len(first_params), len(aligned_second))
        station_errors = []
        for first_parameter, second_parameter in zip(first_params, aligned_second):
            first_station = first_parameter * first["lengthMm"]
            second_station = second_parameter * second["lengthMm"]
            station_errors.append(abs(first_station - second_station))
        stitch_pairs.append({
            "stitchId": stitch["stitchId"],
            "direction": direction,
            "first": {"pieceId": first_key[0], "edgeId": first_key[1]},
            "second": {"pieceId": second_key[0], "edgeId": second_key[1]},
            "firstChainVertexCount": len(first_params),
            "secondChainVertexCount": len(second_params),
            "sampleCountsEqual": len(first_params) == len(second_params),
            "sourceEdgeLengthDifferenceMm": round(
                abs(first["lengthMm"] - second["lengthMm"]), 6
            ),
            "bothChainsEndpointInclusive": (
                first["report"]["endpointInclusive"] and second["report"]["endpointInclusive"]
            ),
            "bothChainsCoverGroups": (
                first["report"]["chainCoversEntireGroup"]
                and second["report"]["chainCoversEntireGroup"]
            ),
            "bothChainsProjectWithinCurveTolerance": (
                first["report"]["boundaryProjectionWithinCurveTolerance"]
                and second["report"]["boundaryProjectionWithinCurveTolerance"]
            ),
            "openSewPairingNodeCount": paired_count,
            "openSewIndexPairingMaxStationGapMm": round(max(station_errors, default=0.0), 6),
        })

    all_endpoint_chains = all(
        row["report"]["endpointInclusive"] and row["report"]["chainCoversEntireGroup"]
        for row in edge_records.values()
    )
    all_stitch_pairs = all(
        row["sampleCountsEqual"]
        and row["bothChainsEndpointInclusive"]
        and row["bothChainsCoverGroups"]
        and row["bothChainsProjectWithinCurveTolerance"]
        for row in stitch_pairs
    )
    all_curve_sampling_within_tolerance = all(
        row["curveSamplingErrorBoundMm"] <= args.target_grid_meters * 1000.0 * 0.15 + 1e-6
        and row["boundaryProjectionWithinCurveTolerance"]
        for edge in edge_records.values()
        for row in (edge["report"],)
    )
    all_flat = all(row["flatInXZ"] for row in panel_records)
    total_edges = sum(len(piece["edges"]) for piece in pattern["pieces"])
    result_path = output_dir / "opensew-2d-run.json"
    blend_path = output_dir / "opensew-2d-panels.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    open_sew_root = args.opensew_root.resolve()
    implementation_path = open_sew_root / "clothing_design" / "patterns.py"
    license_path = open_sew_root / "LICENSE"
    passed = (
        len(edge_records) == total_edges
        and len(stitch_pairs) == len(stitch_graph.get("stitches", []))
        and all_endpoint_chains
        and all_stitch_pairs
        and all_curve_sampling_within_tolerance
        and all_flat
        and all_boundary_manifold
    )
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "productId": pattern["productId"],
        "measuredAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "stage": "OPENSEW_2D_PANEL_MESH_AND_NAMED_SEAM_CHAINS",
        "status": "PASS_2D_ENDPOINT_AWARE_ONLY" if passed else "FAIL_2D_ENDPOINT_AWARE",
        "tool": {
            "name": "OpenSew-2",
            "revision": actual_revision,
            "license": "GPL-3.0-or-later",
            "implementation": "quadratic adaptive tessellation + shared stitch arc-length sampling + resample_loop + panel_bmesh + assign_segments + endpoint-aware shared-corner groups + orient_chain",
            "implementationSha256": sha256(implementation_path),
            "blenderVersion": bpy.app.version_string,
            "targetGridMeters": args.target_grid_meters,
            "endpointToleranceMm": args.endpoint_tolerance_mm,
            "quadraticCurveFlatnessToleranceMm": args.target_grid_meters * 50.0,
            "curveSamplingErrorToleranceMm": args.target_grid_meters * 150.0,
            "maximumCurveChordMm": args.target_grid_meters * 500.0,
        },
        "inputs": {
            "patternDraft": {"path": pattern_path.as_posix(), "sha256": sha256(pattern_path)},
            "stitchGraph": {"path": stitch_path.as_posix(), "sha256": sha256(stitch_path)},
            "license": {"path": license_path.as_posix(), "sha256": sha256(license_path)},
        },
        "counts": {
            "panelCount": len(panel_records),
            "namedEdgeGroupCount": len(edge_records),
            "canonicalNamedEdgeCount": total_edges,
            "stitchPairCount": len(stitch_pairs),
            "nonQuadFaceCount": total_non_quads,
        },
        "checks": {
            "allPanelMeshesFlatInXZ": all_flat,
            "noLooseOrNonmanifoldPanelEdges": all_boundary_manifold,
            "allNamedEdgesHaveConnectedEndpointInclusiveChains": all_endpoint_chains,
            "allStitchPairsHaveEndpointInclusiveChains": all_stitch_pairs,
            "allCurvedEdgesPreservedWithinSamplingTolerance": all_curve_sampling_within_tolerance,
            "allStitchPairSampleCountsEqual": all(row["sampleCountsEqual"] for row in stitch_pairs),
            "stitchPairSampleCountMismatchCount": sum(
                not row["sampleCountsEqual"] for row in stitch_pairs
            ),
            "maximumPairedSourceEdgeLengthDifferenceMm": round(
                max(
                    (row["sourceEdgeLengthDifferenceMm"] for row in stitch_pairs),
                    default=0.0,
                ),
                6,
            ),
            "maximumOpenSewIndexPairingStationGapMm": round(
                max((row["openSewIndexPairingMaxStationGapMm"] for row in stitch_pairs), default=0.0), 6
            ),
            "maximumCurveSamplingErrorBoundMm": round(
                max(
                    (edge["report"]["curveSamplingErrorBoundMm"] for edge in edge_records.values()),
                    default=0.0,
                ),
                6,
            ),
            "curvedEdgeCount": sum(
                bool(edge["report"]["curvedSourceEdge"]) for edge in edge_records.values()
            ),
            "maximumBoundaryProjectionErrorMm": round(
                max(
                    (edge["report"]["maximumBoundaryProjectionErrorMm"] for edge in edge_records.values()),
                    default=0.0,
                ),
                6,
            ),
            "threeDGenerated": False,
            "garmentAssemblyCreated": False,
            "clothSimulationRun": False,
            "canonicalPatternChanged": False,
            "canonicalStitchGraphChanged": False,
        },
        "panels": panel_records,
        "stitchPairs": stitch_pairs,
        "output": {"blendPath": blend_path.as_posix(), "blendSha256": sha256(blend_path)},
        "decision": "2D panel meshing and curve-aware seam-chain evidence only. Relative quadratic curves are adaptively tessellated and resampled by arc length; stitch mates share a segment count and their station gap uses source-curve arc-length parameters. Unsupported curve types, repeated edge stitch assignments, curve error beyond the 15% grid tolerance, or unequal paired chain counts fail this audit. The endpoint adapter may include each corner in both adjacent edge groups. No 3D assembly, sewing simulation, avatar fit, appearance review, or release result is inferred.",
    }
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> int:
    args = parse_args()
    try:
        result = run(args)
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        raise
    print(json.dumps({
        "status": result["status"],
        "resultPath": result["output"]["blendPath"].replace("opensew-2d-panels.blend", "opensew-2d-run.json"),
        "panelCount": result["counts"]["panelCount"],
        "namedEdgeGroupCount": result["counts"]["namedEdgeGroupCount"],
        "stitchPairCount": result["counts"]["stitchPairCount"],
        "allNamedEdgesHaveEndpointChains": result["checks"]["allNamedEdgesHaveConnectedEndpointInclusiveChains"],
        "maximumOpenSewIndexPairingStationGapMm": result["checks"]["maximumOpenSewIndexPairingStationGapMm"],
        "threeDGenerated": result["checks"]["threeDGenerated"],
    }, ensure_ascii=False))
    return 0 if result["status"] == "PASS_2D_ENDPOINT_AWARE_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
