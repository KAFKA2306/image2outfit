"""Semantic contracts for auditable reference and pattern pipeline stages."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PIL import Image

from .construction import DEFAULT_RELATIVE_LENGTH_TOLERANCE
from .curves import curve_length, normalize_curvature, scale_curvature
from .domain import PatternEdge, PatternEdgeRole, PatternPiece
from .pattern_stage import (
    DEFAULT_PATTERN_MINIMUM_ANGLE_DEGREES,
    DEFAULT_PATTERN_MINIMUM_AREA_M2,
    DEFAULT_PATTERN_MINIMUM_EDGE_M,
    audit_pattern_piece_geometry,
)
from .stitch_mapping import resolve_endpoint_mapping

_NORMALIZED_SIZE = 768


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_private_reference(
    repository_root: Path,
    job: Mapping[str, Any],
    audit: Mapping[str, Any],
) -> Path:
    """Resolve the exact private source image and verify its recorded digest."""
    source = audit.get("source")
    if not isinstance(source, Mapping):
        raise ValueError("reference audit source must be an object")
    expected_hash = source.get("originalSha256")
    filename = source.get("originalFileName")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise ValueError("reference audit originalSha256 is required")
    if not isinstance(filename, str) or not filename:
        raise ValueError("reference audit originalFileName is required")

    pipeline = job.get("garmentPipeline")
    explicit = (
        pipeline.get("privateReferencePath") if isinstance(pipeline, Mapping) else None
    )
    candidates: list[Path] = []
    if isinstance(explicit, str) and explicit:
        candidates.append((repository_root / explicit).resolve())

    roots = job.get("privateSourceRoots", [])
    if not isinstance(roots, list):
        raise ValueError("job privateSourceRoots must be a list")
    for raw_root in roots:
        if not isinstance(raw_root, str) or not raw_root:
            raise ValueError("privateSourceRoots entries must be non-empty strings")
        root = (repository_root / raw_root).resolve()
        if root != repository_root and repository_root not in root.parents:
            raise ValueError(f"private source root escapes repository: {raw_root}")
        if root.is_dir():
            candidates.extend(path.resolve() for path in root.rglob(filename))

    seen: set[Path] = set()
    mismatches: list[str] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate != repository_root and repository_root not in candidate.parents:
            continue
        if not candidate.is_file():
            continue
        actual = _sha256(candidate)
        if actual == expected_hash:
            return candidate
        mismatches.append(
            f"{candidate.relative_to(repository_root).as_posix()}={actual}"
        )

    if mismatches:
        raise ValueError(
            "private reference image hash mismatch; expected "
            + expected_hash
            + ", found "
            + ", ".join(mismatches)
        )
    raise FileNotFoundError(
        "private reference image is required for normalize-view: "
        f"{filename} sha256={expected_hash}"
    )


def _bbox(
    value: object, *, width: int, height: int, label: str
) -> tuple[int, int, int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or not all(isinstance(item, int) for item in value)
    ):
        raise ValueError(f"{label} must contain four integer pixel coordinates")
    left, top, right, bottom = value
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError(f"{label} is outside source image bounds")
    return left, top, right, bottom


def normalize_observed_variants(
    source_path: Path,
    audit: Mapping[str, Any],
    output_root: Path,
) -> tuple[list[Path], dict[str, Any]]:
    """Crop real source pixels into normalized canvases with invertible transforms."""
    source = audit.get("source")
    if not isinstance(source, Mapping):
        raise ValueError("reference audit source must be an object")
    expected_hash = str(source.get("originalSha256", ""))
    actual_hash = _sha256(source_path)
    if actual_hash != expected_hash:
        raise ValueError("normalize-view source hash does not match reference audit")

    with Image.open(source_path) as opened:
        image = opened.convert("RGB")
    width, height = image.size
    recorded_width = source.get("widthPx")
    recorded_height = source.get("heightPx")
    if recorded_width != width or recorded_height != height:
        raise ValueError(
            "normalize-view source dimensions do not match reference audit: "
            f"{width}x{height} != {recorded_width}x{recorded_height}"
        )

    variants = audit.get("variants")
    if not isinstance(variants, list) or not variants:
        raise ValueError("reference audit variants must be a non-empty list")
    unobserved = audit.get("unobserved", ["back-view"])
    if not isinstance(unobserved, list) or any(
        not isinstance(view, str) or not view.strip() for view in unobserved
    ):
        raise ValueError("reference audit unobserved must be a list of non-empty views")
    if len(unobserved) != len(set(unobserved)):
        raise ValueError("reference audit unobserved views must be unique")

    output_root.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    records: list[dict[str, Any]] = []
    max_round_trip = 0.0
    for raw_variant in variants:
        if not isinstance(raw_variant, Mapping):
            raise ValueError("reference audit variant entries must be objects")
        variant_id = raw_variant.get("variantId")
        if not isinstance(variant_id, str) or not variant_id:
            raise ValueError("reference audit variantId is required")
        left, top, right, bottom = _bbox(
            raw_variant.get("boundingBoxPx"),
            width=width,
            height=height,
            label=f"{variant_id}.boundingBoxPx",
        )
        crop = image.crop((left, top, right, bottom))
        crop_width, crop_height = crop.size
        scale = min(_NORMALIZED_SIZE / crop_width, _NORMALIZED_SIZE / crop_height)
        resized_width = max(1, round(crop_width * scale))
        resized_height = max(1, round(crop_height * scale))
        resized = crop.resize(
            (resized_width, resized_height),
            resample=Image.Resampling.LANCZOS,
        )
        offset_x = (_NORMALIZED_SIZE - resized_width) // 2
        offset_y = (_NORMALIZED_SIZE - resized_height) // 2
        canvas = Image.new("RGB", (_NORMALIZED_SIZE, _NORMALIZED_SIZE), "white")
        canvas.paste(resized, (offset_x, offset_y))
        output = output_root / f"{variant_id}.png"
        canvas.save(output, optimize=True)
        outputs.append(output)

        scale_x = resized_width / crop_width
        scale_y = resized_height / crop_height

        def forward(point: tuple[float, float]) -> tuple[float, float]:
            return (
                (point[0] - left) * scale_x + offset_x,
                (point[1] - top) * scale_y + offset_y,
            )

        def inverse(point: tuple[float, float]) -> tuple[float, float]:
            return (
                (point[0] - offset_x) / scale_x + left,
                (point[1] - offset_y) / scale_y + top,
            )

        corners = (
            (float(left), float(top)),
            (float(right), float(top)),
            (float(right), float(bottom)),
            (float(left), float(bottom)),
        )
        round_trip = max(math.dist(point, inverse(forward(point))) for point in corners)
        max_round_trip = max(max_round_trip, round_trip)
        records.append(
            {
                "variantId": variant_id,
                "observationState": "OBSERVED",
                "sourceRegionPx": [left, top, right, bottom],
                "normalizedContentRegionPx": [
                    offset_x,
                    offset_y,
                    offset_x + resized_width,
                    offset_y + resized_height,
                ],
                "forwardTransform": {
                    "scaleX": scale_x,
                    "scaleY": scale_y,
                    "offsetX": offset_x - left * scale_x,
                    "offsetY": offset_y - top * scale_y,
                },
                "inverseTransform": {
                    "scaleX": 1.0 / scale_x,
                    "scaleY": 1.0 / scale_y,
                    "offsetX": left - offset_x / scale_x,
                    "offsetY": top - offset_y / scale_y,
                },
                "roundTripMaxErrorPx": round_trip,
                "visibleLabel": raw_variant.get("label"),
                "dominantColors": raw_variant.get("dominantColors", []),
                "normalizedImage": output.name,
            }
        )

    manifest = {
        "schemaVersion": 1,
        "productId": audit.get("productId"),
        "status": "PASS",
        "observationSource": "original-image",
        "sourceReference": f"private-reference://sha256/{actual_hash}",
        "sourceOriginalFileName": source.get("originalFileName"),
        "sourceSizePx": [width, height],
        "normalizedCanvasSizePx": [_NORMALIZED_SIZE, _NORMALIZED_SIZE],
        "variants": records,
        "designHypotheses": [],
        "unobserved": unobserved,
        "roundTripMaxErrorPx": max_round_trip,
    }
    return outputs, manifest


def _piece_id(piece: Mapping[str, Any]) -> str:
    value = piece.get("pieceId", piece.get("id"))
    if not isinstance(value, str) or not value:
        raise ValueError("pattern pieceId is required")
    return value


def validate_pattern_contract(
    payload: Mapping[str, Any],
    *,
    expected_product_id: str,
) -> dict[str, Any]:
    """Validate a strict v2 pattern boundary with explicit addressable edges."""
    if payload.get("schemaVersion") != 1:
        raise ValueError("pattern schemaVersion must be 1")
    if payload.get("productId") != expected_product_id:
        raise ValueError("pattern product identity mismatch")
    if payload.get("units") not in {"meter", "millimeter"}:
        raise ValueError("pattern units must be meter or millimeter")
    coordinate_scale = 1.0 if payload["units"] == "meter" else 0.001

    pieces = payload.get("pieces")
    if not isinstance(pieces, list) or not pieces:
        raise ValueError("pattern pieces must be a non-empty list")

    piece_ids: set[str] = set()
    edges: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_piece in pieces:
        if not isinstance(raw_piece, Mapping):
            raise ValueError("pattern pieces must be objects")
        piece_id = _piece_id(raw_piece)
        if piece_id in piece_ids:
            raise ValueError(f"duplicate pattern pieceId: {piece_id}")
        piece_ids.add(piece_id)

        boundary = raw_piece.get("boundary")
        if (
            not isinstance(boundary, list)
            or len(boundary) < 3
            or not all(
                isinstance(point, list)
                and len(point) == 2
                and all(
                    isinstance(value, (int, float)) and math.isfinite(value)
                    for value in point
                )
                for point in boundary
            )
        ):
            raise ValueError(
                f"pattern piece {piece_id!r} requires a finite 2D boundary"
            )

        seam_allowance = raw_piece.get("seamAllowanceM")
        if not isinstance(seam_allowance, (int, float)) or not math.isfinite(
            seam_allowance
        ):
            raise ValueError(f"pattern piece {piece_id!r} seamAllowanceM is required")
        if seam_allowance < 0:
            raise ValueError(
                f"pattern piece {piece_id!r} seamAllowanceM must be non-negative"
            )

        declared_edges = raw_piece.get("edges")
        if not isinstance(declared_edges, list) or not declared_edges:
            raise ValueError(f"pattern piece {piece_id!r} requires explicit edges")
        local_ids: set[str] = set()
        for raw_edge in declared_edges:
            if not isinstance(raw_edge, Mapping):
                raise ValueError(f"pattern piece {piece_id!r} edges must be objects")
            edge_id = raw_edge.get("edgeId")
            if not isinstance(edge_id, str) or not edge_id:
                raise ValueError(f"pattern piece {piece_id!r} edgeId is required")
            if edge_id in local_ids:
                raise ValueError(f"duplicate edge {piece_id}.{edge_id}")
            local_ids.add(edge_id)
            start = raw_edge.get("startVertex")
            end = raw_edge.get("endVertex")
            if (
                not isinstance(start, int)
                or not isinstance(end, int)
                or start == end
                or not 0 <= start < len(boundary)
                or not 0 <= end < len(boundary)
            ):
                raise ValueError(
                    f"pattern edge {piece_id}.{edge_id} has invalid vertices"
                )
            role = raw_edge.get("role")
            if role not in {"seam", "attachment", "open", "hem", "fold", "internal"}:
                raise ValueError(f"pattern edge {piece_id}.{edge_id} has invalid role")
            max_connections = raw_edge.get("maxConnections", 1)
            if not isinstance(max_connections, int) or max_connections < 0:
                raise ValueError(
                    f"pattern edge {piece_id}.{edge_id} maxConnections must be non-negative"
                )
            first = boundary[start]
            second = boundary[end]
            vector = (
                float(second[0]) - float(first[0]),
                float(second[1]) - float(first[1]),
            )
            if math.hypot(*vector) <= 0:
                raise ValueError(f"pattern edge {piece_id}.{edge_id} has zero length")
            curvature = raw_edge.get("curvature")
            length_m = math.hypot(*vector) * coordinate_scale
            if curvature is not None:
                if not isinstance(curvature, Mapping):
                    raise ValueError(
                        f"pattern edge {piece_id}.{edge_id} curvature must be an object"
                    )
                normalized_curve = normalize_curvature(
                    curvature,
                    f"pattern edge {piece_id}.{edge_id}",
                )
                if (end - start) % len(boundary) not in {1, len(boundary) - 1}:
                    raise ValueError(
                        f"curved pattern edge {piece_id}.{edge_id} must map to one boundary segment"
                    )
                length_m = curve_length(
                    (float(first[0]) * coordinate_scale, float(first[1]) * coordinate_scale),
                    (float(second[0]) * coordinate_scale, float(second[1]) * coordinate_scale),
                    scale_curvature(normalized_curve, coordinate_scale),
                )
            edges[(piece_id, edge_id)] = {
                "pieceId": piece_id,
                "edgeId": edge_id,
                "role": role,
                "startVertex": start,
                "endVertex": end,
                "vector": vector,
                "lengthM": length_m,
                "curvature": normalized_curve if curvature is not None else None,
                "maxConnections": max_connections,
            }

    return {
        "pieceCount": len(piece_ids),
        "edgeCount": len(edges),
        "units": payload["units"],
        "edges": edges,
    }


def audit_pattern_geometry_contract(
    payload: Mapping[str, Any],
    *,
    expected_product_id: str,
) -> dict[str, Any]:
    """Audit canonical pattern polygons with the shared domain geometry rules."""
    validate_pattern_contract(payload, expected_product_id=expected_product_id)
    units = payload["units"]
    coordinate_scale = 1.0 if units == "meter" else 0.001
    edge_roles = {
        "seam": PatternEdgeRole.SEAM,
        "attachment": PatternEdgeRole.ATTACHMENT,
        "open": PatternEdgeRole.OPENING,
        "hem": PatternEdgeRole.HEM,
        "fold": PatternEdgeRole.FOLD,
        "internal": PatternEdgeRole.CUT,
    }
    pattern_pieces: list[PatternPiece] = []
    for raw_piece in payload["pieces"]:
        piece_id = _piece_id(raw_piece)
        edges: list[PatternEdge] = []
        for raw_edge in raw_piece["edges"]:
            role = edge_roles.get(raw_edge["role"])
            if role is None:
                raise ValueError(
                    f"pattern edge {piece_id}.{raw_edge['edgeId']} has no geometry role mapping"
                )
            edges.append(
                PatternEdge(
                    edge_id=raw_edge["edgeId"],
                    piece_id=piece_id,
                    start_vertex=raw_edge["startVertex"],
                    end_vertex=raw_edge["endVertex"],
                    role=role,
                    seam_allowance_m=float(raw_piece["seamAllowanceM"]),
                    curvature=(
                        scale_curvature(raw_edge["curvature"], coordinate_scale)
                        if raw_edge.get("curvature") is not None
                        else None
                    ),
                )
            )
        pattern_pieces.append(
            PatternPiece(
                piece_id=piece_id,
                part_id=raw_piece["partId"],
                boundary=tuple(
                    tuple(float(value) * coordinate_scale for value in point)
                    for point in raw_piece["boundary"]
                ),
                grain_angle_degrees=float(raw_piece.get("grainAngleDegrees", 0.0)),
                cut_count=raw_piece.get("cutCount", 1),
                on_fold=raw_piece.get("onFold", False),
                edges=tuple(edges),
            )
        )

    defects = audit_pattern_piece_geometry(pattern_pieces)
    defect_codes = sorted({item.code for item in defects})
    return {
        "auditType": "pattern-piece-planar-geometry",
        "status": "PASS" if not defects else "FAIL",
        "pieceCount": len(pattern_pieces),
        "thresholds": {
            "minimumAreaM2": DEFAULT_PATTERN_MINIMUM_AREA_M2,
            "minimumEdgeM": DEFAULT_PATTERN_MINIMUM_EDGE_M,
            "minimumAngleDegrees": DEFAULT_PATTERN_MINIMUM_ANGLE_DEGREES,
            "maximumSelfIntersections": 0,
        },
        "defectCount": len(defects),
        "defectCounts": {
            code: sum(item.code == code for item in defects)
            for code in defect_codes
        },
        "defects": [
            {
                "pieceId": item.piece_id,
                "code": item.code,
                "value": item.value,
                "threshold": item.threshold,
            }
            for item in defects
        ],
        "evaluationLimit": (
            "Planar pattern geometry only; this does not evaluate fabric grain suitability, "
            "stitch assembly, avatar fit, 3D silhouette, motion, or appearance."
        ),
    }


def validate_stitch_contract(
    payload: Mapping[str, Any],
    pattern: Mapping[str, Any],
    *,
    expected_product_id: str,
    relative_length_tolerance: float = DEFAULT_RELATIVE_LENGTH_TOLERANCE,
) -> dict[str, Any]:
    """Validate stitch references, geometric direction, endpoint mapping, and edge multiplicity."""
    pattern_summary = validate_pattern_contract(
        pattern,
        expected_product_id=expected_product_id,
    )
    if payload.get("schemaVersion") != 1:
        raise ValueError("stitch graph schemaVersion must be 1")
    if payload.get("productId") != expected_product_id:
        raise ValueError("stitch graph product identity mismatch")
    stitches = payload.get("stitches")
    if not isinstance(stitches, list) or not stitches:
        raise ValueError("stitch graph stitches must be a non-empty list")

    edges = pattern_summary["edges"]
    if (
        not isinstance(relative_length_tolerance, (int, float))
        or not math.isfinite(relative_length_tolerance)
        or relative_length_tolerance < 0
    ):
        raise ValueError("relative_length_tolerance must be finite and non-negative")
    seen_ids: set[str] = set()
    usage: dict[tuple[str, str], int] = {}
    orientation_checks = 0
    endpoint_mapping_checks: list[dict[str, str]] = []
    edge_length_checks = 0
    edge_length_mismatches: list[dict[str, Any]] = []
    edge_length_discrepancies: list[float] = []
    for raw_stitch in stitches:
        if not isinstance(raw_stitch, Mapping):
            raise ValueError("stitch graph entries must be objects")
        stitch_id = raw_stitch.get("stitchId", raw_stitch.get("id"))
        if not isinstance(stitch_id, str) or not stitch_id:
            raise ValueError("stitchId is required")
        if stitch_id in seen_ids:
            raise ValueError(f"duplicate stitchId: {stitch_id}")
        seen_ids.add(stitch_id)

        endpoints: list[tuple[str, str]] = []
        for side in ("first", "second"):
            endpoint = raw_stitch.get(side)
            if not isinstance(endpoint, Mapping):
                raise ValueError(f"stitch {stitch_id!r} {side} endpoint is required")
            piece_id = endpoint.get("pieceId")
            edge_id = endpoint.get("edgeId")
            if not isinstance(piece_id, str) or not isinstance(edge_id, str):
                raise ValueError(
                    f"stitch {stitch_id!r} {side} requires pieceId and edgeId"
                )
            key = (piece_id, edge_id)
            if key not in edges:
                raise ValueError(
                    f"stitch {stitch_id!r} references unknown edge {piece_id}.{edge_id}"
                )
            endpoints.append(key)
            usage[key] = usage.get(key, 0) + 1

        if endpoints[0] == endpoints[1]:
            raise ValueError(f"stitch {stitch_id!r} cannot connect an edge to itself")

        direction = raw_stitch.get("direction")
        if direction not in {"same", "reversed", "not-applicable"}:
            raise ValueError(
                f"stitch {stitch_id!r} direction must be same, reversed, or not-applicable"
            )
        first_edge = edges[endpoints[0]]
        second_edge = edges[endpoints[1]]
        if direction != "not-applicable":
            dot = sum(
                left * right
                for left, right in zip(first_edge["vector"], second_edge["vector"])
            )
            if abs(dot) < 1e-12:
                raise ValueError(
                    f"stitch {stitch_id!r} has perpendicular edges; direction is not auditable"
                )
            actual = "same" if dot > 0 else "reversed"
            if direction != actual:
                raise ValueError(
                    f"stitch {stitch_id!r} direction mismatch: "
                    f"declared {direction}, geometry is {actual}"
                )
            orientation_checks += 1

        endpoint_mapping, endpoint_mapping_source = resolve_endpoint_mapping(
            raw_stitch
        )
        endpoint_mapping_checks.append(
            {
                "stitchId": stitch_id,
                "mapping": endpoint_mapping,
                "source": endpoint_mapping_source,
            }
        )

        easing = raw_stitch.get("easingRatio", 1.0)
        if (
            not isinstance(easing, (int, float))
            or not math.isfinite(easing)
            or easing <= 0
        ):
            raise ValueError(f"stitch {stitch_id!r} easingRatio must be positive")
        first_length = first_edge["lengthM"]
        second_length = second_edge["lengthM"]
        interface_ruffle = raw_stitch.get("garmentCodeInterfaceRuffle")
        ruffle_factors = {"first": 1.0, "second": 1.0}
        if interface_ruffle is not None:
            if not isinstance(interface_ruffle, Mapping):
                raise ValueError(
                    f"stitch {stitch_id!r} garmentCodeInterfaceRuffle must be an object"
                )
            side = interface_ruffle.get("side")
            ratio = interface_ruffle.get("ratio")
            source = interface_ruffle.get("source")
            if side not in {"first", "second"}:
                raise ValueError(
                    f"stitch {stitch_id!r} ruffle side must be first or second"
                )
            if (
                isinstance(ratio, bool)
                or not isinstance(ratio, (int, float))
                or not math.isfinite(ratio)
                or ratio < 1.0
            ):
                raise ValueError(
                    f"stitch {stitch_id!r} ruffle ratio must be finite and at least 1"
                )
            if (
                not isinstance(source, Mapping)
                or not isinstance(source.get("path"), str)
                or not source.get("path")
                or not isinstance(source.get("field"), str)
                or not source.get("field")
                or not isinstance(source.get("sha256"), str)
                or len(source["sha256"]) != 64
                or any(character not in "0123456789abcdef" for character in source["sha256"])
            ):
                raise ValueError(
                    f"stitch {stitch_id!r} ruffle metadata requires source path, field, and SHA-256"
                )
            ruffle_factors[side] = float(ratio)
        projected_first_length = first_length / ruffle_factors["first"]
        projected_second_length = (
            second_length / ruffle_factors["second"]
        ) * float(easing)
        denominator = max(projected_first_length, projected_second_length, 1e-12)
        relative_discrepancy = abs(projected_first_length - projected_second_length) / denominator
        edge_length_checks += 1
        edge_length_discrepancies.append(relative_discrepancy)
        if relative_discrepancy > relative_length_tolerance:
            edge_length_mismatches.append(
                {
                    "stitchId": stitch_id,
                    "firstEdge": f"{endpoints[0][0]}.{endpoints[0][1]}",
                    "secondEdge": f"{endpoints[1][0]}.{endpoints[1][1]}",
                    "firstLengthM": first_length,
                    "secondLengthM": second_length,
                    "firstRuffleRatio": ruffle_factors["first"],
                    "secondRuffleRatio": ruffle_factors["second"],
                    "projectedFirstLengthM": projected_first_length,
                    "projectedSecondLengthM": projected_second_length,
                    "easingRatio": float(easing),
                    "expectedSecondLengthM": projected_second_length,
                    "relativeDiscrepancy": relative_discrepancy,
                }
            )

    for key, count in usage.items():
        maximum = edges[key]["maxConnections"]
        if count > maximum:
            raise ValueError(
                f"pattern edge {key[0]}.{key[1]} is used {count} times; "
                f"maxConnections={maximum}"
            )

    required_unsewn = sorted(
        f"{piece}.{edge}"
        for (piece, edge), spec in edges.items()
        if spec["role"] == "seam" and usage.get((piece, edge), 0) == 0
    )
    if required_unsewn:
        raise ValueError(
            "required seam edges are not consumed: " + ", ".join(required_unsewn)
        )

    return {
        "stitchCount": len(seen_ids),
        "referencedEdgeCount": len(usage),
        "orientationChecks": orientation_checks,
        "endpointMappingChecks": endpoint_mapping_checks,
        "explicitEndpointMappingCount": sum(
            check["source"] == "explicit" for check in endpoint_mapping_checks
        ),
        "patternPieceCount": pattern_summary["pieceCount"],
        "patternEdgeCount": pattern_summary["edgeCount"],
        "edgeLengthCompatibilityAudit": {
            "status": "PASS" if not edge_length_mismatches else "FAIL",
            "relativeTolerance": relative_length_tolerance,
            "checkedPairCount": edge_length_checks,
            "compatiblePairCount": edge_length_checks - len(edge_length_mismatches),
            "mismatchCount": len(edge_length_mismatches),
            "maximumRelativeDiscrepancy": max(edge_length_discrepancies, default=0.0),
            "meanRelativeDiscrepancy": (
                sum(edge_length_discrepancies) / len(edge_length_discrepancies)
                if edge_length_discrepancies
                else 0.0
            ),
            "mismatches": edge_length_mismatches,
            "evaluationLimit": (
                "2D edge lengths use exact circles and bounded Bezier flattening; this does not evaluate sewn 3D curves, "
                "physical ease, assembly, avatar fit, collision, motion, or appearance."
            ),
        },
    }


def audit_structural_pattern_coverage(
    pattern: Mapping[str, Any],
    stitches: Mapping[str, Any],
    decomposition: Mapping[str, Any],
    construction: Mapping[str, Any] | None,
    *,
    expected_product_id: str,
) -> dict[str, Any]:
    """Check that required structural parts exist and their seams form components."""
    payloads = [
        ("pattern", pattern),
        ("stitch graph", stitches),
        ("decomposition", decomposition),
    ]
    if construction is not None:
        payloads.append(("construction", construction))
    for label, payload in payloads:
        if payload.get("schemaVersion") != 1:
            raise ValueError(f"{label} schemaVersion must be 1")
        if payload.get("productId") != expected_product_id:
            raise ValueError(f"{label} product identity mismatch")

    pattern_pieces = pattern.get("pieces")
    decomposition_parts = decomposition.get("parts")
    stitch_pairs = stitches.get("stitches")
    if not all(
        isinstance(items, list)
        for items in (pattern_pieces, decomposition_parts, stitch_pairs)
    ):
        raise ValueError("pattern pieces, decomposition parts, and stitch graph must be lists")

    piece_ids: set[str] = set()
    part_id_by_piece: dict[str, str] = {}
    piece_ids_by_part: dict[str, list[str]] = {}
    for index, raw_piece in enumerate(pattern_pieces):
        if not isinstance(raw_piece, Mapping):
            raise ValueError(f"pattern piece {index} must be an object")
        piece_id = _piece_id(raw_piece)
        if piece_id in piece_ids:
            raise ValueError(f"duplicate pattern pieceId: {piece_id}")
        part_id = raw_piece.get("partId")
        if not isinstance(part_id, str) or not part_id:
            raise ValueError(f"pattern piece {piece_id!r} partId is required")
        piece_ids.add(piece_id)
        part_id_by_piece[piece_id] = part_id
        piece_ids_by_part.setdefault(part_id, []).append(piece_id)

    structural_part_ids: list[str] = []
    for index, raw_part in enumerate(decomposition_parts):
        if not isinstance(raw_part, Mapping):
            raise ValueError(f"decomposition part {index} must be an object")
        if raw_part.get("role") != "structural-panel":
            continue
        part_id = raw_part.get("partId")
        if not isinstance(part_id, str) or not part_id:
            raise ValueError(f"structural decomposition part {index} requires partId")
        if part_id in structural_part_ids:
            raise ValueError(f"duplicate structural decomposition partId: {part_id}")
        structural_part_ids.append(part_id)

    required_components = (
        construction.get("requiredPatternComponents", [])
        if construction is not None
        else []
    )
    if not isinstance(required_components, list):
        raise ValueError("construction requiredPatternComponents must be a list")
    construction_panels = construction.get("panels") if construction is not None else None
    if required_components:
        if not isinstance(construction_panels, list) or not all(
            isinstance(item, str) and item for item in construction_panels
        ):
            raise ValueError(
                "construction panels must list every required pattern piece ID"
            )
        if len(construction_panels) != len(set(construction_panels)):
            raise ValueError("construction panels must contain unique piece IDs")

    adjacency = {piece_id: set() for piece_id in piece_ids}
    for index, raw_stitch in enumerate(stitch_pairs):
        if not isinstance(raw_stitch, Mapping):
            raise ValueError(f"stitch {index} must be an object")
        first = raw_stitch.get("first")
        second = raw_stitch.get("second")
        if not isinstance(first, Mapping) or not isinstance(second, Mapping):
            raise ValueError(f"stitch {index} must have two endpoints")
        first_piece = first.get("pieceId")
        second_piece = second.get("pieceId")
        if first_piece not in adjacency or second_piece not in adjacency:
            raise ValueError(f"stitch {index} references an unknown pattern piece")
        adjacency[first_piece].add(second_piece)
        adjacency[second_piece].add(first_piece)

    connectivity_audits: dict[str, dict[str, Any]] = {}
    for part_id in sorted(structural_part_ids):
        part_piece_ids = sorted(piece_ids_by_part.get(part_id, []))
        if not part_piece_ids:
            connectivity_audits[part_id] = {
                "partId": part_id,
                "patternPieceIds": [],
                "connectedByStitchGraph": False,
                "status": "MISSING_PATTERN_PIECES",
            }
            continue
        pending = [part_piece_ids[0]]
        connected = {part_piece_ids[0]}
        while pending:
            current = pending.pop()
            same_part_neighbours = {
                neighbour
                for neighbour in adjacency[current]
                if part_id_by_piece[neighbour] == part_id
            }
            for neighbour in same_part_neighbours.difference(connected):
                connected.add(neighbour)
                pending.append(neighbour)
        is_connected = connected == set(part_piece_ids)
        connectivity_audits[part_id] = {
            "partId": part_id,
            "patternPieceIds": part_piece_ids,
            "connectedByStitchGraph": is_connected,
            "status": "PASS" if is_connected else "DISCONNECTED_STITCH_GRAPH",
        }

    component_audits: list[dict[str, Any]] = []
    component_ids: set[str] = set()
    for index, raw_component in enumerate(required_components):
        if not isinstance(raw_component, Mapping):
            raise ValueError(f"required pattern component {index} must be an object")
        component_id = raw_component.get("componentId")
        part_id = raw_component.get("partId")
        required_piece_ids = raw_component.get("requiredPieceIds")
        if not isinstance(component_id, str) or not component_id:
            raise ValueError(f"required pattern component {index} needs componentId")
        if component_id in component_ids:
            raise ValueError(f"duplicate required pattern componentId: {component_id}")
        component_ids.add(component_id)
        if not isinstance(part_id, str) or part_id not in structural_part_ids:
            raise ValueError(
                f"required pattern component {component_id!r} must bind to a structural decomposition part"
            )
        if not isinstance(required_piece_ids, list) or not required_piece_ids:
            raise ValueError(
                f"required pattern component {component_id!r} needs requiredPieceIds"
            )
        if not all(isinstance(item, str) and item for item in required_piece_ids):
            raise ValueError(
                f"required pattern component {component_id!r} has an invalid piece ID"
            )
        if len(required_piece_ids) != len(set(required_piece_ids)):
            raise ValueError(
                f"required pattern component {component_id!r} needs unique requiredPieceIds"
            )
        observed_piece_ids = set(piece_ids_by_part.get(part_id, []))
        missing_piece_ids = sorted(set(required_piece_ids).difference(piece_ids))
        undeclared_piece_ids = sorted(
            set(required_piece_ids).difference(construction_panels or [])
        )
        wrong_part_piece_ids = sorted(
            item
            for item in set(required_piece_ids).intersection(piece_ids)
            if part_id_by_piece[item] != part_id
        )
        connectivity = connectivity_audits[part_id]
        if undeclared_piece_ids:
            status = "REQUIRED_PANELS_NOT_DECLARED_IN_CONSTRUCTION"
        elif missing_piece_ids:
            status = "MISSING_REQUIRED_PANELS"
        elif wrong_part_piece_ids:
            status = "WRONG_PATTERN_PART_BINDING"
        elif connectivity["status"] != "PASS":
            status = "DISCONNECTED_STITCH_GRAPH"
        else:
            status = "PASS"
        component_audits.append(
            {
                "componentId": component_id,
                "partId": part_id,
                "requiredPieceIds": list(required_piece_ids),
                "observedPieceIds": sorted(observed_piece_ids),
                "undeclaredRequiredPieceIds": undeclared_piece_ids,
                "missingPieceIds": missing_piece_ids,
                "wrongPartPieceIds": wrong_part_piece_ids,
                "connectedByStitchGraph": connectivity["connectedByStitchGraph"],
                "status": status,
            }
        )

    missing_components = [
        item["componentId"]
        for item in component_audits
        if item["status"] != "PASS"
    ]
    missing_panels = sorted(
        {piece_id for item in component_audits for piece_id in item["missingPieceIds"]}
    )
    undeclared_panels = sorted(
        {
            piece_id
            for item in component_audits
            for piece_id in item["undeclaredRequiredPieceIds"]
        }
    )
    disconnected_components = [
        item["componentId"]
        for item in component_audits
        if item["status"] == "DISCONNECTED_STITCH_GRAPH"
    ]
    passed = not missing_components
    audit_status = (
        "BLOCKED"
        if not passed
        else "PASS"
        if required_components
        else "NOT_REQUIRED"
    )
    return {
        "status": audit_status,
        "patternPieceCount": len(piece_ids),
        "requiredPatternComponentCount": len(component_audits),
        "constructionPanelCount": (
            len(construction_panels) if isinstance(construction_panels, list) else None
        ),
        "missingExpectedPanels": missing_panels,
        "undeclaredRequiredPanels": undeclared_panels,
        "structuralComponentCoverage": component_audits,
        "structuralPartStitchConnectivity": [
            connectivity_audits[part_id] for part_id in sorted(connectivity_audits)
        ],
        "missingStructuralComponents": missing_components,
        "disconnectedStructuralComponents": disconnected_components,
        "stitchConnectivityScope": "Per required structural component; graph-level piece connectivity only, no physical assembly or 3D claim.",
    }
