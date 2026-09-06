"""Semantic contracts for auditable reference and pattern pipeline stages."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PIL import Image

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
        "unobserved": ["back-view"],
        "roundTripMaxErrorPx": max_round_trip,
    }
    return outputs, manifest


def validate_producer_artifact_binding(
    producer_result: Mapping[str, Any],
    *,
    producer_result_path: str,
    artifact_path: Path,
    artifact_repository_path: str,
    expected_stage: str,
    expected_role: str,
    expected_product_id: str,
) -> dict[str, str]:
    """Bind a consumer read to the exact artifact emitted by its producer stage."""
    if producer_result.get("schemaVersion") != 1:
        raise ValueError(
            f"producer result schema mismatch for role {expected_role}: "
            f"{producer_result_path}"
        )
    if producer_result.get("stage") != expected_stage:
        raise ValueError(
            f"producer stage mismatch for role {expected_role}: "
            f"{producer_result_path}"
        )
    if producer_result.get("productId") != expected_product_id:
        raise ValueError(
            f"producer product mismatch for role {expected_role}: "
            f"{producer_result_path}"
        )
    if producer_result.get("status") != "PASS":
        raise ValueError(
            f"producer did not PASS for role {expected_role}: "
            f"{producer_result_path}"
        )
    if producer_result.get("artifactRole") != expected_role:
        raise ValueError(
            f"required role {expected_role} missing from producer result: "
            f"{producer_result_path}"
        )
    producer_hash = producer_result.get("artifactSha256")
    if not isinstance(producer_hash, str) or len(producer_hash) != 64:
        raise ValueError(
            f"producer artifact hash missing for role {expected_role}: "
            f"{producer_result_path}"
        )
    if not artifact_path.is_file():
        raise FileNotFoundError(
            f"canonical artifact missing for role {expected_role}: "
            f"{artifact_repository_path}"
        )
    actual_hash = _sha256(artifact_path)
    if actual_hash != producer_hash:
        raise ValueError(
            f"stale input hash for role {expected_role}: producer "
            f"{producer_result_path} recorded {producer_hash}, canonical "
            f"{artifact_repository_path} is {actual_hash}"
        )

    evidence = producer_result.get("evidence")
    if not isinstance(evidence, list):
        raise ValueError(
            f"producer evidence missing for role {expected_role}: "
            f"{producer_result_path}"
        )
    matches = [
        item
        for item in evidence
        if isinstance(item, Mapping)
        and item.get("path") == artifact_repository_path
    ]
    if len(matches) != 1:
        raise ValueError(
            f"producer evidence path mismatch for role {expected_role}: "
            f"producer={producer_result_path}, canonical={artifact_repository_path}"
        )
    if matches[0].get("sha256") != actual_hash:
        raise ValueError(
            f"producer evidence hash mismatch for role {expected_role}: "
            f"producer={producer_result_path}, canonical={artifact_repository_path}"
        )
    return {
        "role": expected_role,
        "producerResultPath": producer_result_path,
        "artifactPath": artifact_repository_path,
        "artifactSha256": actual_hash,
    }


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
            edges[(piece_id, edge_id)] = {
                "pieceId": piece_id,
                "edgeId": edge_id,
                "role": role,
                "startVertex": start,
                "endVertex": end,
                "vector": vector,
                "maxConnections": max_connections,
            }

    return {
        "pieceCount": len(piece_ids),
        "edgeCount": len(edges),
        "units": payload["units"],
        "edges": edges,
    }


def validate_stitch_contract(
    payload: Mapping[str, Any],
    pattern: Mapping[str, Any],
    *,
    expected_product_id: str,
) -> dict[str, Any]:
    """Validate stitch references, direction declarations, and edge multiplicity."""
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
    seen_ids: set[str] = set()
    usage: dict[tuple[str, str], int] = {}
    orientation_checks = 0
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

        easing = raw_stitch.get("easingRatio", 1.0)
        if (
            not isinstance(easing, (int, float))
            or not math.isfinite(easing)
            or easing <= 0
        ):
            raise ValueError(f"stitch {stitch_id!r} easingRatio must be positive")

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
        "patternPieceCount": pattern_summary["pieceCount"],
        "patternEdgeCount": pattern_summary["edgeCount"],
    }
