#!/usr/bin/env python3
"""Run the pinned GarmentCode/PyGarment 2D panel preview runtime."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import re
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--upstream-root", required=True, type=Path)
    parser.add_argument("--upstream-revision", required=True)
    parser.add_argument("--python-version", required=True)
    parser.add_argument("--pygarment-version", required=True)
    parser.add_argument("--requirements-lock", required=True, type=Path)
    parser.add_argument(
        "--stitch-export-mode",
        choices=("preview-only", "strict-boundary-edges"),
        default="preview-only",
    )
    return parser.parse_args()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_locked_packages(path: Path) -> str:
    mismatches: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        requirement = line.strip()
        if not requirement or requirement.startswith("#"):
            continue
        name, separator, expected = requirement.partition("==")
        if not separator or not name or not expected:
            raise ValueError(f"invalid pinned requirement: {requirement!r}")
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            actual = "missing"
        if actual != expected:
            mismatches.append(f"{name}: expected {expected}, found {actual}")
    if mismatches:
        raise RuntimeError(
            "GarmentCode dependency lock mismatch: " + "; ".join(mismatches)
        )
    return _sha256(path)


def _edge_direction(pattern: dict[str, object], reference: dict[str, object]) -> tuple[float, float]:
    panel_name = reference.get("panel")
    edge_index = reference.get("edge")
    panels = pattern.get("panels")
    if not isinstance(panel_name, str) or not isinstance(edge_index, int):
        raise ValueError("GarmentCode stitch reference requires a panel and edge index")
    if not isinstance(panels, dict) or panel_name not in panels:
        raise ValueError(f"GarmentCode stitch references unknown panel {panel_name!r}")
    panel = panels[panel_name]
    if not isinstance(panel, dict):
        raise ValueError(f"GarmentCode panel {panel_name!r} is invalid")
    edges = panel.get("edges")
    vertices = panel.get("vertices")
    if not isinstance(edges, list) or not 0 <= edge_index < len(edges):
        raise ValueError(f"GarmentCode stitch references invalid edge {panel_name}.{edge_index}")
    if not isinstance(vertices, list):
        raise ValueError(f"GarmentCode panel {panel_name!r} has no vertices")
    edge = edges[edge_index]
    endpoints = edge.get("endpoints") if isinstance(edge, dict) else None
    if not isinstance(endpoints, list) or len(endpoints) != 2:
        raise ValueError(f"GarmentCode edge {panel_name}.{edge_index} has no endpoint pair")
    start_index, end_index = endpoints
    if not (isinstance(start_index, int) and isinstance(end_index, int)):
        raise ValueError(f"GarmentCode edge {panel_name}.{edge_index} has invalid endpoints")
    if not (0 <= start_index < len(vertices) and 0 <= end_index < len(vertices)):
        raise ValueError(f"GarmentCode edge {panel_name}.{edge_index} endpoint is out of range")
    start, end = vertices[start_index], vertices[end_index]
    if not (isinstance(start, list) and isinstance(end, list) and len(start) >= 2 and len(end) >= 2):
        raise ValueError(f"GarmentCode edge {panel_name}.{edge_index} has invalid vertex coordinates")
    vector = (float(end[0]) - float(start[0]), float(end[1]) - float(start[1]))
    if vector == (0.0, 0.0):
        raise ValueError(f"GarmentCode edge {panel_name}.{edge_index} has zero length")
    return vector


def _audit_stitch_orientations(pattern: object, adapter_metadata: dict[str, object]) -> dict[str, object]:
    if not isinstance(pattern, dict):
        raise ValueError("GarmentCode pattern output is invalid")
    stitches = pattern.get("stitches")
    mappings = adapter_metadata.get("stitchMapping")
    panel_key_map = adapter_metadata.get("panelKeyMap")
    if not isinstance(stitches, list) or not isinstance(mappings, list):
        raise ValueError("GarmentCode orientation audit requires submitted stitch mappings")
    if not isinstance(panel_key_map, dict):
        raise ValueError("GarmentCode orientation audit requires the canonical panel map")
    canonical_piece_to_panel = {piece_id: panel for panel, piece_id in panel_key_map.items()}
    if len(stitches) != len(mappings):
        raise ValueError("GarmentCode changed the number of submitted stitch pairs")

    audited = []
    for index, (pair, mapping) in enumerate(zip(stitches, mappings)):
        if (
            not isinstance(pair, list)
            or len(pair) not in (2, 3)
            or (len(pair) == 3 and pair[2] != "right_wrong")
            or not isinstance(mapping, dict)
        ):
            raise ValueError(f"GarmentCode stitch pair {index} is malformed")
        canonical_edges = mapping.get("edges")
        if not isinstance(canonical_edges, list) or len(canonical_edges) != 2:
            raise ValueError(f"Canonical stitch {index} has no two edge mappings")
        for side, reference in enumerate(pair[:2]):
            canonical_edge = canonical_edges[side]
            if not isinstance(reference, dict) or not isinstance(canonical_edge, dict):
                raise ValueError(f"GarmentCode stitch pair {index} has an invalid endpoint")
            expected_panel = canonical_piece_to_panel.get(canonical_edge.get("pieceId"))
            if reference.get("panel") != expected_panel:
                raise ValueError(
                    f"GarmentCode changed panel binding for stitch {mapping.get('stitchId')!r}"
                )

        actual_right_wrong = len(pair) == 3
        expected_right_wrong = mapping.get("garmentCodeRightWrong")
        if expected_right_wrong is not None and actual_right_wrong is not expected_right_wrong:
            raise ValueError(
                f"GarmentCode changed stitch orientation for {mapping.get('stitchId')!r}"
            )

        first = _edge_direction(pattern, pair[0])
        second = _edge_direction(pattern, pair[1])
        dot = first[0] * second[0] + first[1] * second[1]
        first_length = (first[0] ** 2 + first[1] ** 2) ** 0.5
        second_length = (second[0] ** 2 + second[1] ** 2) ** 0.5
        normalized_dot = dot / (first_length * second_length)
        relation = "same" if normalized_dot > 1e-9 else "reversed" if normalized_dot < -1e-9 else "orthogonal"
        declared = mapping.get("canonicalDirection")
        matched = None if declared == "not-applicable" else relation == declared
        canonical_endpoint_mapping = mapping.get("canonicalEndpointMapping")
        endpoint_mapping_source = mapping.get("endpointMappingSource")
        native_endpoint_mapping = (
            "start-to-start" if actual_right_wrong else "start-to-end"
        )
        endpoint_mapping_matches = (
            canonical_endpoint_mapping == native_endpoint_mapping
            and isinstance(endpoint_mapping_source, str)
            and endpoint_mapping_source in {
                "explicit", "legacy-direction", "garmentcode-default"
            }
        )
        audited.append(
            {
                "stitchId": mapping.get("stitchId"),
                "garmentCodeStitchIndex": index,
                "canonicalDirection": declared,
                "garmentCodeDirection": relation,
                "normalizedDotProduct": round(normalized_dot, 8),
                "garmentCodeRightWrong": actual_right_wrong,
                "directionMatchesCanonical": matched,
                "directionAuditStatus": (
                    "NOT_APPLICABLE" if declared == "not-applicable"
                    else "MATCH" if matched is True
                    else "MISMATCH" if matched is False
                    else "UNKNOWN"
                ),
                "canonicalEndpointMapping": canonical_endpoint_mapping,
                "endpointMappingSource": endpoint_mapping_source,
                "garmentCodeEndpointMapping": native_endpoint_mapping,
                "endpointMappingMatchesCanonical": endpoint_mapping_matches,
            }
        )

    mismatches = [item for item in audited if item["directionMatchesCanonical"] is False]
    unknowns = [
        item for item in audited
        if item["directionMatchesCanonical"] is None
        and item["canonicalDirection"] != "not-applicable"
    ]
    endpoint_mapping_mismatches = [
        item for item in audited if item["endpointMappingMatchesCanonical"] is not True
    ]
    if mismatches:
        names = ", ".join(str(item["stitchId"]) for item in mismatches)
        raise ValueError(f"GarmentCode normalized seam directions mismatch canonical graph: {names}")
    if endpoint_mapping_mismatches:
        names = ", ".join(
            str(item["stitchId"]) for item in endpoint_mapping_mismatches
        )
        raise ValueError(
            "GarmentCode seam endpoint mapping mismatch canonical graph: " + names
        )
    return {
        "status": "BLOCKED" if unknowns else "PASS",
        "source": "post-normalization GarmentCode edge geometry and native BoxMesh endpoint mapping",
        "canonicalStitchPairCount": len(mappings),
        "directionAuditedCount": len(audited),
        "directionMatchedCount": sum(
            item["directionMatchesCanonical"] is True for item in audited
        ),
        "directionNotApplicableCount": sum(
            item["canonicalDirection"] == "not-applicable" for item in audited
        ),
        "directionMismatchCount": len(mismatches),
        "directionUnknownCount": len(unknowns),
        "directionUnknownStitchIds": [item["stitchId"] for item in unknowns],
        "endpointMappingAuditedCount": len(audited),
        "endpointMappingMatchedCount": len(audited) - len(endpoint_mapping_mismatches),
        "endpointMappingMismatchCount": len(endpoint_mapping_mismatches),
        "endpointMappingMismatchStitchIds": [
            item["stitchId"] for item in endpoint_mapping_mismatches
        ],
        "assemblyConnectivityEvaluated": False,
        "seams": audited,
    }


def _rebuild_native_stitches(
    pattern: object, relative_stitch_length_tolerance: float
) -> dict[str, object]:
    """Rebuild the submitted boundary stitch graph with GarmentCode's native API."""
    import numpy as np
    from scipy.spatial.transform import Rotation
    from pygarment.garmentcode.component import Component
    from pygarment.garmentcode.interface import Interface
    from pygarment.garmentcode.edge_factory import EdgeSeqFactory
    from pygarment.garmentcode.panel import Panel

    source = pattern.pattern
    raw_panels = source.get("panels")
    raw_stitches = source.get("stitches")
    if not isinstance(raw_panels, dict) or not isinstance(raw_stitches, list):
        raise ValueError("native GarmentCode assembly requires panels and stitches")
    if (
        not math.isfinite(relative_stitch_length_tolerance)
        or relative_stitch_length_tolerance < 0
    ):
        raise ValueError("native GarmentCode stitch length tolerance is invalid")
    adapter_metadata = pattern.spec.get("parameters", {}).get("image2outfit", {})
    stitch_mappings = adapter_metadata.get("stitchMapping")
    if not isinstance(stitch_mappings, list) or len(stitch_mappings) != len(raw_stitches):
        raise ValueError("native GarmentCode assembly requires one metadata record per stitch")
    from pygarment.garmentcode.edge import CircleEdge, CurveEdge, Edge, EdgeSequence

    def make_edge(
        start: list[float], end: list[float], edge_data: dict[str, object], label: str
    ):
        curvature = edge_data.get("curvature")
        if curvature is None:
            return Edge(start, end, label=label)
        if not isinstance(curvature, dict) or not isinstance(curvature.get("params"), list):
            raise ValueError(f"native curve descriptor is invalid ({label})")
        curve_type = curvature.get("type")
        params = curvature["params"]
        if curve_type in {"quadratic", "cubic"}:
            expected_count = 1 if curve_type == "quadratic" else 2
            if len(params) != expected_count or any(
                not isinstance(point, list) or len(point) != 2 for point in params
            ):
                raise ValueError(f"native {curve_type} curve controls are invalid ({label})")
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not np.isfinite(value)
                for point in params
                for value in point
            ):
                raise ValueError(f"native {curve_type} curve controls must be finite ({label})")
            return CurveEdge(
                start,
                end,
                control_points=[[
                    float(point[0]), float(point[1])
                ] for point in params],
                relative=True,
                label=label,
            )
        if curve_type == "circle":
            if len(params) != 3:
                raise ValueError(f"native circle curve parameters are invalid ({label})")
            radius, large_arc, right = params
            if (
                isinstance(radius, bool)
                or not isinstance(radius, (int, float))
                or not np.isfinite(radius)
                or radius <= 0
                or isinstance(large_arc, bool)
                or not isinstance(large_arc, int)
                or large_arc not in (0, 1)
                or isinstance(right, bool)
                or not isinstance(right, int)
                or right not in (0, 1)
            ):
                raise ValueError(f"native circle curve parameters must be valid ({label})")
            chord_length = float(np.linalg.norm(np.asarray(end[:2]) - np.asarray(start[:2])))
            if chord_length <= 0 or float(radius) < chord_length / 2.0:
                raise ValueError(f"native circle radius is incompatible with its chord ({label})")
            relative_radius = float(radius) / chord_length
            center_offset = np.sqrt(max(0.0, relative_radius**2 - 0.25))
            sagitta = (
                relative_radius + center_offset
                if large_arc
                else relative_radius - center_offset
            )
            control_y = -float(sagitta) if right else float(sagitta)
            return CircleEdge(start, end, cy=control_y, label=label)
        raise ValueError(f"native curve type {curve_type!r} is unsupported ({label})")

    def serialized_edge_length(panel_data: dict[str, object], edge_index: int) -> float:
        vertices = panel_data.get("vertices")
        edges = panel_data.get("edges")
        if not isinstance(vertices, list) or not isinstance(edges, list):
            raise ValueError("native GarmentCode panel has no vertices or edges")
        edge_data = edges[edge_index]
        endpoints = edge_data.get("endpoints") if isinstance(edge_data, dict) else None
        if not isinstance(endpoints, list) or len(endpoints) != 2:
            raise ValueError("native GarmentCode edge has no endpoint pair")
        start_index, end_index = endpoints
        if not (
            isinstance(start_index, int)
            and isinstance(end_index, int)
            and 0 <= start_index < len(vertices)
            and 0 <= end_index < len(vertices)
        ):
            raise ValueError("native GarmentCode edge endpoint is out of range")
        label = f"{panel_data.get('label', 'panel')}.{edge_index}"
        edge = make_edge(vertices[start_index], vertices[end_index], edge_data, label)
        return float(edge.length())

    def curve_parameter_drift(
        input_curve: object, native_curve: object, label: str
    ) -> float:
        if input_curve is None or native_curve is None:
            if input_curve is native_curve:
                return 0.0
            raise ValueError(f"native GarmentCode assembly changed {label} curvature type")
        if not isinstance(input_curve, dict) or not isinstance(native_curve, dict):
            raise ValueError(f"native GarmentCode assembly returned invalid {label} curvature")
        if input_curve.get("type") != native_curve.get("type"):
            raise ValueError(f"native GarmentCode assembly changed {label} curve type")
        input_params = input_curve.get("params")
        native_params = native_curve.get("params")
        if not isinstance(input_params, list) or not isinstance(native_params, list):
            raise ValueError(f"native GarmentCode assembly returned invalid {label} parameters")
        if len(input_params) != len(native_params):
            raise ValueError(f"native GarmentCode assembly changed {label} parameter count")

        def flatten(value: object) -> list[object]:
            if isinstance(value, list):
                return [item for child in value for item in flatten(child)]
            return [value]

        drift = 0.0
        for input_value, native_value in zip(flatten(input_params), flatten(native_params)):
            if (
                isinstance(input_value, bool)
                or isinstance(native_value, bool)
                or not isinstance(input_value, (int, float))
                or not isinstance(native_value, (int, float))
                or not math.isfinite(input_value)
                or not math.isfinite(native_value)
            ):
                raise ValueError(f"native GarmentCode assembly returned invalid {label} values")
            if isinstance(input_value, int) or isinstance(native_value, int):
                if input_value != native_value:
                    raise ValueError(f"native GarmentCode assembly changed {label} flags")
            else:
                drift = max(drift, abs(float(input_value) - float(native_value)))
        return drift

    native_component = Component("image2outfit-native-stitch-assembly")
    native_panels = {}
    input_edge_lengths = {}
    for panel_name, panel_data in raw_panels.items():
        vertices = panel_data.get("vertices")
        edges = panel_data.get("edges")
        if not isinstance(vertices, list) or not isinstance(edges, list):
            raise ValueError(f"native GarmentCode panel {panel_name!r} is incomplete")
        if len(edges) != len(vertices):
            raise ValueError(f"native GarmentCode panel {panel_name!r} is not one closed loop")
        panel = Panel(panel_name, label=str(panel_data.get("label", "")))
        edge_objects = []
        boundary_pairs = []
        for edge_index, edge_data in enumerate(edges):
            if not isinstance(edge_data, dict) or set(edge_data) - {"endpoints", "curvature"}:
                raise ValueError(
                    f"native GarmentCode edge {panel_name}.{edge_index} has unsupported fields"
                )
            endpoints = edge_data.get("endpoints")
            if (
                not isinstance(endpoints, list)
                or len(endpoints) != 2
                or any(not isinstance(value, int) for value in endpoints)
                or any(not 0 <= value < len(vertices) for value in endpoints)
            ):
                raise ValueError(
                    f"native GarmentCode edge {panel_name}.{edge_index} has invalid endpoints"
                )
            start_index, end_index = endpoints
            start, end = vertices[start_index], vertices[end_index]
            boundary_pairs.append((start, end))
            edge_objects.append(
                make_edge(
                    start,
                    end,
                    edge_data,
                    f"{panel_name}.{edge_index}",
                )
            )
            input_edge_lengths[(panel_name, edge_index)] = float(
                edge_objects[-1].length()
            )
        for edge_index, (_, end) in enumerate(boundary_pairs):
            next_start = boundary_pairs[(edge_index + 1) % len(boundary_pairs)][0]
            if len(end) != 2 or len(next_start) != 2 or any(
                abs(float(end[axis]) - float(next_start[axis])) > 1e-9
                for axis in (0, 1)
            ):
                raise ValueError(
                    f"native GarmentCode panel {panel_name!r} boundary is not chained"
                )
        panel.edges = EdgeSequence(*edge_objects)
        panel.translation = np.asarray(panel_data["translation"], dtype=float)
        panel.rotation = Rotation.from_euler(
            "XYZ", panel_data["rotation"], degrees=True
        )
        if len(panel.edges) != len(edges):
            raise ValueError(f"native edge construction changed panel {panel_name!r}")
        native_panels[panel_name] = panel
        native_component.subs.append(panel)

    interface_ruffle_factors = []
    for stitch_index, pair in enumerate(raw_stitches):
        if not isinstance(pair, list) or len(pair) not in (2, 3):
            raise ValueError(f"native GarmentCode stitch {stitch_index} is malformed")
        first, second = pair[:2]
        if not isinstance(first, dict) or not isinstance(second, dict):
            raise ValueError(f"native GarmentCode stitch {stitch_index} has invalid edges")
        right_wrong = len(pair) == 3 and pair[2] == "right_wrong"
        try:
            first_panel = native_panels[first["panel"]]
            second_panel = native_panels[second["panel"]]
            first_edge = first_panel.edges[int(first["edge"])]
            second_edge = second_panel.edges[int(second["edge"])]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError(
                f"native GarmentCode stitch {stitch_index} references a missing edge"
            ) from exc
        stitch_metadata = stitch_mappings[stitch_index]
        if not isinstance(stitch_metadata, dict):
            raise ValueError(f"native GarmentCode stitch {stitch_index} metadata is invalid")
        ruffle_spec = stitch_metadata.get("garmentCodeInterfaceRuffle")
        first_ruffle = 1.0
        second_ruffle = 1.0
        if ruffle_spec is not None:
            if (
                not isinstance(ruffle_spec, dict)
                or ruffle_spec.get("side") not in {"first", "second"}
                or isinstance(ruffle_spec.get("ratio"), bool)
                or not isinstance(ruffle_spec.get("ratio"), (int, float))
                or not math.isfinite(ruffle_spec["ratio"])
                or ruffle_spec["ratio"] < 1.0
            ):
                raise ValueError(
                    f"native GarmentCode stitch {stitch_index} ruffle metadata is invalid"
                )
            if ruffle_spec["side"] == "first":
                first_ruffle = float(ruffle_spec["ratio"])
            else:
                second_ruffle = float(ruffle_spec["ratio"])
        interface_ruffle_factors.append((first_ruffle, second_ruffle))
        native_component.stitching_rules.append(
            (
                Interface(
                    first_panel,
                    first_edge,
                    ruffle=first_ruffle,
                    right_wrong=right_wrong,
                ),
                Interface(second_panel, second_edge, ruffle=second_ruffle),
            )
        )

    assembled = native_component.assembly()
    native_pattern = assembled.pattern
    native_panels_data = native_pattern.get("panels", {})
    native_stitches = native_pattern.get("stitches", [])
    if set(native_panels_data) != set(raw_panels):
        raise ValueError("native GarmentCode assembly changed the panel set")
    if len(native_stitches) != len(raw_stitches):
        raise ValueError("native GarmentCode assembly changed the stitch-pair count")

    def pair_key(pair: list[object]) -> tuple[tuple[str, int], tuple[str, int]]:
        return tuple(
            (str(endpoint["panel"]), int(endpoint["edge"]))
            for endpoint in pair[:2]
        )

    if [pair_key(pair) for pair in native_stitches] != [
        pair_key(pair) for pair in raw_stitches
    ]:
        raise ValueError("native GarmentCode assembly changed boundary stitch mappings")

    length_drifts = []
    curve_parameter_drifts = []
    for panel_name, input_panel in raw_panels.items():
        native_panel = native_panels_data[panel_name]
        if len(input_panel["edges"]) != len(native_panel["edges"]):
            raise ValueError(f"native GarmentCode assembly changed {panel_name} edge count")
        for edge_index, (input_edge, native_edge) in enumerate(
            zip(input_panel["edges"], native_panel["edges"])
        ):
            input_length = input_edge_lengths[(panel_name, edge_index)]
            native_length = serialized_edge_length(native_panel, edge_index)
            curve_parameter_drifts.append(
                curve_parameter_drift(
                    input_edge.get("curvature"),
                    native_edge.get("curvature"),
                    f"{panel_name}.{edge_index}",
                )
            )
            length_drifts.append(abs(input_length - native_length))

    seam_differences = []
    projected_seam_differences = []
    relative_seam_differences = []
    for stitch_index, pair in enumerate(native_stitches):
        first, second = pair[:2]
        first_panel = native_panels_data[first["panel"]]
        second_panel = native_panels_data[second["panel"]]
        first_length = serialized_edge_length(first_panel, int(first["edge"]))
        second_length = serialized_edge_length(second_panel, int(second["edge"]))
        first_ruffle, second_ruffle = interface_ruffle_factors[stitch_index]
        projected_first_length = first_length / first_ruffle
        projected_second_length = second_length / second_ruffle
        difference = abs(first_length - second_length)
        projected_difference = abs(projected_first_length - projected_second_length)
        seam_differences.append(difference)
        projected_seam_differences.append(projected_difference)
        relative_difference = projected_difference / max(
            projected_first_length, projected_second_length, 1e-12
        )
        relative_seam_differences.append(relative_difference)

    if assembled.is_self_intersecting():
        raise ValueError("native GarmentCode assembly produced a self-intersecting panel")
    if length_drifts and max(length_drifts) > 1e-6:
        raise ValueError("native GarmentCode assembly changed boundary edge lengths")
    if curve_parameter_drifts and max(curve_parameter_drifts) > 1e-7:
        raise ValueError("native GarmentCode assembly changed curve geometry")
    if (
        relative_seam_differences
        and max(relative_seam_differences) > relative_stitch_length_tolerance
    ):
        raise ValueError(
            "native GarmentCode assembly produced seam lengths beyond the canonical tolerance"
        )

    pattern.pattern = native_pattern
    pattern.spec["pattern"] = native_pattern
    return {
        "status": "PASS",
        "api": "Panel + Component + Interface + StitchingRule",
        "panelCount": len(native_panels_data),
        "boundaryEdgeCount": sum(
            len(panel["edges"]) for panel in native_panels_data.values()
        ),
        "canonicalStitchPairCount": len(raw_stitches),
        "nativeStitchPairCount": len(native_stitches),
        "stitchPairMappingExact": True,
        "maximumBoundaryEdgeLengthDriftCm": max(length_drifts) if length_drifts else 0.0,
        "maximumCurveParameterDrift": (
            max(curve_parameter_drifts) if curve_parameter_drifts else 0.0
        ),
        "maximumConnectedEdgeLengthDifferenceCm": (
            max(seam_differences) if seam_differences else 0.0
        ),
        "maximumProjectedConnectedEdgeLengthDifferenceCm": (
            max(projected_seam_differences) if projected_seam_differences else 0.0
        ),
        "maximumRelativeConnectedEdgeLengthDifference": (
            max(relative_seam_differences) if relative_seam_differences else 0.0
        ),
        "relativeStitchLengthTolerance": relative_stitch_length_tolerance,
        "selfIntersection": False,
        "threeDGenerated": False,
    }

def main() -> int:
    args = parse_args()
    actual_python = sys.version.split()[0]
    if actual_python != args.python_version:
        raise RuntimeError(
            f"expected Python {args.python_version}, found {actual_python}"
        )
    requirements_lock_sha256 = _validate_locked_packages(
        args.requirements_lock.resolve()
    )
    upstream_root = args.upstream_root.resolve()
    revision = subprocess.run(
        ["git", "-C", str(upstream_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if revision != args.upstream_revision:
        raise RuntimeError(
            f"expected GarmentCode revision {args.upstream_revision}, found {revision}"
        )
    setup_cfg = (upstream_root / "setup.cfg").read_text(encoding="utf-8")
    version_match = re.search(r"(?m)^version\s*=\s*([^\s]+)\s*$", setup_cfg)
    if not version_match or version_match.group(1) != args.pygarment_version:
        raise RuntimeError("PyGarment version does not match the runtime lock")

    sys.path.insert(0, str(upstream_root))
    from pygarment.pattern.wrappers import VisPattern  # noqa: PLC0415

    input_path = args.input.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    pattern = VisPattern(str(input_path))
    if not pattern.pattern.get("panels"):
        raise ValueError("GarmentCode received no panels")
    adapter_metadata = pattern.spec.get("parameters", {}).get("image2outfit", {})
    native_stitch_assembly = {
        "status": "NOT_RUN",
        "api": "Panel + Component + Interface + StitchingRule",
        "threeDGenerated": False,
    }
    if args.stitch_export_mode == "strict-boundary-edges":
        relative_stitch_length_tolerance = adapter_metadata.get(
            "relativeStitchLengthTolerance"
        )
        if (
            isinstance(relative_stitch_length_tolerance, bool)
            or not isinstance(relative_stitch_length_tolerance, (int, float))
        ):
            raise ValueError(
                "strict GarmentCode stitch export requires the canonical relative seam tolerance"
            )
        native_stitch_assembly = _rebuild_native_stitches(
            pattern, float(relative_stitch_length_tolerance)
        )
    if pattern.is_self_intersecting():
        raise ValueError("GarmentCode detected a self-intersecting pattern panel")
    stitch_count = len(pattern.pattern.get("stitches", []))
    canonical_stitch_count = int(adapter_metadata.get("canonicalStitchCount", 0))
    stitches_submitted = bool(
        adapter_metadata.get("stitchesSubmittedToGarmentCode", False)
    )
    if args.stitch_export_mode == "strict-boundary-edges" and (
        not stitches_submitted or stitch_count != canonical_stitch_count
    ):
        raise ValueError(
            "strict GarmentCode stitch export did not preserve every canonical pair"
        )
    orientation_audit = (
        _audit_stitch_orientations(pattern.pattern, adapter_metadata)
        if args.stitch_export_mode == "strict-boundary-edges"
        else {
            "status": "NOT_RUN",
            "source": "post-normalization GarmentCode 2D panel geometry",
            "canonicalStitchPairCount": 0,
            "directionAuditedCount": 0,
            "directionMatchedCount": 0,
            "directionMismatchCount": 0,
            "assemblyConnectivityEvaluated": False,
            "seams": [],
        }
    )

    specification = output_dir / "garmentcode-pattern-specification.json"
    layout_svg = output_dir / "garmentcode-pattern-layout.svg"
    layout_png = output_dir / "garmentcode-pattern-layout.png"
    layout_pdf = output_dir / "garmentcode-pattern-layout.pdf"
    _write_json(specification, pattern.pattern)
    drawing = pattern.get_svg(
        str(layout_svg),
        with_text=False,
        view_ids=False,
        flat=True,
        fill_panels=True,
        margin=2,
    )
    drawing.save(pretty=True)
    import cairosvg  # noqa: PLC0415

    cairosvg.svg2png(
        url=str(layout_svg),
        write_to=str(layout_png),
        output_width=1800,
    )
    cairosvg.svg2pdf(
        url=str(layout_svg),
        write_to=str(layout_pdf),
        dpi=2.54 * pattern.px_per_unit,
    )

    outputs = [specification, layout_svg, layout_png, layout_pdf]
    if not all(path.is_file() and path.stat().st_size > 0 for path in outputs):
        raise FileNotFoundError(
            "GarmentCode did not produce every required 2D artifact"
        )
    record = {
        "schemaVersion": 1,
        "upstreamRevision": revision,
        "pythonVersion": actual_python,
        "pygarmentVersion": args.pygarment_version,
        "requirementsLockSha256": requirements_lock_sha256,
        "panelCount": len(pattern.pattern["panels"]),
        "selfIntersection": False,
        "threeDGenerated": False,
        "stitchExportMode": args.stitch_export_mode,
        "canonicalStitchCount": canonical_stitch_count,
        "stitchCount": stitch_count,
        "stitchesSubmittedToGarmentCode": stitches_submitted,
        "seamOrientationAudit": orientation_audit,
        "nativeStitchAssembly": native_stitch_assembly,
        "outputs": [path.name for path in outputs],
    }
    _write_json(output_dir / "garmentcode-run.json", record)
    print(json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
