"""Deterministic exchange contract for Marvelous Designer's official Python API.

The Marvelous Designer runtime stays external to image2outfit. This module owns
only the repository-side request manifest: canonical pattern/stitch/material
inputs are converted to explicit API-ready operations with hashes and fail-closed
validation. The actual API calls run inside Marvelous Designer.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

MD_API_REFERENCE = "https://developer.marvelousdesigner.com/list.html"
MD_PYTHON_REFERENCE = "https://developer.marvelousdesigner.com/python.html"
MD_SCENARIO_REFERENCE = "https://developer.marvelousdesigner.com/scenario.html"


@dataclass(frozen=True, slots=True)
class MarvelousDesignerRuntimeDescriptor:
    runtime_id: str
    execution_mode: str
    api_reference: str
    python_reference: str
    scenario_reference: str
    required_modules: tuple[str, ...]
    required_functions: tuple[str, ...]


MARVELOUS_DESIGNER_RUNTIME = MarvelousDesignerRuntimeDescriptor(
    runtime_id="marvelous-designer-python-api",
    execution_mode="in-application-python",
    api_reference=MD_API_REFERENCE,
    python_reference=MD_PYTHON_REFERENCE,
    scenario_reference=MD_SCENARIO_REFERENCE,
    required_modules=(
        "ApiTypes",
        "export_api",
        "fabric_api",
        "import_api",
        "pattern_api",
        "utility_api",
    ),
    required_functions=(
        "import_api.ImportFBX",
        "pattern_api.CreatePatternWithPoints",
        "pattern_api.CreateInternalShapeWithPoints",
        "pattern_api.SetPatternPieceName",
        "pattern_api.SetPatternPieceGrainDirection",
        "pattern_api.AddSeamlinePairGroup",
        "pattern_api.SetArrangement",
        "pattern_api.SetArrangementPosition",
        "pattern_api.SetArrangementOrientation",
        "fabric_api.CreateZfabFromTextures",
        "fabric_api.AddFabric",
        "fabric_api.AssignFabricToPattern",
        "utility_api.NewProject",
        "utility_api.SetSimulationQuality",
        "utility_api.SetSimulationTimeStep",
        "utility_api.SetSimulationNumberOfSimulation",
        "utility_api.Simulate",
        "export_api.ExportZPrj",
        "export_api.ExportOBJ",
        "export_api.ExportFBX",
    ),
)


class MarvelousDesignerContractError(ValueError):
    """Raised when canonical garment inputs cannot map safely to MD API calls."""


def canonical_json(value: Mapping[str, Any]) -> str:
    """Serialize a request deterministically for hashing and replay."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def request_sha256(value: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def _require_object(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MarvelousDesignerContractError(f"{label} must be an object")
    return value


def _require_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise MarvelousDesignerContractError(f"{label} must be a list")
    return value


def _piece_id(piece: Mapping[str, Any]) -> str:
    value = piece.get("pieceId", piece.get("id"))
    if not isinstance(value, str) or not value:
        raise MarvelousDesignerContractError("pattern pieceId is required")
    return value


def _piece_lookup(pattern: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    pieces = _require_list(pattern.get("pieces"), "pattern.pieces")
    result: dict[str, Mapping[str, Any]] = {}
    for raw in pieces:
        piece = _require_object(raw, "pattern piece")
        piece_id = _piece_id(piece)
        if piece_id in result:
            raise MarvelousDesignerContractError(f"duplicate pattern piece: {piece_id}")
        result[piece_id] = piece
    if not result:
        raise MarvelousDesignerContractError("pattern.pieces must not be empty")
    return result


def _scale_to_mm(units: str) -> float:
    if units == "meter":
        return 1000.0
    if units == "millimeter":
        return 1.0
    raise MarvelousDesignerContractError(
        f"unsupported canonical pattern units {units!r}; expected meter or millimeter"
    )


def _point_mm(raw: object, units: str) -> list[float | int]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != 2:
        raise MarvelousDesignerContractError("pattern point must contain x,y")
    x, y = raw
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise MarvelousDesignerContractError("pattern x must be numeric")
    if isinstance(y, bool) or not isinstance(y, (int, float)):
        raise MarvelousDesignerContractError("pattern y must be numeric")
    scale = _scale_to_mm(units)
    return [float(x) * scale, float(y) * scale, 0]


def _points_mm(piece: Mapping[str, Any], units: str) -> list[list[float | int]]:
    return [
        _point_mm(raw, units)
        for raw in _require_list(piece.get("boundary"), "pattern piece boundary")
    ]


def _walk_segments(vertex_count: int, start: int, end: int, step: int) -> list[dict[str, Any]]:
    current = start
    segments: list[dict[str, Any]] = []
    guard = 0
    while current != end:
        guard += 1
        if guard > vertex_count:
            raise MarvelousDesignerContractError("edge walk did not terminate")
        if step == 1:
            line_index = current
            following = (current + 1) % vertex_count
            forward = True
        else:
            following = (current - 1) % vertex_count
            line_index = following
            forward = False
        segments.append({"lineIndex": line_index, "forward": forward})
        current = following
    return segments


def _edge_vertices(
    piece: Mapping[str, Any], edge: Mapping[str, Any]
) -> tuple[list[Any], int, int]:
    boundary = _require_list(piece.get("boundary"), "pattern piece boundary")
    if len(boundary) < 3:
        raise MarvelousDesignerContractError("pattern boundary requires at least 3 vertices")
    start = edge.get("startVertex")
    end = edge.get("endVertex")
    if isinstance(start, bool) or not isinstance(start, int):
        raise MarvelousDesignerContractError("edge.startVertex must be an integer")
    if isinstance(end, bool) or not isinstance(end, int):
        raise MarvelousDesignerContractError("edge.endVertex must be an integer")
    if start == end or min(start, end) < 0 or max(start, end) >= len(boundary):
        raise MarvelousDesignerContractError("edge vertex indices are invalid")
    return boundary, start, end


def edge_segments(piece: Mapping[str, Any], edge: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Resolve a canonical boundary edge to one or more MD boundary line indices.

    Non-adjacent legacy edges are represented by the unique shortest boundary arc.
    An equal-length tie is deliberately rejected here because it is not a unique
    boundary address. The higher-level adapter may map an attachment/internal tie
    to an explicit MD internal shape instead.
    """

    boundary, start, end = _edge_vertices(piece, edge)
    forward = _walk_segments(len(boundary), start, end, 1)
    reverse = _walk_segments(len(boundary), start, end, -1)
    if len(forward) == len(reverse):
        edge_id = edge.get("edgeId", "<unnamed>")
        raise MarvelousDesignerContractError(
            f"edge {edge_id!r} has an ambiguous equal-length boundary arc"
        )
    return forward if len(forward) < len(reverse) else reverse


def _edge_binding(
    piece: Mapping[str, Any], edge: Mapping[str, Any], units: str
) -> dict[str, Any]:
    boundary, start, end = _edge_vertices(piece, edge)
    role = edge.get("role")
    explicit_locus = edge.get("locus")
    if explicit_locus not in {None, "boundary", "internal"}:
        raise MarvelousDesignerContractError("edge.locus must be boundary or internal")

    forward = _walk_segments(len(boundary), start, end, 1)
    reverse = _walk_segments(len(boundary), start, end, -1)
    equal_arc = len(forward) == len(reverse)
    internal = explicit_locus == "internal" or role == "internal"
    inference = None
    if explicit_locus is None and not internal and equal_arc and role == "attachment":
        # Legacy v2 pattern contracts have no geometric-locus field. An attachment
        # chord with no unique boundary route is representable in MD only as an
        # internal line. Preserve the inference in the request so it is auditable.
        internal = True
        inference = "legacy-equal-arc-attachment-as-internal"

    if internal:
        return {
            "kind": "internal",
            "internalEdgeId": str(edge.get("edgeId")),
            "pointsMm": [_point_mm(boundary[start], units), _point_mm(boundary[end], units)],
            "segments": [{"lineIndex": 0, "forward": True}],
            "inference": inference,
        }
    if equal_arc:
        edge_id = edge.get("edgeId", "<unnamed>")
        raise MarvelousDesignerContractError(
            f"edge {edge_id!r} has an ambiguous equal-length boundary arc"
        )
    return {
        "kind": "boundary",
        "segments": forward if len(forward) < len(reverse) else reverse,
    }


def _edge_index(piece: Mapping[str, Any], units: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in _require_list(piece.get("edges", []), "pattern piece edges"):
        edge = _require_object(raw, "pattern edge")
        edge_id = edge.get("edgeId")
        if not isinstance(edge_id, str) or not edge_id:
            raise MarvelousDesignerContractError("pattern edgeId is required")
        if edge_id in result:
            raise MarvelousDesignerContractError(f"duplicate edge id: {edge_id}")
        result[edge_id] = _edge_binding(piece, edge, units)
    return result


def _endpoint_segments(
    piece_id: str, edge_id: str, binding: Mapping[str, Any]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw in _require_list(binding.get("segments"), "edge binding segments"):
        segment = _require_object(raw, "edge binding segment")
        endpoint: dict[str, Any] = {
            "pieceId": piece_id,
            "kind": str(binding["kind"]),
            "lineIndex": int(segment["lineIndex"]),
            "direction": bool(segment["forward"]),
        }
        if binding["kind"] == "internal":
            endpoint["internalEdgeId"] = str(binding["internalEdgeId"])
        output.append(endpoint)
    return output


def _stitch_requests(
    stitch_graph: Mapping[str, Any],
    pieces: Mapping[str, Mapping[str, Any]],
    edge_maps: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw in _require_list(stitch_graph.get("stitches"), "stitchGraph.stitches"):
        stitch = _require_object(raw, "stitch")
        stitch_id = stitch.get("stitchId")
        if not isinstance(stitch_id, str) or not stitch_id:
            raise MarvelousDesignerContractError("stitchId is required")
        endpoints: list[tuple[str, str, Mapping[str, Any]]] = []
        for side in ("first", "second"):
            endpoint = _require_object(stitch.get(side), f"stitch.{side}")
            piece_id = endpoint.get("pieceId")
            edge_id = endpoint.get("edgeId")
            if not isinstance(piece_id, str) or piece_id not in pieces:
                raise MarvelousDesignerContractError(
                    f"stitch {stitch_id!r} references unknown piece {piece_id!r}"
                )
            if not isinstance(edge_id, str) or edge_id not in edge_maps[piece_id]:
                raise MarvelousDesignerContractError(
                    f"stitch {stitch_id!r} references unknown edge {edge_id!r}"
                )
            endpoints.append((piece_id, edge_id, edge_maps[piece_id][edge_id]))

        first_raw = _endpoint_segments(*endpoints[0])
        second_raw = _endpoint_segments(*endpoints[1])
        if len(first_raw) != len(second_raw):
            raise MarvelousDesignerContractError(
                f"stitch {stitch_id!r} maps to {len(first_raw)} vs {len(second_raw)} MD lines; "
                "explicit edge subdivision is required"
            )
        direction = stitch.get("direction", "reversed")
        if direction not in {"same", "reversed", "not-applicable"}:
            raise MarvelousDesignerContractError(
                f"stitch {stitch_id!r} has unsupported direction {direction!r}"
            )
        segments: list[dict[str, Any]] = []
        for first, second in zip(first_raw, second_raw, strict=True):
            second = dict(second)
            if direction == "reversed":
                second["direction"] = not bool(second["direction"])
            segments.append({"first": first, "second": second})
        output.append(
            {
                "stitchId": stitch_id,
                "type": stitch.get("type", "plain"),
                "easingRatio": stitch.get("easingRatio", 1),
                "segments": segments,
            }
        )
    return output


def _material_requests(
    material_recipe: Mapping[str, Any] | None,
    pieces: Mapping[str, Mapping[str, Any]],
    product_root: str,
) -> tuple[list[dict[str, Any]], list[str], bool]:
    if not material_recipe:
        return [], sorted(pieces), False
    map_sets = _require_object(material_recipe.get("mapSets", {}), "materialRecipe.mapSets")
    materials = _require_object(material_recipe.get("materials", {}), "materialRecipe.materials")
    assigned: set[str] = set()
    result: list[dict[str, Any]] = []
    all_realized = True
    for role, raw in sorted(materials.items()):
        material = _require_object(raw, f"materialRecipe.materials.{role}")
        map_set_name = material.get("mapSet")
        regions = material.get("regions", [])
        if not isinstance(regions, list) or not all(isinstance(item, str) for item in regions):
            raise MarvelousDesignerContractError(f"material {role!r} regions must be strings")
        matched: list[str] = []
        for piece_id, piece in pieces.items():
            part_id = str(piece.get("partId", ""))
            for region in regions:
                if (
                    piece_id == region
                    or piece_id.startswith(region)
                    or part_id == region
                    or part_id.startswith(region)
                ):
                    matched.append(piece_id)
                    assigned.add(piece_id)
                    break
        entry: dict[str, Any] = {
            "role": str(role),
            "materialName": str(material.get("materialName", role)),
            "patterns": sorted(matched),
            "alpha": material.get("alpha", 1),
            "metallic": material.get("metallic", 0),
        }
        if isinstance(map_set_name, str) and map_set_name in map_sets:
            map_set = _require_object(map_sets[map_set_name], f"mapSet {map_set_name}")
            entry["mapSet"] = map_set_name
            entry["textureIntent"] = dict(map_set)
            entry["textureProvenance"] = map_set.get("provenance", {})
            files = map_set.get("files")
            if isinstance(files, Mapping) and all(
                isinstance(files.get(name), str) and files.get(name)
                for name in ("baseColor", "normal", "roughness")
            ):
                entry["textures"] = {
                    name: str(files[name])
                    for name in (
                        "baseColor",
                        "normal",
                        "roughness",
                        "displacement",
                        "opacity",
                        "metalness",
                    )
                    if isinstance(files.get(name), str) and files.get(name)
                }
                entry["realizationStatus"] = "BOUND"
            else:
                expected_root = f"{product_root}/Textures"
                entry["expectedTextureRoot"] = expected_root
                entry["realizationStatus"] = "UNVERIFIED"
                all_realized = False
        elif matched:
            # Constant/non-texture materials are valid material assignments but are
            # not enough to claim the PBR texture path implemented by this backend.
            entry["realizationStatus"] = "UNVERIFIED"
            all_realized = False
        result.append(entry)
    return result, sorted(set(pieces).difference(assigned)), all_realized


def build_request(
    *,
    job: Mapping[str, Any],
    pattern: Mapping[str, Any],
    stitch_graph: Mapping[str, Any],
    material_recipe: Mapping[str, Any] | None = None,
    initialization: Mapping[str, Any] | None = None,
    source_bindings: Mapping[str, str] | None = None,
    simulation_steps: int = 120,
) -> dict[str, Any]:
    """Build one replayable Marvelous Designer API request from canonical JSON."""

    product_id = job.get("id")
    if not isinstance(product_id, str) or not product_id:
        raise MarvelousDesignerContractError("job.id is required")
    for label, document in (("pattern", pattern), ("stitch graph", stitch_graph)):
        if document.get("productId") != product_id:
            raise MarvelousDesignerContractError(f"{label} product identity mismatch")
    if (
        isinstance(simulation_steps, bool)
        or not isinstance(simulation_steps, int)
        or simulation_steps < 1
    ):
        raise MarvelousDesignerContractError("simulation_steps must be a positive integer")

    pieces = _piece_lookup(pattern)
    units = str(pattern.get("units", ""))
    _scale_to_mm(units)
    edge_maps = {
        piece_id: _edge_index(piece, units) for piece_id, piece in pieces.items()
    }
    pattern_requests: list[dict[str, Any]] = []
    for piece_id, piece in sorted(pieces.items()):
        internal_lines = []
        named_edges: dict[str, Any] = {}
        for edge_id, binding in edge_maps[piece_id].items():
            named_edges[edge_id] = {
                key: value
                for key, value in binding.items()
                if key not in {"pointsMm"}
            }
            if binding["kind"] == "internal":
                internal_lines.append(
                    {
                        "edgeId": edge_id,
                        "pointsMm": binding["pointsMm"],
                        "isClosed": False,
                        "inference": binding.get("inference"),
                    }
                )
        pattern_requests.append(
            {
                "pieceId": piece_id,
                "partId": str(piece.get("partId", "")),
                "pointsMm": _points_mm(piece, units),
                "grainAngleDegrees": float(piece.get("grainAngleDegrees", 0.0)),
                "cutCount": int(piece.get("cutCount", 1)),
                "onFold": bool(piece.get("onFold", False)),
                "namedEdges": named_edges,
                "internalLines": internal_lines,
            }
        )

    placements: dict[str, dict[str, Any]] = {}
    if initialization:
        if initialization.get("productId") not in {None, product_id}:
            raise MarvelousDesignerContractError("initialization product identity mismatch")
        raw_placements = initialization.get("placements", {})
        if isinstance(raw_placements, Mapping):
            placements = {
                str(key): dict(value)
                for key, value in raw_placements.items()
                if key in pieces and isinstance(value, Mapping)
            }
    materials, unassigned, materials_realized = _material_requests(
        material_recipe, pieces, str(job.get("productRoot", ""))
    )
    runtime_root = f".image2outfit/products/{product_id}/marvelous-designer"
    request: dict[str, Any] = {
        "schemaVersion": 1,
        "backend": MARVELOUS_DESIGNER_RUNTIME.runtime_id,
        "productId": product_id,
        "apiContract": {
            "executionMode": MARVELOUS_DESIGNER_RUNTIME.execution_mode,
            "reference": MARVELOUS_DESIGNER_RUNTIME.api_reference,
            "pythonReference": MARVELOUS_DESIGNER_RUNTIME.python_reference,
            "scenarioReference": MARVELOUS_DESIGNER_RUNTIME.scenario_reference,
            "requiredModules": list(MARVELOUS_DESIGNER_RUNTIME.required_modules),
            "requiredFunctions": list(MARVELOUS_DESIGNER_RUNTIME.required_functions),
        },
        "sourceBindings": dict(sorted((source_bindings or {}).items())),
        "units": {
            "canonical": units,
            "marvelousDesigner": "millimeter",
            "scale": _scale_to_mm(units),
        },
        "avatar": {
            "sourcePath": job.get("targetSourcePath"),
            "adapterId": job.get("adapterId"),
            "importAs": "avatar",
        },
        "patterns": pattern_requests,
        "stitches": _stitch_requests(stitch_graph, pieces, edge_maps),
        "arrangement": {
            "status": "BOUND" if placements else "UNVERIFIED",
            "placements": placements,
            "policy": "canonical-initialize-3d-output-only",
        },
        "materials": {
            "status": (
                "BOUND"
                if materials and materials_realized and not unassigned
                else "UNVERIFIED"
            ),
            "definitions": materials,
            "unassignedPatterns": unassigned,
            "policy": "canonical-material-recipe-and-realized-textures-only",
        },
        "simulation": {
            "steps": simulation_steps,
            "quality": 2,
            "mode": 0,
            "timeStep": 0.03333,
            "substeps": 1,
        },
        "outputs": {
            "root": runtime_root,
            "project": f"{runtime_root}/{product_id}.zprj",
            "obj": f"{runtime_root}/{product_id}.obj",
            "fbx": f"{runtime_root}/{product_id}.fbx",
            "result": f"{runtime_root}/execution-result.json",
        },
        "completionPolicy": {
            "mdExecutionIsNotProductPass": True,
            "existingVerifierRequired": True,
            "missingExecutionStatus": "UNVERIFIED",
        },
    }
    request["requestSha256"] = request_sha256(request)
    return request
