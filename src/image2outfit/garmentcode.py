"""Dependency-free Stage 04 interoperability with GarmentCode/PyGarment JSON.

GarmentCode itself is intentionally not a production dependency of image2outfit.
The external runtime remains isolated; this module only owns deterministic exchange.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from .construction import DEFAULT_RELATIVE_LENGTH_TOLERANCE
from .curves import curve_length, normalize_curvature, reverse_curvature, scale_curvature
from .pattern_stage import PatternHypothesis
from .stitch_mapping import resolve_endpoint_mapping


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

GARMENTCODE_PATTERN_TOOL = "pattern.garmentcode-2d"


def _canonical_curvature(edge: dict[str, Any], label: str) -> dict[str, Any] | None:
    raw = edge.get("curvature")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"{label} curvature must be an object")
    return normalize_curvature(raw, label)


def _reverse_curvature(curvature: dict[str, Any]) -> dict[str, Any]:
    return reverse_curvature(curvature)


def _curve_length_m(
    start: list[float], end: list[float], curvature: dict[str, Any]
) -> float:
    return curve_length(
        (float(start[0]), float(start[1])),
        (float(end[0]), float(end[1])),
        curvature,
    )


def _garmentcode_interface_ruffle(stitch: dict[str, Any]) -> dict[str, Any] | None:
    value = stitch.get("garmentCodeInterfaceRuffle")
    if value is None:
        return None
    if not isinstance(value, dict) or value.get("side") not in {"first", "second"}:
        raise ValueError("garmentCodeInterfaceRuffle requires side first or second")
    ratio = value.get("ratio")
    source = value.get("source")
    if (
        isinstance(ratio, bool)
        or not isinstance(ratio, (int, float))
        or not math.isfinite(ratio)
        or ratio < 1.0
    ):
        raise ValueError("garmentCodeInterfaceRuffle ratio must be finite and at least one")
    if (
        not isinstance(source, dict)
        or not isinstance(source.get("path"), str)
        or not source["path"]
        or not isinstance(source.get("field"), str)
        or not source["field"]
        or not isinstance(source.get("sha256"), str)
        or len(source["sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in source["sha256"])
    ):
        raise ValueError("garmentCodeInterfaceRuffle requires a source path, field, and SHA-256")
    return {"side": value["side"], "ratio": float(ratio), "source": dict(source)}


def pattern_contract_to_garmentcode_preview(
    pattern: dict[str, Any],
    stitch_graph: dict[str, Any],
    *,
    pattern_sha256: str,
    stitch_graph_sha256: str,
    stitch_export_mode: str = "preview-only",
) -> dict[str, Any]:
    """Project canonical panel boundaries into GarmentCode's 2D preview format.

    GarmentCode's basic pattern format addresses one boundary segment per edge.
    Strict stitch export therefore requires every referenced canonical edge to
    resolve to exactly one boundary segment. The compatibility preview mode keeps
    the prior panel-only behavior and makes that limitation explicit.
    """

    if pattern.get("units") != "meter":
        raise ValueError("GarmentCode preview requires pattern units in meters")
    pieces = pattern.get("pieces")
    stitches = stitch_graph.get("stitches")
    if not isinstance(pieces, list) or not pieces:
        raise ValueError("GarmentCode preview requires canonical pattern pieces")
    if not isinstance(stitches, list):
        raise ValueError("GarmentCode preview requires a canonical stitch graph")
    if stitch_export_mode not in {"preview-only", "strict-boundary-edges"}:
        raise ValueError(
            f"unsupported GarmentCode stitch export mode: {stitch_export_mode}"
        )

    ordered_pieces = sorted(pieces, key=lambda item: str(item["pieceId"]))
    panels: dict[str, dict[str, Any]] = {}
    panel_key_map: dict[str, str] = {}
    named_edges: dict[str, list[dict[str, Any]]] = {}
    edge_indices_by_piece: dict[str, dict[str, int]] = {}
    edge_lengths_by_piece: dict[str, dict[str, float]] = {}
    curvature_by_edge: dict[tuple[str, str], dict[str, Any]] = {}
    curved_boundary_edges: list[dict[str, Any]] = []
    layout_rows: dict[str, int] = {}
    row_widths = [0.0, 0.0]
    row_by_piece: dict[str, int] = {}
    for piece in sorted(
        ordered_pieces,
        key=lambda item: (
            -(
                max(float(point[0]) for point in item["boundary"])
                - min(float(point[0]) for point in item["boundary"])
            ),
            str(item["pieceId"]),
        ),
    ):
        piece_id = str(piece["pieceId"])
        row = 0 if row_widths[0] <= row_widths[1] else 1
        boundary_x = [float(point[0]) for point in piece["boundary"]]
        row_widths[row] += max(boundary_x) - min(boundary_x)
        row_by_piece[piece_id] = row

    for index, piece in enumerate(ordered_pieces, start=1):
        panel_key = f"P{index:02d}"
        piece_id = str(piece["pieceId"])
        boundary = piece["boundary"]
        if not isinstance(boundary, list) or len(boundary) < 3:
            raise ValueError(f"pattern piece {piece_id!r} has an invalid boundary")
        panel_edges = [
            {"endpoints": [edge_index, (edge_index + 1) % len(boundary)]}
            for edge_index in range(len(boundary))
        ]
        panels[panel_key] = {
            "translation": [0.0, 0.0, -1.0 if row_by_piece[piece_id] == 0 else 0.0],
            "rotation": [0.0, 0.0, 0.0],
            "vertices": [[float(x) * 100.0, float(y) * 100.0] for x, y in boundary],
            "edges": panel_edges,
        }
        panel_key_map[panel_key] = piece_id
        layout_rows[panel_key] = row_by_piece[piece_id]
        named_edges[panel_key] = [
            {
                "edgeId": str(edge["edgeId"]),
                "startVertex": int(edge["startVertex"]),
                "endVertex": int(edge["endVertex"]),
            }
            for edge in piece.get("edges", [])
        ]
        vertex_count = len(boundary)
        edge_indices_by_piece[piece_id] = {}
        edge_lengths_by_piece[piece_id] = {}
        for edge in piece.get("edges", []):
            edge_id = str(edge["edgeId"])
            start = int(edge["startVertex"])
            end = int(edge["endVertex"])
            start_point = boundary[start]
            end_point = boundary[end]
            curvature = _canonical_curvature(
                edge, f"pattern edge {piece_id}.{edge_id}"
            )
            edge_key = (piece_id, edge_id)
            if curvature is not None:
                curvature_by_edge[edge_key] = curvature
            forward = (end - start) % vertex_count
            if forward == 1:
                edge_index = start
            elif forward == vertex_count - 1:
                edge_index = end
            else:
                edge_index = -1
            edge_indices_by_piece[piece_id][edge_id] = edge_index
            if curvature is not None:
                if edge_index < 0:
                    raise ValueError(
                        f"curved edge {piece_id}.{edge_id} spans multiple boundary "
                        "segments and cannot be represented by one GarmentCode edge"
                    )
                oriented_curvature = (
                    _reverse_curvature(curvature)
                    if forward == vertex_count - 1
                    else curvature
                )
                garmentcode_curvature = scale_curvature(oriented_curvature, 100.0)
                if "curvature" in panel_edges[edge_index]:
                    raise ValueError(
                        f"multiple canonical curves map to {piece_id} boundary segment "
                        f"{edge_index}"
                    )
                panel_edges[edge_index]["curvature"] = garmentcode_curvature
                arc_length = _curve_length_m(
                    [float(start_point[0]), float(start_point[1])],
                    [float(end_point[0]), float(end_point[1])],
                    curvature,
                )
                curved_boundary_edges.append(
                    {
                        "pieceId": piece_id,
                        "edgeId": edge_id,
                        "panel": panel_key,
                        "edgeIndex": edge_index,
                        "orientationReversedForBoundaryLoop": forward
                        == vertex_count - 1,
                        "chordLengthM": math.hypot(
                            float(end_point[0]) - float(start_point[0]),
                            float(end_point[1]) - float(start_point[1]),
                        ),
                        "curveType": curvature["type"],
                        "curveLengthM": arc_length,
                        "quadraticArcLengthM": (
                            arc_length if curvature["type"] == "quadratic" else None
                        ),
                    }
                )
                edge_lengths_by_piece[piece_id][edge_id] = arc_length
            else:
                edge_lengths_by_piece[piece_id][edge_id] = math.hypot(
                    float(end_point[0]) - float(start_point[0]),
                    float(end_point[1]) - float(start_point[1]),
                )

    exported_stitches: list[list[dict[str, str | int] | str]] = []
    stitch_mapping: list[dict[str, Any]] = []
    if stitch_export_mode == "strict-boundary-edges":
        for stitch in sorted(stitches, key=lambda item: str(item.get("stitchId", ""))):
            stitch_id = str(stitch.get("stitchId", ""))
            pair: list[dict[str, str | int]] = []
            mapped_edges: list[dict[str, str | int]] = []
            for side in ("first", "second"):
                endpoint = stitch.get(side)
                if not isinstance(endpoint, dict):
                    raise ValueError(f"stitch {stitch_id!r} has no {side} endpoint")
                piece_id = str(endpoint.get("pieceId", ""))
                edge_id = str(endpoint.get("edgeId", ""))
                panel_key = next(
                    (key for key, value in panel_key_map.items() if value == piece_id),
                    None,
                )
                edge_index = edge_indices_by_piece.get(piece_id, {}).get(edge_id)
                if panel_key is None or edge_index is None:
                    raise ValueError(
                        f"stitch {stitch_id!r} references unknown GarmentCode edge "
                        f"{piece_id}.{edge_id}"
                    )
                if edge_index < 0:
                    raise ValueError(
                        f"stitch {stitch_id!r} edge {piece_id}.{edge_id} spans "
                        "multiple boundary segments; strict GarmentCode export only "
                        "supports one-to-one boundary edges"
                    )
                reference = {"panel": panel_key, "edge": edge_index}
                pair.append(reference)
                mapped_edges.append(
                    {
                        "pieceId": piece_id,
                        "edgeId": edge_id,
                        "edgeIndex": edge_index,
                        "edgeLengthM": edge_lengths_by_piece[piece_id][edge_id],
                    }
                )
            direction = stitch.get("direction")
            endpoint_mapping, endpoint_mapping_source = resolve_endpoint_mapping(
                stitch
            )
            right_wrong = endpoint_mapping == "start-to-start"
            if right_wrong:
                # BoxMesh's explicit tag selects start-to-start pairing;
                # flat-edge direction remains a separate canonical audit.
                pair.append("right_wrong")
            exported_stitches.append(pair)
            first_length = float(mapped_edges[0]["edgeLengthM"])
            second_length = float(mapped_edges[1]["edgeLengthM"])
            curved_sides = [
                (str(edge["pieceId"]), str(edge["edgeId"])) in curvature_by_edge
                for edge in mapped_edges
            ]
            easing = stitch.get("easingRatio", 1.0)
            if (
                isinstance(easing, bool)
                or not isinstance(easing, (int, float))
                or not math.isfinite(easing)
                or easing <= 0
            ):
                raise ValueError(
                    f"stitch {stitch_id!r} easingRatio must be finite and positive"
                )
            interface_ruffle = _garmentcode_interface_ruffle(stitch)
            first_ruffle = (
                interface_ruffle["ratio"]
                if interface_ruffle and interface_ruffle["side"] == "first"
                else 1.0
            )
            second_ruffle = (
                interface_ruffle["ratio"]
                if interface_ruffle and interface_ruffle["side"] == "second"
                else 1.0
            )
            projected_first_length = first_length / first_ruffle
            projected_second_length = second_length / second_ruffle * float(easing)
            denominator = max(projected_first_length, projected_second_length, 1e-12)
            relative_discrepancy = abs(projected_first_length - projected_second_length) / denominator
            seam_curve_audit: dict[str, Any] = {
                "status": "NOT_APPLICABLE",
                "curvedEdges": 0,
            }
            if any(curved_sides):
                curve_parameters_match: bool | None = None
                curve_types: list[str | None] = []
                if all(curved_sides):
                    first_key = (
                        str(mapped_edges[0]["pieceId"]),
                        str(mapped_edges[0]["edgeId"]),
                    )
                    second_key = (
                        str(mapped_edges[1]["pieceId"]),
                        str(mapped_edges[1]["edgeId"]),
                    )
                    first_curve = curvature_by_edge[first_key]
                    second_curve = curvature_by_edge[second_key]
                    comparable_second = (
                        second_curve
                        if endpoint_mapping == "start-to-start"
                        else _reverse_curvature(second_curve)
                        if endpoint_mapping == "start-to-end"
                        else None
                    )
                    if comparable_second is None:
                        raise ValueError(
                            f"stitch {stitch_id!r} has unsupported curve endpoint mapping"
                        )
                    curve_parameters_match = (
                        first_curve["type"] == comparable_second["type"]
                        and len(first_curve["params"]) == len(comparable_second["params"])
                    )
                    if curve_parameters_match:
                        curve_parameters_match = all(
                            math.isclose(
                                float(left), float(right), rel_tol=0.0, abs_tol=1e-6
                            )
                            for first_param, second_param in zip(
                                first_curve["params"], comparable_second["params"]
                            )
                            for left, right in zip(
                                first_param if isinstance(first_param, list) else [first_param],
                                second_param if isinstance(second_param, list) else [second_param],
                            )
                        )
                    curve_types = [first_curve["type"], second_curve["type"]]
                else:
                    curve_types = [
                        curvature_by_edge[
                            (str(edge["pieceId"]), str(edge["edgeId"]))
                        ]["type"]
                        if is_curved
                        else None
                        for edge, is_curved in zip(mapped_edges, curved_sides)
                    ]
                seam_curve_audit = {
                    "status": "PASS",
                    "curvedEdges": sum(curved_sides),
                    "curveTypes": curve_types,
                    "curveParametersMatchEndpointMapping": curve_parameters_match,
                    "parameterEqualityRequiredForStitchExport": False,
                    "lengthCompatibilityStatus": (
                        "PASS"
                        if relative_discrepancy <= DEFAULT_RELATIVE_LENGTH_TOLERANCE
                        else "FAIL"
                    ),
                    "projectedFirstLengthM": projected_first_length,
                    "projectedSecondLengthM": projected_second_length,
                    "relativeLengthDiscrepancy": relative_discrepancy,
                    "relativeLengthTolerance": DEFAULT_RELATIVE_LENGTH_TOLERANCE,
                }
            stitch_mapping.append(
                {
                    "stitchId": stitch_id,
                    "garmentCodeStitchIndex": len(exported_stitches) - 1,
                    "edges": mapped_edges,
                    "canonicalDirection": stitch.get("direction"),
                    "canonicalEndpointMapping": endpoint_mapping,
                    "endpointMappingSource": endpoint_mapping_source,
                    "garmentCodeRightWrong": right_wrong,
                    "canonicalType": stitch.get("type"),
                    "canonicalEasingRatio": stitch.get("easingRatio", 1.0),
                    "garmentCodeInterfaceRuffle": interface_ruffle,
                    "seamLengthAudit": {
                        "firstEdgeLengthM": first_length,
                        "secondEdgeLengthM": second_length,
                        "signedDifferenceMm": round(
                            (second_length - first_length) * 1000.0, 3
                        ),
                        "absoluteDifferenceMm": round(
                            abs(second_length - first_length) * 1000.0, 3
                        ),
                        "secondToFirstRatio": (
                            second_length / first_length if first_length > 0 else None
                        ),
                        "projectedFirstEdgeLengthM": projected_first_length,
                        "projectedSecondEdgeLengthM": projected_second_length,
                        "relativeDiscrepancyAfterEase": relative_discrepancy,
                    },
                    "seamCurveAudit": seam_curve_audit,
                }
            )

    return {
        "pattern": {
            "panels": panels,
            "stitches": exported_stitches,
            "panel_order": list(panels),
        },
        "parameters": {
            "image2outfit": {
                "productId": str(pattern["productId"]),
                "patternContractSha256": pattern_sha256,
                "stitchGraphSha256": stitch_graph_sha256,
                "canonicalStitchCount": len(stitches),
                "relativeStitchLengthTolerance": DEFAULT_RELATIVE_LENGTH_TOLERANCE,
                "curvedBoundaryEdges": curved_boundary_edges,
                "curvedStitchCount": sum(
                    item["seamCurveAudit"]["status"] == "PASS"
                    for item in stitch_mapping
                ),
                "stitchExportMode": stitch_export_mode,
                "stitchesSubmittedToGarmentCode": stitch_export_mode
                == "strict-boundary-edges",
                "stitchMapping": stitch_mapping,
                "canonicalStitches": stitches,
                "panelKeyMap": panel_key_map,
                "layoutRows": layout_rows,
                "namedEdges": named_edges,
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


def audit_stitch_graph_connectivity(
    pattern: dict[str, Any], stitch_graph: dict[str, Any]
) -> dict[str, Any]:
    """Summarize panel-level stitch connectivity without claiming physical assembly.

    The audit treats each pattern piece as a graph node and each canonical stitch
    pair as an undirected connection. A stitch joining two edges on the same panel
    is retained as a self-loop so closed bands remain distinguishable from loose
    panels. GarmentCode's 2D preview does not evaluate 3D assembly connectivity.
    """

    pieces = pattern.get("pieces")
    stitches = stitch_graph.get("stitches")
    if not isinstance(pieces, list) or not isinstance(stitches, list):
        raise ValueError("connectivity audit requires canonical pieces and stitches")

    piece_parts: dict[str, str] = {}
    adjacency: dict[str, set[str]] = {}
    incident_stitches: dict[str, list[str]] = {}
    for piece in pieces:
        if not isinstance(piece, dict):
            raise ValueError("connectivity audit found an invalid pattern piece")
        piece_id = piece.get("pieceId")
        part_id = piece.get("partId")
        if not isinstance(piece_id, str) or not piece_id:
            raise ValueError("connectivity audit found a piece without pieceId")
        if piece_id in adjacency:
            raise ValueError(f"connectivity audit found duplicate pieceId {piece_id!r}")
        if not isinstance(part_id, str) or not part_id:
            raise ValueError(f"connectivity audit found no partId for {piece_id!r}")
        piece_parts[piece_id] = part_id
        adjacency[piece_id] = set()
        incident_stitches[piece_id] = []

    seen_stitches: set[str] = set()
    self_loop_stitches: list[str] = []
    for stitch in stitches:
        if not isinstance(stitch, dict):
            raise ValueError("connectivity audit found an invalid stitch")
        stitch_id = stitch.get("stitchId")
        first = stitch.get("first")
        second = stitch.get("second")
        if not isinstance(stitch_id, str) or not stitch_id:
            raise ValueError("connectivity audit found a stitch without stitchId")
        if stitch_id in seen_stitches:
            raise ValueError(f"connectivity audit found duplicate stitchId {stitch_id!r}")
        if not isinstance(first, dict) or not isinstance(second, dict):
            raise ValueError(f"connectivity audit found incomplete pair {stitch_id!r}")
        first_piece = first.get("pieceId")
        second_piece = second.get("pieceId")
        if not isinstance(first_piece, str) or not isinstance(second_piece, str):
            raise ValueError(f"connectivity audit found invalid panel ids in {stitch_id!r}")
        if first_piece not in adjacency or second_piece not in adjacency:
            raise ValueError(f"connectivity audit found unknown piece in {stitch_id!r}")
        seen_stitches.add(stitch_id)
        incident_stitches[first_piece].append(stitch_id)
        if second_piece != first_piece:
            incident_stitches[second_piece].append(stitch_id)
            adjacency[first_piece].add(second_piece)
            adjacency[second_piece].add(first_piece)
        else:
            self_loop_stitches.append(stitch_id)

    components: list[dict[str, Any]] = []
    unseen = set(adjacency)
    while unseen:
        seed = min(unseen)
        stack = [seed]
        members: set[str] = set()
        while stack:
            piece_id = stack.pop()
            if piece_id in members:
                continue
            members.add(piece_id)
            unseen.discard(piece_id)
            stack.extend(sorted(adjacency[piece_id] - members, reverse=True))
        member_stitches = sorted(
            {stitch_id for piece_id in members for stitch_id in incident_stitches[piece_id]}
        )
        components.append(
            {
                "componentId": f"panel-component-{len(components) + 1:02d}",
                "pieceIds": sorted(members),
                "partIds": sorted({piece_parts[piece_id] for piece_id in members}),
                "stitchIds": member_stitches,
                "panelCount": len(members),
                "stitchCount": len(member_stitches),
            }
        )

    unstitched = sorted(
        piece_id for piece_id, stitch_ids in incident_stitches.items() if not stitch_ids
    )
    return {
        "auditType": "canonical-panel-stitch-connectivity",
        "status": "COMPUTED",
        "panelConnectivityEvaluated": True,
        "physicalAssemblyEvaluated": False,
        "inputPanelCount": len(adjacency),
        "inputStitchCount": len(seen_stitches),
        "componentCount": len(components),
        "components": components,
        "unstitchedPanelIds": unstitched,
        "selfLoopStitchIds": sorted(self_loop_stitches),
        "crossPartStitchCount": sum(
            piece_parts[stitch["first"]["pieceId"]]
            != piece_parts[stitch["second"]["pieceId"]]
            for stitch in stitches
        ),
        "evaluationLimit": (
            "Panel graph connectivity only; this does not evaluate sewing, 3D assembly, "
            "fit, collision, or appearance."
        ),
    }


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

    return (
        json.dumps(
            pattern_hypothesis_to_garmentcode(hypothesis),
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


@dataclass(frozen=True, slots=True)
class GarmentCodeNativePatternImport:
    """Lossless snapshot of a native BasicPattern plus its semantic group map.

    Native curves and panel transforms are kept in ``document``. The separate
    projection function converts panel curves and stitches into canonical
    contracts without treating them as a product pattern.
    """

    document: dict[str, Any]
    panel_order: tuple[str, ...]
    canonical_piece_ids: dict[str, str]
    semantic_panel_groups: dict[str, str]
    connectivity_audit: dict[str, Any]
    document_sha256: str
    panel_stitch_graph_sha256: str
    canonical_projection_status: str
    native_curve_types: dict[str, int]


def import_garmentcode_native_pattern(
    document: str | dict[str, Any],
    *,
    semantic_panel_groups: dict[str, str],
) -> GarmentCodeNativePatternImport:
    """Validate and import native GarmentCode panels/stitches without flattening.

    ``semantic_panel_groups`` must explicitly map each native panel name to its
    image2outfit semantic group. Native panel ids, edge indices, transforms,
    curve descriptors, stitch order, and optional stitch tags remain unchanged.
    """

    import hashlib
    import re

    if isinstance(document, str):
        try:
            raw_document = json.loads(document)
        except json.JSONDecodeError as exc:
            raise ValueError("native GarmentCode document is not valid JSON") from exc
    elif isinstance(document, dict):
        raw_document = json.loads(json.dumps(document, ensure_ascii=False))
    else:
        raise ValueError("native GarmentCode document must be JSON text or an object")

    if not isinstance(raw_document, dict):
        raise ValueError("native GarmentCode document root must be an object")
    pattern = raw_document.get("pattern")
    properties = raw_document.get("properties")
    if not isinstance(pattern, dict) or not isinstance(properties, dict):
        raise ValueError("native GarmentCode document requires pattern and properties")
    panels = pattern.get("panels")
    stitches = pattern.get("stitches")
    panel_order = pattern.get("panel_order")
    if not isinstance(panels, dict) or not panels:
        raise ValueError("native GarmentCode pattern requires panels")
    if not isinstance(stitches, list):
        raise ValueError("native GarmentCode pattern requires a stitch list")
    if (
        not isinstance(panel_order, list)
        or any(not isinstance(item, str) for item in panel_order)
        or len(panel_order) != len(set(panel_order))
        or set(panel_order) != set(panels)
    ):
        raise ValueError("native GarmentCode panel_order must enumerate every panel once")

    units_in_meter = properties.get("units_in_meter")
    if (
        isinstance(units_in_meter, bool)
        or not isinstance(units_in_meter, (int, float))
        or not math.isfinite(units_in_meter)
        or units_in_meter <= 0
    ):
        raise ValueError("native GarmentCode units_in_meter must be finite and positive")

    native_panel_ids = set(panels)
    if any(not isinstance(panel_id, str) or not panel_id for panel_id in native_panel_ids):
        raise ValueError("native GarmentCode panel ids must be non-empty strings")
    if set(semantic_panel_groups) != native_panel_ids:
        missing = sorted(native_panel_ids.difference(semantic_panel_groups))
        extra = sorted(set(semantic_panel_groups).difference(native_panel_ids))
        raise ValueError(
            "semantic panel groups must map every native panel exactly once; "
            f"missing={missing}, extra={extra}"
        )
    if any(not isinstance(group, str) or not group.strip() for group in semantic_panel_groups.values()):
        raise ValueError("semantic panel groups must be non-empty strings")

    canonical_piece_ids = {
        panel_id: f"gc-{panel_id.lower().replace('_', '-')}"
        for panel_id in native_panel_ids
    }
    if len(set(canonical_piece_ids.values())) != len(canonical_piece_ids):
        raise ValueError("native panel ids collide after canonical piece-id conversion")
    if any(not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", piece_id)
           for piece_id in canonical_piece_ids.values()):
        raise ValueError("native panel ids cannot be converted to canonical identifiers")

    curve_types: dict[str, int] = {}
    for panel_id, panel in panels.items():
        if not isinstance(panel, dict):
            raise ValueError(f"native panel {panel_id!r} must be an object")
        vertices = panel.get("vertices")
        edges = panel.get("edges")
        if not isinstance(vertices, list) or len(vertices) < 3:
            raise ValueError(f"native panel {panel_id!r} needs at least three vertices")
        if not isinstance(edges, list) or len(edges) < 3:
            raise ValueError(f"native panel {panel_id!r} needs at least three edges")
        for vertex_index, vertex in enumerate(vertices):
            if (
                not isinstance(vertex, list)
                or len(vertex) != 2
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    for value in vertex
                )
            ):
                raise ValueError(
                    f"native panel {panel_id!r} has invalid vertex {vertex_index}"
                )
        for edge_index, edge in enumerate(edges):
            endpoints = edge.get("endpoints") if isinstance(edge, dict) else None
            if (
                not isinstance(endpoints, list)
                or len(endpoints) != 2
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or value < 0
                    or value >= len(vertices)
                    for value in endpoints
                )
                or endpoints[0] == endpoints[1]
            ):
                raise ValueError(
                    f"native panel {panel_id!r} has invalid edge endpoints at {edge_index}"
                )
            curvature = edge.get("curvature")
            if curvature is not None:
                if not isinstance(curvature, dict) or not isinstance(
                    curvature.get("type"), str
                ):
                    raise ValueError(
                        f"native panel {panel_id!r} has an invalid curve descriptor"
                    )
                curve_type = curvature["type"]
                curve_types[curve_type] = curve_types.get(curve_type, 0) + 1

    graph_stitches: list[dict[str, Any]] = []
    for stitch_index, stitch in enumerate(stitches):
        if not isinstance(stitch, list) or len(stitch) < 2:
            raise ValueError(f"native stitch {stitch_index} must contain an edge pair")
        endpoints: list[dict[str, Any]] = []
        for side in stitch[:2]:
            if not isinstance(side, dict):
                raise ValueError(f"native stitch {stitch_index} contains an invalid edge ref")
            panel_id = side.get("panel")
            edge_index = side.get("edge")
            if panel_id not in panels:
                raise ValueError(
                    f"native stitch {stitch_index} references unknown panel {panel_id!r}"
                )
            panel_edges = panels[panel_id].get("edges")
            if (
                isinstance(edge_index, bool)
                or not isinstance(edge_index, int)
                or edge_index < 0
                or edge_index >= len(panel_edges)
            ):
                raise ValueError(
                    f"native stitch {stitch_index} references invalid edge on {panel_id!r}"
                )
            endpoints.append({"pieceId": panel_id, "edgeIndex": edge_index})
        graph_stitches.append(
            {
                "stitchId": f"garmentcode-stitch-{stitch_index + 1:04d}",
                "first": endpoints[0],
                "second": endpoints[1],
            }
        )

    connectivity_audit = audit_stitch_graph_connectivity(
        {
            "pieces": [
                {"pieceId": panel_id, "partId": semantic_panel_groups[panel_id]}
                for panel_id in panel_order
            ]
        },
        {"stitches": graph_stitches},
    )

    def _digest(value: Any) -> str:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    panel_stitch_payload = {
        "panelOrder": panel_order,
        "panels": panels,
        "stitches": stitches,
        "unitsInMeter": units_in_meter,
    }
    return GarmentCodeNativePatternImport(
        document=raw_document,
        panel_order=tuple(panel_order),
        canonical_piece_ids=canonical_piece_ids,
        semantic_panel_groups=dict(semantic_panel_groups),
        connectivity_audit=connectivity_audit,
        document_sha256=_digest(raw_document),
        panel_stitch_graph_sha256=_digest(panel_stitch_payload),
        canonical_projection_status=(
            "CURVE_PRIMITIVES_PROJECTABLE" if curve_types else "POLYGON_ONLY"
        ),
        native_curve_types=curve_types,
    )


def garmentcode_native_pattern_to_contract(
    imported: GarmentCodeNativePatternImport,
    *,
    product_id: str,
    interface_ruffle_rules: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Project native panels and stitches into local canonical-shaped contracts.

    This adapter preserves panel-local boundary vertices, native edge indexing,
    semantic group assignments, and curve primitives. It creates exchange
    contracts for validation and round-trip comparison only; it does not approve
    product replacement or physical assembly.
    """
    if not isinstance(product_id, str) or not product_id:
        raise ValueError("product_id must be a non-empty string")
    native = imported.document
    pattern = native["pattern"]
    panels = pattern["panels"]
    units_in_meter = float(native["properties"]["units_in_meter"])
    ruffle_rules: dict[tuple[str, str], dict[str, Any]] = {}
    for rule in interface_ruffle_rules or []:
        if not isinstance(rule, dict):
            raise ValueError("GarmentCode ruffle rules must be objects")
        interface_group = rule.get("interfacePartId")
        peer_group = rule.get("peerPartId")
        ratio = rule.get("ratio")
        source = rule.get("source")
        if (
            not isinstance(interface_group, str)
            or not interface_group
            or not isinstance(peer_group, str)
            or not peer_group
            or interface_group == peer_group
        ):
            raise ValueError("GarmentCode ruffle rules require distinct part groups")
        if (
            isinstance(ratio, bool)
            or not isinstance(ratio, (int, float))
            or not math.isfinite(ratio)
            or ratio < 1.0
        ):
            raise ValueError("GarmentCode ruffle rule ratio must be finite and at least one")
        if (
            not isinstance(source, dict)
            or not isinstance(source.get("path"), str)
            or not source["path"]
            or not isinstance(source.get("field"), str)
            or not source["field"]
            or not isinstance(source.get("sha256"), str)
            or len(source["sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in source["sha256"])
        ):
            raise ValueError("GarmentCode ruffle rule requires source path, field, and SHA-256")
        key = (interface_group, peer_group)
        if key in ruffle_rules:
            raise ValueError(f"duplicate GarmentCode ruffle rule for {key!r}")
        ruffle_rules[key] = {
            "ratio": float(ratio),
            "source": dict(source),
        }
    edge_ids: dict[tuple[str, int], str] = {}
    edge_usage: dict[tuple[str, int], int] = {}
    for panel_id, panel in panels.items():
        for edge_index, _ in enumerate(panel["edges"]):
            edge_ids[(panel_id, edge_index)] = f"edge-{edge_index + 1:03d}"
            edge_usage[(panel_id, edge_index)] = 0

    native_stitches: list[tuple[list[dict[str, Any]], list[str]]] = []
    for stitch_index, raw_stitch in enumerate(pattern["stitches"]):
        references = raw_stitch[:2]
        tags = [tag for tag in raw_stitch[2:] if isinstance(tag, str)]
        for reference in references:
            key = (reference["panel"], reference["edge"])
            edge_usage[key] += 1
        native_stitches.append((references, tags))

    contract_pieces: list[dict[str, Any]] = []
    for panel_id in imported.panel_order:
        panel = panels[panel_id]
        piece_id = imported.canonical_piece_ids[panel_id]
        vertices = panel["vertices"]
        edges: list[dict[str, Any]] = []
        for edge_index, native_edge in enumerate(panel["edges"]):
            start, end = native_edge["endpoints"]
            key = (panel_id, edge_index)
            usage = edge_usage[key]
            edge: dict[str, Any] = {
                "edgeId": edge_ids[key],
                "startVertex": start,
                "endVertex": end,
                "role": "seam" if usage else "open",
                "maxConnections": usage,
            }
            native_curve = native_edge.get("curvature")
            if native_curve is not None:
                normalized_curve = normalize_curvature(
                    native_curve, f"native panel {panel_id} edge {edge_index}"
                )
                if normalized_curve["type"] == "circle":
                    normalized_curve["params"][0] /= units_in_meter
                edge["curvature"] = normalized_curve
            edges.append(edge)
        contract_pieces.append(
            {
                "pieceId": piece_id,
                "partId": imported.semantic_panel_groups[panel_id],
                "nativePanelId": panel_id,
                "boundary": [
                    [float(point[0]) / units_in_meter, float(point[1]) / units_in_meter]
                    for point in vertices
                ],
                "seamAllowanceM": 0.0,
                "edges": edges,
            }
        )

    contract_stitches: list[dict[str, Any]] = []
    for stitch_index, (references, tags) in enumerate(native_stitches):
        first_panel, second_panel = references[0]["panel"], references[1]["panel"]
        first_edge, second_edge = references[0]["edge"], references[1]["edge"]
        first_group = imported.semantic_panel_groups[first_panel]
        second_group = imported.semantic_panel_groups[second_panel]
        first_native_edge = panels[first_panel]["edges"][first_edge]
        second_native_edge = panels[second_panel]["edges"][second_edge]
        first_vertices = panels[first_panel]["vertices"]
        second_vertices = panels[second_panel]["vertices"]
        first_vector = [
            float(first_vertices[first_native_edge["endpoints"][1]][axis])
            - float(first_vertices[first_native_edge["endpoints"][0]][axis])
            for axis in range(2)
        ]
        second_vector = [
            float(second_vertices[second_native_edge["endpoints"][1]][axis])
            - float(second_vertices[second_native_edge["endpoints"][0]][axis])
            for axis in range(2)
        ]
        direction_dot = sum(left * right for left, right in zip(first_vector, second_vector))
        direction = (
            "same"
            if direction_dot > 1e-12
            else "reversed"
            if direction_dot < -1e-12
            else "not-applicable"
        )
        interface_ruffle = None
        for side, interface_group, peer_group in (
            ("first", first_group, second_group),
            ("second", second_group, first_group),
        ):
            rule = ruffle_rules.get((interface_group, peer_group))
            if rule is not None:
                if interface_ruffle is not None:
                    raise ValueError(
                        f"native stitch {stitch_index} matches multiple ruffle rules"
                    )
                interface_ruffle = {
                    "side": side,
                    "ratio": rule["ratio"],
                    "source": rule["source"],
                }
        contract_stitch = {
                "stitchId": f"garmentcode-stitch-{stitch_index + 1:04d}",
                "first": {
                    "pieceId": imported.canonical_piece_ids[first_panel],
                    "edgeId": edge_ids[(first_panel, first_edge)],
                },
                "second": {
                    "pieceId": imported.canonical_piece_ids[second_panel],
                    "edgeId": edge_ids[(second_panel, second_edge)],
                },
                "direction": direction,
                "endpointMapping": (
                    "start-to-start" if "right_wrong" in tags else "start-to-end"
                ),
                "nativeTags": tags,
            }
        if interface_ruffle is not None:
            contract_stitch["garmentCodeInterfaceRuffle"] = interface_ruffle
        contract_stitches.append(contract_stitch)

    return (
        {
            "schemaVersion": 1,
            "productId": product_id,
            "units": "meter",
            "pieces": contract_pieces,
        },
        {
            "schemaVersion": 1,
            "productId": product_id,
            "stitches": contract_stitches,
        },
    )


def garmentcode_native_pattern_export(
    imported: GarmentCodeNativePatternImport,
) -> str:
    """Serialize an imported native pattern without changing its source fields."""

    return json.dumps(
        imported.document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
