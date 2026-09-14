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
        "pattern_api.CreatePatternWithPoints",
        "pattern_api.SetPatternPieceName",
        "pattern_api.SetPatternPieceGrainDirection",
        "pattern_api.AddSeamlinePairGroup",
        "pattern_api.SetArrangement",
        "fabric_api.CreateZfabFromTextures",
        "fabric_api.AddFabric",
        "fabric_api.AssignFabricToPattern",
        "utility_api.NewProject",
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


def _piece_lookup(pattern: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    pieces = _require_list(pattern.get("pieces"), "pattern.pieces")
    result: dict[str, Mapping[str, Any]] = {}
    for raw in pieces:
        piece = _require_object(raw, "pattern piece")
        piece_id = piece.get("pieceId")
        if not isinstance(piece_id, str) or not piece_id:
            raise MarvelousDesignerContractError("pattern pieceId is required")
        if piece_id in result:
            raise MarvelousDesignerContractError(f"duplicate pattern piece: {piece_id}")
        result[piece_id] = piece
    if not result:
        raise MarvelousDesignerContractError("pattern.pieces must not be empty")
    return result


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


def edge_segments(piece: Mapping[str, Any], edge: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Resolve a named canonical edge to one or more MD boundary line indices.

    Legacy pattern contracts may name a seam using two non-adjacent vertices. MD's
    sewing API addresses one line at a time, so we choose the unique shortest
    boundary arc. Ties are rejected instead of guessing which side of the polygon
    was intended.
    """

    boundary = _require_list(piece.get("boundary"), "pattern piece boundary")
    vertex_count = len(boundary)
    if vertex_count < 3:
        raise MarvelousDesignerContractError("pattern boundary requires at least 3 vertices")
    start = edge.get("startVertex")
    end = edge.get("endVertex")
    if isinstance(start, bool) or not isinstance(start, int):
        raise MarvelousDesignerContractError("edge.startVertex must be an integer")
    if isinstance(end, bool) or not isinstance(end, int):
        raise MarvelousDesignerContractError("edge.endVertex must be an integer")
    if start == end or min(start, end) < 0 or max(start, end) >= vertex_count:
        raise MarvelousDesignerContractError("edge vertex indices are invalid")
    forward = _walk_segments(vertex_count, start, end, 1)
    reverse = _walk_segments(vertex_count, start, end, -1)
    if len(forward) == len(reverse):
        edge_id = edge.get("edgeId", "<unnamed>")
        raise MarvelousDesignerContractError(
            f"edge {edge_id!r} has an ambiguous equal-length boundary arc"
        )
    return forward if len(forward) < len(reverse) else reverse


def _edge_index(piece: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for raw in _require_list(piece.get("edges", []), "pattern piece edges"):
        edge = _require_object(raw, "pattern edge")
        edge_id = edge.get("edgeId")
        if not isinstance(edge_id, str) or not edge_id:
            raise MarvelousDesignerContractError("pattern edgeId is required")
        if edge_id in result:
            raise MarvelousDesignerContractError(f"duplicate edge id: {edge_id}")
        result[edge_id] = edge_segments(piece, edge)
    return result


def _points_mm(piece: Mapping[str, Any], units: str) -> list[list[float | int]]:
    if units != "meter":
        raise MarvelousDesignerContractError(
            f"unsupported canonical pattern units {units!r}; expected 'meter'"
        )
    points: list[list[float | int]] = []
    for raw in _require_list(piece.get("boundary"), "pattern piece boundary"):
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != 2:
            raise MarvelousDesignerContractError("pattern boundary point must contain x,y")
        x, y = raw
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise MarvelousDesignerContractError("pattern x must be numeric")
        if isinstance(y, bool) or not isinstance(y, (int, float)):
            raise MarvelousDesignerContractError("pattern y must be numeric")
        points.append([float(x) * 1000.0, float(y) * 1000.0, 0])
    return points


def _stitch_requests(
    stitch_graph: Mapping[str, Any],
    pieces: Mapping[str, Mapping[str, Any]],
    edge_maps: Mapping[str, Mapping[str, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw in _require_list(stitch_graph.get("stitches"), "stitchGraph.stitches"):
        stitch = _require_object(raw, "stitch")
        stitch_id = stitch.get("stitchId")
        if not isinstance(stitch_id, str) or not stitch_id:
            raise MarvelousDesignerContractError("stitchId is required")
        endpoints: list[tuple[str, str, list[dict[str, Any]]]] = []
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
        first, second = endpoints
        if len(first[2]) != len(second[2]):
            raise MarvelousDesignerContractError(
                f"stitch {stitch_id!r} maps to {len(first[2])} vs {len(second[2])} MD lines; "
                "explicit edge subdivision is required"
            )
        direction = stitch.get("direction", "reversed")
        if direction not in {"same", "reversed", "not-applicable"}:
            raise MarvelousDesignerContractError(
                f"stitch {stitch_id!r} has unsupported direction {direction!r}"
            )
        segments = []
        for first_segment, second_segment in zip(first[2], second[2], strict=True):
            direction_a = bool(first_segment["forward"])
            direction_b = bool(second_segment["forward"])
            if direction == "reversed":
                direction_b = not direction_b
            segments.append(
                {
                    "first": {
                        "pieceId": first[0],
                        "lineIndex": first_segment["lineIndex"],
                        "direction": direction_a,
                    },
                    "second": {
                        "pieceId": second[0],
                        "lineIndex": second_segment["lineIndex"],
                        "direction": direction_b,
                    },
                }
            )
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
) -> tuple[list[dict[str, Any]], list[str]]:
    if not material_recipe:
        return [], sorted(pieces)
    map_sets = _require_object(material_recipe.get("mapSets", {}), "materialRecipe.mapSets")
    materials = _require_object(material_recipe.get("materials", {}), "materialRecipe.materials")
    assigned: set[str] = set()
    result: list[dict[str, Any]] = []
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
            texture_root = f"{product_root}/Textures"
            entry["mapSet"] = map_set_name
            entry["textures"] = {
                "baseColor": f"{texture_root}/{map_set_name}_albedo.png",
                "normal": f"{texture_root}/{map_set_name}_normal.png",
                "roughness": f"{texture_root}/{map_set_name}_roughness.png",
            }
            entry["textureProvenance"] = map_set.get("provenance", {})
        result.append(entry)
    return result, sorted(set(pieces).difference(assigned))


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
    edge_maps = {piece_id: _edge_index(piece) for piece_id, piece in pieces.items()}
    units = str(pattern.get("units", ""))
    pattern_requests = []
    for piece_id, piece in sorted(pieces.items()):
        pattern_requests.append(
            {
                "pieceId": piece_id,
                "partId": str(piece.get("partId", "")),
                "pointsMm": _points_mm(piece, units),
                "grainAngleDegrees": float(piece.get("grainAngleDegrees", 0.0)),
                "cutCount": int(piece.get("cutCount", 1)),
                "onFold": bool(piece.get("onFold", False)),
                "namedEdges": edge_maps[piece_id],
            }
        )

    placements = {}
    if initialization:
        raw_placements = initialization.get("placements", {})
        if isinstance(raw_placements, Mapping):
            placements = {
                str(key): dict(value)
                for key, value in raw_placements.items()
                if key in pieces and isinstance(value, Mapping)
            }
    materials, unassigned = _material_requests(
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
        "units": {"canonical": "meter", "marvelousDesigner": "millimeter", "scale": 1000},
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
            "status": "BOUND" if materials else "UNVERIFIED",
            "definitions": materials,
            "unassignedPatterns": unassigned,
            "policy": "canonical-material-recipe-only",
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
