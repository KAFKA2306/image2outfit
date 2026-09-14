"""Marvelous Designer in-application executor for image2outfit request manifests.

Run this script from Marvelous Designer's Python environment (directly or through
an MCP/editor bridge). It refuses to simulate when canonical arrangement or
material realization is missing and never marks downstream image2outfit
verification as PASS.
"""

from __future__ import annotations

import hashlib
import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class ExecutionBlocked(RuntimeError):
    pass


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _request_hash(request: Mapping[str, Any]) -> str:
    copy = dict(request)
    copy.pop("requestSha256", None)
    return hashlib.sha256(_canonical_json(copy).encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _repo_path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    root = root.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ExecutionBlocked(f"path escapes repository: {relative}") from exc
    return candidate


def _status(name: str, state: str, **extra: Any) -> dict[str, Any]:
    return {"stage": name, "status": state, **extra}


def _inner_child(
    endpoint: Mapping[str, Any],
    internal_indices: Mapping[tuple[str, str], int],
) -> int:
    key = (str(endpoint["pieceId"]), str(endpoint["internalEdgeId"]))
    if key not in internal_indices:
        raise ExecutionBlocked(f"internal edge was not created: {key[0]}.{key[1]}")
    return internal_indices[key]


def _add_seam(
    pattern_api: Any,
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    pattern_indices: Mapping[str, int],
    internal_indices: Mapping[tuple[str, str], int],
) -> bool:
    first_pattern = pattern_indices[str(first["pieceId"])]
    second_pattern = pattern_indices[str(second["pieceId"])]
    first_line = int(first["lineIndex"])
    second_line = int(second["lineIndex"])
    first_direction = bool(first["direction"])
    second_direction = bool(second["direction"])
    first_kind = first["kind"]
    second_kind = second["kind"]

    if first_kind == "boundary" and second_kind == "boundary":
        return bool(
            pattern_api.AddSeamlinePairGroup(
                first_pattern,
                first_line,
                second_pattern,
                second_line,
                first_direction,
                second_direction,
            )
        )
    if first_kind == "boundary" and second_kind == "internal":
        return bool(
            pattern_api.AddSeamlinePairGroup(
                first_pattern,
                first_line,
                second_pattern,
                _inner_child(second, internal_indices),
                second_line,
                first_direction,
                second_direction,
            )
        )
    if first_kind == "internal" and second_kind == "boundary":
        # The official overload exposes boundary -> inner shape. Sewing is a pair,
        # so reverse argument order without changing each endpoint's direction.
        return bool(
            pattern_api.AddSeamlinePairGroup(
                second_pattern,
                second_line,
                first_pattern,
                _inner_child(first, internal_indices),
                first_line,
                second_direction,
                first_direction,
            )
        )
    if first_kind == "internal" and second_kind == "internal":
        return bool(
            pattern_api.AddSeamlinePairGroup(
                first_pattern,
                _inner_child(first, internal_indices),
                first_line,
                second_pattern,
                _inner_child(second, internal_indices),
                second_line,
                first_direction,
                second_direction,
            )
        )
    raise ExecutionBlocked(f"unsupported seam kinds: {first_kind!r}, {second_kind!r}")


def execute(request_path: str, repo_root: str) -> dict[str, Any]:
    request_file = Path(request_path).resolve()
    root = Path(repo_root).resolve()
    request = json.loads(request_file.read_text(encoding="utf-8"))
    expected = request.get("requestSha256")
    actual = _request_hash(request)
    if not isinstance(expected, str) or expected != actual:
        raise ExecutionBlocked("requestSha256 mismatch")
    if request.get("backend") != "marvelous-designer-python-api":
        raise ExecutionBlocked("unsupported backend")

    result_path = _repo_path(root, str(request["outputs"]["result"]))
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "productId": request.get("productId"),
        "requestSha256": expected,
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "executionStatus": "UNVERIFIED",
        "phases": [],
        "artifacts": {},
        "verifierStatus": "UNVERIFIED",
    }

    try:
        import ApiTypes  # type: ignore
        import export_api  # type: ignore
        import fabric_api  # type: ignore
        import import_api  # type: ignore
        import pattern_api  # type: ignore
        import utility_api  # type: ignore

        result["runtime"] = {
            "major": int(utility_api.GetMajorVersion()),
            "minor": int(utility_api.GetMinorVersion()),
        }
        utility_api.NewProject()
        result["phases"].append(_status("new-project", "PASS"))

        avatar_path = _repo_path(root, str(request["avatar"]["sourcePath"]))
        if not avatar_path.is_file():
            raise ExecutionBlocked(f"avatar not found: {avatar_path}")
        options = ApiTypes.ImportExportOption()
        if hasattr(options, "loadObjectType"):
            options.loadObjectType = 0
        if not import_api.ImportFBX(str(avatar_path), options):
            raise ExecutionBlocked("ImportFBX returned false")
        result["phases"].append(_status("avatar-import", "PASS", path=str(avatar_path)))

        pattern_indices: dict[str, int] = {}
        internal_indices: dict[tuple[str, str], int] = {}
        for spec in request.get("patterns", []):
            points = [tuple(point) for point in spec["pointsMm"]]
            pattern_index = int(pattern_api.CreatePatternWithPoints(points))
            if pattern_index < 0:
                raise ExecutionBlocked(f"pattern creation failed: {spec['pieceId']}")
            pattern_api.SetPatternPieceName(pattern_index, str(spec["pieceId"]))
            pattern_api.SetPatternPieceGrainDirection(
                pattern_index, float(spec.get("grainAngleDegrees", 0.0))
            )
            piece_id = str(spec["pieceId"])
            pattern_indices[piece_id] = pattern_index
            for internal in spec.get("internalLines", []):
                child_index = int(
                    pattern_api.CreateInternalShapeWithPoints(
                        pattern_index,
                        [tuple(point) for point in internal["pointsMm"]],
                        bool(internal.get("isClosed", False)),
                    )
                )
                if child_index < 0:
                    raise ExecutionBlocked(
                        f"internal shape creation failed: {piece_id}.{internal['edgeId']}"
                    )
                internal_indices[(piece_id, str(internal["edgeId"]))] = child_index
        result["phases"].append(
            _status(
                "pattern-create",
                "PASS",
                patternCount=len(pattern_indices),
                internalLineCount=len(internal_indices),
            )
        )

        arrangement = request.get("arrangement", {})
        placements = arrangement.get("placements", {}) if isinstance(arrangement, dict) else {}
        if arrangement.get("status") != "BOUND" or not placements:
            raise ExecutionBlocked(
                "canonical initialize-3d output is not bound; simulation stays UNVERIFIED"
            )
        missing_placements = sorted(set(pattern_indices).difference(placements))
        if missing_placements:
            raise ExecutionBlocked(
                "canonical arrangement is incomplete for patterns: "
                + ", ".join(missing_placements)
            )
        for piece_id, placement in placements.items():
            pattern_index = pattern_indices[piece_id]
            if "arrangementIndex" not in placement:
                raise ExecutionBlocked(
                    f"placement {piece_id!r} lacks arrangementIndex; do not guess MD placement"
                )
            pattern_api.SetArrangement(pattern_index, int(placement["arrangementIndex"]))
            if all(key in placement for key in ("positionX", "positionY", "offset")):
                pattern_api.SetArrangementPosition(
                    pattern_index,
                    int(placement["positionX"]),
                    int(placement["positionY"]),
                    int(placement["offset"]),
                )
            if "orientation" in placement:
                pattern_api.SetArrangementOrientation(pattern_index, int(placement["orientation"]))
        result["phases"].append(
            _status("arrangement", "PASS", placementCount=len(placements))
        )

        seam_count = 0
        for stitch in request.get("stitches", []):
            for segment in stitch.get("segments", []):
                if not _add_seam(
                    pattern_api,
                    segment["first"],
                    segment["second"],
                    pattern_indices,
                    internal_indices,
                ):
                    raise ExecutionBlocked(f"sewing failed: {stitch['stitchId']}")
                seam_count += 1
        result["phases"].append(_status("sewing", "PASS", segmentCount=seam_count))

        materials = request.get("materials", {})
        if materials.get("status") != "BOUND":
            missing = materials.get("unassignedPatterns", [])
            suffix = f"; unassigned={missing}" if missing else ""
            raise ExecutionBlocked(
                "canonical realized PBR textures are not fully bound" + suffix
            )
        material_root = _repo_path(root, str(request["outputs"]["root"])) / "fabrics"
        material_root.mkdir(parents=True, exist_ok=True)
        for definition in materials.get("definitions", []):
            patterns = definition.get("patterns", [])
            if not patterns:
                continue
            textures = definition.get("textures")
            if not isinstance(textures, Mapping):
                raise ExecutionBlocked(
                    f"material {definition['role']!r} has no realized texture binding"
                )
            required = ("baseColor", "normal", "roughness")
            missing = [
                key
                for key in required
                if key not in textures or not _repo_path(root, str(textures[key])).is_file()
            ]
            if missing:
                raise ExecutionBlocked(
                    f"material {definition['role']!r} missing required textures: {', '.join(missing)}"
                )
            zfab_path = material_root / f"{definition['role']}.zfab"
            optional = {
                name: textures.get(name, "")
                for name in ("displacement", "opacity", "metalness")
            }
            ok = fabric_api.CreateZfabFromTextures(
                str(zfab_path),
                str(_repo_path(root, str(textures["baseColor"]))),
                str(_repo_path(root, str(textures["normal"]))),
                str(_repo_path(root, str(optional["displacement"])))
                if optional["displacement"]
                else "",
                str(_repo_path(root, str(optional["opacity"]))) if optional["opacity"] else "",
                str(_repo_path(root, str(textures["roughness"]))),
                str(_repo_path(root, str(optional["metalness"]))) if optional["metalness"] else "",
            )
            if not ok:
                raise ExecutionBlocked(f"CreateZfabFromTextures failed: {definition['role']}")
            fabric_index = int(fabric_api.AddFabric(str(zfab_path)))
            if fabric_index < 0:
                raise ExecutionBlocked(f"AddFabric failed: {definition['role']}")
            for piece_id in patterns:
                if not fabric_api.AssignFabricToPattern(
                    fabric_index, pattern_indices[piece_id], 1
                ):
                    raise ExecutionBlocked(
                        f"AssignFabricToPattern failed: {definition['role']} -> {piece_id}"
                    )
        result["phases"].append(_status("materials", "PASS"))

        simulation = request["simulation"]
        utility_api.SetSimulationQuality(
            int(simulation["quality"]), int(simulation["mode"])
        )
        utility_api.SetSimulationTimeStep(float(simulation["timeStep"]))
        utility_api.SetSimulationNumberOfSimulation(int(simulation["substeps"]))
        if not utility_api.Simulate(int(simulation["steps"])):
            raise ExecutionBlocked("Simulate returned false")
        result["phases"].append(
            _status("simulation", "PASS", steps=int(simulation["steps"]))
        )

        export_options = ApiTypes.ImportExportOption()
        export_paths = {
            "project": _repo_path(root, str(request["outputs"]["project"])),
            "obj": _repo_path(root, str(request["outputs"]["obj"])),
            "fbx": _repo_path(root, str(request["outputs"]["fbx"])),
        }
        for path in export_paths.values():
            path.parent.mkdir(parents=True, exist_ok=True)
        if not export_api.ExportZPrj(str(export_paths["project"]), False):
            raise ExecutionBlocked("ExportZPrj failed")
        if not export_api.ExportOBJ(str(export_paths["obj"]), export_options):
            raise ExecutionBlocked("ExportOBJ failed")
        if not export_api.ExportFBX(str(export_paths["fbx"]), export_options):
            raise ExecutionBlocked("ExportFBX failed")
        for name, path in export_paths.items():
            if not path.is_file():
                raise ExecutionBlocked(f"exported {name} artifact not found: {path}")
            result["artifacts"][name] = {
                "path": str(path.relative_to(root)),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
        result["phases"].append(_status("export", "PASS"))
        result["executionStatus"] = "PASS"
    except ExecutionBlocked as exc:
        result["executionStatus"] = "UNVERIFIED"
        result["blocker"] = str(exc)
    except Exception as exc:
        result["executionStatus"] = "FAIL"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()
    finally:
        result["finishedAt"] = datetime.now(timezone.utc).isoformat()
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return result


if __name__ == "__main__":
    raise SystemExit(
        "Run execute(request_path, repo_root) from Marvelous Designer's Python environment."
    )
