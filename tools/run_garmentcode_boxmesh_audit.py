#!/usr/bin/env python3
"""Audit a strict stitch graph with the pinned GarmentCode BoxMesh runtime."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mesh-output", type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--upstream-root", required=True, type=Path)
    parser.add_argument("--upstream-revision", required=True)
    parser.add_argument("--python-version", required=True)
    parser.add_argument("--pygarment-version", required=True)
    parser.add_argument("--requirements-lock", required=True, type=Path)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def validate_runtime(args: argparse.Namespace) -> tuple[str, str]:
    actual_python = sys.version.split()[0]
    if actual_python != args.python_version:
        raise RuntimeError(
            f"expected Python {args.python_version}, found {actual_python}"
        )

    mismatches: list[str] = []
    for line in args.requirements_lock.read_text(encoding="utf-8").splitlines():
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
    return actual_python, sha256(args.requirements_lock.resolve())


def _mapped_stitch_ids(pattern: dict[str, Any], adapter: dict[str, Any]) -> list[str]:
    stitches = pattern.get("stitches")
    mappings = adapter.get("stitchMapping")
    if not isinstance(stitches, list) or not isinstance(mappings, list):
        raise ValueError("BoxMesh audit requires the submitted stitch graph mapping")
    if len(stitches) != len(mappings):
        raise ValueError("BoxMesh stitch count differs from the canonical mapping")
    if adapter.get("canonicalStitchCount") != len(stitches):
        raise ValueError("BoxMesh stitch count differs from the canonical count")

    stitch_ids: list[str] = []
    for index, (pair, mapping) in enumerate(zip(stitches, mappings)):
        if (
            not isinstance(pair, list)
            or len(pair) not in (2, 3)
            or (len(pair) == 3 and pair[2] != "right_wrong")
            or not isinstance(mapping, dict)
            or mapping.get("garmentCodeStitchIndex") != index
            or not isinstance(mapping.get("stitchId"), str)
        ):
            raise ValueError(f"BoxMesh stitch mapping {index} is invalid")
        stitch_ids.append(mapping["stitchId"])
    return stitch_ids


def _stitch_diagnostics(mesh: Any, stitch_ids: list[str], same_panel: Any) -> dict[str, Any]:
    _valid, invalid_indices = mesh._is_stitching_valid(same_panel)
    invalid = []
    front_end_collapse_count = 0
    shared_panel_conflict_count = 0
    for index in invalid_indices:
        stitch = mesh.stitches[index]
        front_valid = mesh._valid_stitch_front_end(stitch)
        panel_valid = mesh._valid_stitch_same_panel(stitch, same_panel)
        front_end_collapse_count += int(not front_valid)
        shared_panel_conflict_count += int(not panel_valid)
        pair = mesh.pattern["stitches"][index]
        invalid.append(
            {
                "stitchId": stitch_ids[index],
                "edgeReferences": [
                    {"panel": item["panel"], "edge": item["edge"]}
                    for item in pair[:2]
                ],
                "rightWrongTag": len(pair) == 3 and pair[2] == "right_wrong",
                "frontEndCollapse": not front_valid,
                "sharedPanelEndpointConflict": not panel_valid,
            }
        )
    return {
        "invalidStitchCount": len(invalid),
        "invalidStitches": invalid,
        "frontEndCollapseCount": front_end_collapse_count,
        "sharedPanelEndpointConflictCount": shared_panel_conflict_count,
    }


def _endpoint_conflict_clusters(
    mesh: Any,
    stitch_ids: list[str],
    same_panel: Any,
    invalid_indices: list[int],
    panel_key_map: dict[str, str],
) -> list[dict[str, Any]]:
    """Group invalid stitch endpoints by the native BoxMesh vertex they collapse to."""
    clusters: dict[int, dict[str, Any]] = {}
    for stitch_index in invalid_indices:
        stitch = mesh.stitches[stitch_index]
        for panel_name, edge_index in (
            (stitch.panel_1, stitch.edge_1),
            (stitch.panel_2, stitch.edge_2),
        ):
            edge = mesh.panels[panel_name].edges[edge_index]
            for endpoint, local_id in (
                ("start", edge.vertex_range[0]),
                ("end", edge.vertex_range[-1]),
            ):
                global_id = int(mesh.verts_loc_glob[(panel_name, local_id)])
                local_members = mesh.verts_glob_loc[global_id]
                panel_conflicts = []
                for member_panel, member_ids in mesh._group_same_panel_stiches(
                    local_members
                ):
                    if mesh.check_local_vertices_stitching(
                        same_panel, member_panel, member_ids
                    ):
                        panel_conflicts.append(
                            {
                                "panel": member_panel,
                                "garmentPieceId": panel_key_map[member_panel],
                                "localVertexIds": sorted(int(value) for value in member_ids),
                            }
                        )
                if not panel_conflicts:
                    continue

                cluster = clusters.setdefault(
                    global_id,
                    {
                        "inMemoryGlobalVertexId": global_id,
                        "mergedLocalVertices": [
                            {
                                "panel": member_panel,
                                "garmentPieceId": panel_key_map[member_panel],
                                "localVertexId": int(member_id),
                            }
                            for member_panel, member_id in local_members
                        ],
                        "samePanelConflicts": {},
                        "affectedStitchIds": set(),
                        "endpointUses": [],
                    },
                )
                cluster["affectedStitchIds"].add(stitch_ids[stitch_index])
                cluster["endpointUses"].append(
                    {
                        "stitchId": stitch_ids[stitch_index],
                        "panel": panel_name,
                        "garmentPieceId": panel_key_map[panel_name],
                        "edge": int(edge_index),
                        "endpoint": endpoint,
                        "localVertexId": int(local_id),
                    }
                )
                for conflict in panel_conflicts:
                    key = (conflict["panel"], tuple(conflict["localVertexIds"]))
                    cluster["samePanelConflicts"][key] = conflict

    output = []
    for global_id in sorted(clusters):
        cluster = clusters[global_id]
        output.append(
            {
                "inMemoryGlobalVertexId": cluster["inMemoryGlobalVertexId"],
                "mergedLocalVertices": cluster["mergedLocalVertices"],
                "samePanelConflicts": [
                    cluster["samePanelConflicts"][key]
                    for key in sorted(cluster["samePanelConflicts"])
                ],
                "affectedStitchIds": sorted(cluster["affectedStitchIds"]),
                "endpointUses": sorted(
                    cluster["endpointUses"],
                    key=lambda item: (
                        item["stitchId"],
                        item["panel"],
                        item["edge"],
                        item["endpoint"],
                    ),
                ),
                "scope": "in-memory endpoint incidence; no mesh finalization or topology approval",
            }
        )
    return output


def _intentional_closed_loop_stitches(
    mesh: Any,
    stitch_ids: list[str],
    same_panel: Any,
    invalid_indices: list[int],
) -> list[dict[str, Any]]:
    """Recognize sewn boundary loops without treating them as a topology pass."""
    closed_loops: list[dict[str, Any]] = []
    for index in invalid_indices:
        stitch = mesh.stitches[index]
        if mesh._valid_stitch_front_end(stitch):
            continue
        if not mesh._valid_stitch_same_panel(stitch, same_panel):
            continue

        range_1, range_2 = mesh._swap_stitch_ranges(stitch)
        chain_1 = [
            mesh.verts_loc_glob[(stitch.panel_1, local_id)]
            for local_id in range_1
        ]
        chain_2 = [
            mesh.verts_loc_glob[(stitch.panel_2, local_id)]
            for local_id in range_2
        ]
        if len(chain_1) < 4 or len(chain_1) != len(chain_2):
            continue
        if chain_1[0] != chain_1[-1] or chain_2[0] != chain_2[-1]:
            continue
        if chain_1 != chain_2:
            continue
        if any(first == second for first, second in zip(chain_1, chain_1[1:])):
            continue
        if len(set(chain_1[:-1])) != len(chain_1) - 1:
            continue

        closed_loops.append(
            {
                "stitchId": stitch_ids[index],
                "panelEdgeReferences": [
                    {"panel": stitch.panel_1, "edge": stitch.edge_1},
                    {"panel": stitch.panel_2, "edge": stitch.edge_2},
                ],
                "pairedSampleCount": len(chain_1),
                "pairedGlobalVertexIdsMatch": True,
                "closedAtBothEnds": True,
                "consecutiveDuplicateVertexCount": 0,
                "distinctLoopVertexCount": len(set(chain_1[:-1])),
                "nonLoopStitchConflict": False,
                "evaluationLimit": (
                    "Classifies endpoint closure only; it does not approve sewn-face area, "
                    "manifold topology, panel pose, fit, or cloth simulation."
                ),
            }
        )
    return closed_loops


def _finalized_mesh_topology(mesh: Any, panel_key_map: dict[str, str]) -> dict[str, Any]:
    vertices = [tuple(float(value) for value in vertex) for vertex in mesh.vertices]
    faces = [[int(value) for value in face] for face in mesh.faces]
    if vertices:
        bounds = [
            (min(vertex[axis] for vertex in vertices), max(vertex[axis] for vertex in vertices))
            for axis in range(3)
        ]
        bbox_diagonal = math.sqrt(
            sum((maximum - minimum) ** 2 for minimum, maximum in bounds)
        )
    else:
        bbox_diagonal = 0.0
    area_tolerance = max(1e-12, bbox_diagonal * bbox_diagonal * 1e-12)
    degenerate_face_count = 0
    degenerate_face_records = []
    face_owners = []
    for panel_name, panel in mesh.panels.items():
        for local_face in panel.panel_faces:
            global_face = mesh._get_glob_ids(panel, local_face)
            if len(set(global_face)) == 3:
                face_owners.append(panel_key_map[panel_name])
    if len(face_owners) != len(faces):
        raise ValueError("Finalized face ownership does not match BoxMesh topology")
    edge_incidence: dict[tuple[int, int], int] = {}
    for face_index, face in enumerate(faces):
        before_count = degenerate_face_count
        if len(face) != 3 or len(set(face)) != 3:
            degenerate_face_count += 1
        else:
            a, b, c = (vertices[vertex_id] for vertex_id in face)
            ab = tuple(b[axis] - a[axis] for axis in range(3))
            ac = tuple(c[axis] - a[axis] for axis in range(3))
            cross = (
                ab[1] * ac[2] - ab[2] * ac[1],
                ab[2] * ac[0] - ab[0] * ac[2],
                ab[0] * ac[1] - ab[1] * ac[0],
            )
            area = 0.5 * math.sqrt(sum(component * component for component in cross))
            if area <= area_tolerance:
                degenerate_face_count += 1
        if degenerate_face_count != before_count:
            degenerate_face_records.append({
                "faceIndex": face_index, "pieceId": face_owners[face_index],
                "vertexIds": face,
                "positionsNativeUnits": [vertices[vertex_id] for vertex_id in face],
            })
        for edge_index, vertex_id in enumerate(face):
            next_vertex_id = face[(edge_index + 1) % len(face)]
            edge = tuple(sorted((vertex_id, next_vertex_id)))
            edge_incidence[edge] = edge_incidence.get(edge, 0) + 1

    incidence_histogram: dict[str, int] = {}
    for count in edge_incidence.values():
        key = str(count)
        incidence_histogram[key] = incidence_histogram.get(key, 0) + 1
    return {
        "vertexCount": len(vertices),
        "faceCount": len(faces),
        "bboxDiagonal": bbox_diagonal,
        "degenerateAreaTolerance": area_tolerance,
        "degenerateFaceCount": degenerate_face_count,
        "degenerateFaceRecords": degenerate_face_records,
        "facePieceIds": face_owners,
        "uniqueUndirectedEdgeCount": len(edge_incidence),
        "edgeIncidenceHistogram": incidence_histogram,
        "boundaryEdgeCount": sum(count == 1 for count in edge_incidence.values()),
        "nonManifoldEdgeCount": sum(count > 2 for count in edge_incidence.values()),
    }


def _panel_pose_input_audit(pattern: dict[str, Any]) -> dict[str, Any]:
    panels = pattern.get("panels")
    if not isinstance(panels, dict) or not panels:
        return {
            "status": "UNAVAILABLE",
            "panelCount": 0,
            "rotationDeclaredCount": 0,
            "translationDeclaredCount": 0,
            "zeroRotationPanelCount": 0,
            "rotationDistinctCount": 0,
            "translationDistinctCount": 0,
            "interpretation": "Panel transforms are required to interpret the BoxMesh preflight input.",
        }

    rotations: list[tuple[float, float, float]] = []
    translations: list[tuple[float, float, float]] = []
    missing_rotation: list[str] = []
    missing_translation: list[str] = []
    for panel_name, panel in panels.items():
        if not isinstance(panel, dict):
            missing_rotation.append(str(panel_name))
            missing_translation.append(str(panel_name))
            continue
        for field, values, missing in (
            ("rotation", rotations, missing_rotation),
            ("translation", translations, missing_translation),
        ):
            raw = panel.get(field)
            if (
                not isinstance(raw, list)
                or len(raw) != 3
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    for value in raw
                )
            ):
                missing.append(str(panel_name))
                continue
            values.append(tuple(round(float(value), 9) for value in raw))

    zero_rotation_count = sum(
        int(all(abs(value) <= 1e-9 for value in rotation))
        for rotation in rotations
    )
    all_rotations_zero = len(rotations) == len(panels) and zero_rotation_count == len(panels)
    status = "COMPLETE" if not missing_rotation and not missing_translation else "INCOMPLETE"
    return {
        "status": status,
        "panelCount": len(panels),
        "rotationDeclaredCount": len(rotations),
        "translationDeclaredCount": len(translations),
        "zeroRotationPanelCount": zero_rotation_count,
        "rotationDistinctCount": len(set(rotations)),
        "translationDistinctCount": len(set(translations)),
        "allRotationsZero": all_rotations_zero,
        "panelsMissingRotation": missing_rotation,
        "panelsMissingTranslation": missing_translation,
        "interpretation": (
            "Panel-transform distribution only; a nonzero panel rotation does not prove a valid assembled garment pose, and an all-zero rotation set flags that the flat 2D layout has no panel-specific orientation for this in-memory BoxMesh audit."
        ),
    }


def _initialize_cylindrical_panels(mesh, pattern, scale):
    """Wrap explicit sleeve panels before BoxMesh averages the sewn vertices.

    Keep the upstream 2D panel vertices and edge rest lengths unchanged. Only
    the 2D-to-3D placement function changes, including its use at sewn seams.
    """
    import numpy as np
    from types import MethodType

    records = []
    for name, source in pattern["panels"].items():
        collar = source.get("image2outfitCollarWrap")
        if collar is not None:
            if collar["method"] != "pattern-length-standing-collar" or any(source.get(key) for key in ["image2outfitSkirtWrap", "image2outfitLegWrap", "image2outfitTorsoWrap", "image2outfitCylindricalWrap"]):
                raise ValueError("Unknown or conflicting collar placement")
            anchor = np.array(collar["axisAnchorGarmentCodeM"], dtype=float)*scale
            length = float(collar["circumferenceLocalYM"])*scale
            if anchor.shape != (3,) or not np.isfinite(anchor).all() or not math.isfinite(length) or length <= 0:
                raise ValueError("Invalid collar placement bounds")
            def collar_transform(panel, vertex, anchor=anchor, length=length):
                x, y = vertex
                angle = 2*math.pi*y/length
                radius = length/(2*math.pi)
                # Pattern -X is collar height; +Y traverses front-left,
                # back-left, back-right, front-right sewn base quarters.
                return anchor+np.array([radius*math.sin(angle), -x, radius*math.cos(angle)])
            panel = mesh.panels[name]
            panel.rot_trans_vertex = MethodType(collar_transform, panel)
            panel.rot_trans_panel = MethodType(lambda panel, vertices: np.array([panel.rot_trans_vertex(v) for v in vertices]), panel)
            panel.image2outfit_cylindrical = True
            panel.image2outfit_reverse_winding = False
            records.append({"panel":name,"specification":collar,"vertexCount":len(panel.panel_vertices),"changes2dRestLengths":False,"grantsFitAcceptance":False})
            continue
        skirt = source.get("image2outfitSkirtWrap")
        if skirt is not None:
            if skirt["method"] != "pattern-half-circumference-skirt" or any(source.get(key) for key in ["image2outfitLegWrap", "image2outfitTorsoWrap", "image2outfitCylindricalWrap"]):
                raise ValueError("Unknown or conflicting skirt placement")
            depth = skirt["depthDirection"]
            anchor = np.array(skirt["axisAnchorGarmentCodeM"], dtype=float)*scale
            profile = np.array(skirt["widthRadiusProfileM"], dtype=float)*scale
            if depth not in (-1, 1) or anchor.shape != (3,) or profile.shape != (2, 3):
                raise ValueError("Invalid skirt placement specification")
            if not np.isfinite(anchor).all() or not np.isfinite(profile).all() or np.any(np.diff(profile[:,0]) <= 0) or np.any(profile[:,1:] <= 0):
                raise ValueError("Invalid skirt placement bounds")
            width_curve = skirt.get("widthQuadraticControlM")
            if width_curve is not None:
                width_curve = np.array(width_curve, dtype=float)*scale
                if width_curve.shape != (3,) or not np.isfinite(width_curve).all() or np.any(width_curve <= 0):
                    raise ValueError("Invalid skirt quadratic half-width controls")
                if abs(width_curve[0]-profile[-1,1]) > 1e-7 or abs(width_curve[2]-profile[0,1]) > 1e-7:
                    raise ValueError("Skirt quadratic half-width endpoints differ from profile")
            def skirt_transform(panel, vertex, depth=depth, anchor=anchor, profile=profile, width_curve=width_curve):
                x, y = vertex
                width = np.interp(y, profile[:,0], profile[:,1])
                if width_curve is not None:
                    t = (profile[-1,0]-y)/(profile[-1,0]-profile[0,0])
                    if not -1e-7 <= t <= 1+1e-7:
                        raise ValueError("Skirt vertex outside quadratic width bounds")
                    t = min(1.0, max(0.0, t))
                    width = (1-t)**2*width_curve[0]+2*t*(1-t)*width_curve[1]+t*t*width_curve[2]
                radius = np.interp(y, profile[:,0], profile[:,2])
                angle = x/width*math.pi/2
                return anchor+np.array([radius*math.sin(angle), y, depth*radius*math.cos(angle)])
            panel = mesh.panels[name]
            panel.rot_trans_vertex = MethodType(skirt_transform, panel)
            panel.rot_trans_panel = MethodType(lambda panel, vertices: np.array([panel.rot_trans_vertex(v) for v in vertices]), panel)
            panel.image2outfit_cylindrical = True
            panel.image2outfit_reverse_winding = depth < 0
            records.append({"panel":name,"specification":skirt,"vertexCount":len(panel.panel_vertices),"changes2dRestLengths":False,"grantsFitAcceptance":False})
            continue
        leg = source.get("image2outfitLegWrap")
        if leg is not None:
            if leg["method"] != "pattern-half-leg-to-quarter-pelvis" or source.get("image2outfitTorsoWrap") or source.get("image2outfitCylindricalWrap"):
                raise ValueError("Unknown or conflicting shorts placement")
            side, depth = leg["sideDirection"], leg["depthDirection"]
            anchor = np.array(leg["axisAnchorGarmentCodeM"], dtype=float)*scale
            profile = np.array(leg["widthBoundsProfileM"], dtype=float)*scale
            start, end = np.array(leg["pelvisBlendLocalYM"], dtype=float)*scale
            if side not in (-1, 1) or depth not in (-1, 1) or anchor.shape != (3,) or profile.shape != (3, 3):
                raise ValueError("Invalid shorts placement specification")
            if not np.isfinite(anchor).all() or not np.isfinite(profile).all() or not math.isfinite(start+end) or not start < end or np.any(np.diff(profile[:,0]) <= 0) or np.any(profile[:,2] <= profile[:,1]):
                raise ValueError("Invalid shorts placement bounds")
            def leg_transform(panel, vertex, side=side, depth=depth, anchor=anchor, profile=profile, start=start, end=end):
                x, y = vertex
                inner = np.interp(y, profile[:,0], profile[:,1])
                outer = np.interp(y, profile[:,0], profile[:,2])
                width = outer-inner
                fraction = (x-inner)/width
                radius = width/math.pi
                angle = fraction*math.pi
                lower = np.array([side*(abs(anchor[0])-radius*math.cos(angle)), y+anchor[1], anchor[2]+depth*radius*math.sin(angle)])
                # At the waist, front/back become pelvis quarters. At the
                # crotch tip each leg retains its half-cylinder inseam.
                blend = min(1, max(0, (y-start)/(end-start)))
                upper_radius = 2*width/math.pi
                upper_angle = fraction*math.pi/2
                upper = np.array([side*upper_radius*math.sin(upper_angle), y+anchor[1], anchor[2]+depth*upper_radius*math.cos(upper_angle)])
                return lower*(1-blend)+upper*blend
            panel = mesh.panels[name]
            panel.rot_trans_vertex = MethodType(leg_transform, panel)
            panel.rot_trans_panel = MethodType(lambda panel, vertices: np.array([panel.rot_trans_vertex(v) for v in vertices]), panel)
            panel.image2outfit_cylindrical = True
            panel.image2outfit_reverse_winding = side*depth < 0
            records.append({"panel":name,"specification":leg,"vertexCount":len(panel.panel_vertices),"changes2dRestLengths":False,"grantsFitAcceptance":False})
            continue
        torso = source.get("image2outfitTorsoWrap")
        if torso is not None:
            if source.get("image2outfitCylindricalWrap") is not None:
                raise ValueError("Panel cannot use two nonlinear placement methods")
            if torso["method"] != "pattern-quarter-circumference-torso" or torso["upperProfileExtrapolation"] != "hold-final-quarter-width":
                raise ValueError("Unknown torso placement method")
            side, depth = torso["sideDirection"], torso["depthDirection"]
            anchor = np.array(torso["axisAnchorGarmentCodeM"], dtype=float)*scale
            profile = np.array(torso["quarterWidthProfileM"], dtype=float)*scale
            if side not in (-1, 1) or depth not in (-1, 1) or anchor.shape != (3,) or profile.ndim != 2 or profile.shape[1] != 2 or len(profile) < 2:
                raise ValueError("Invalid torso placement specification")
            if not np.isfinite(anchor).all() or not np.isfinite(profile).all() or np.any(profile[:,1] <= 0) or np.any(np.diff(profile[:,0]) <= 0):
                raise ValueError("Invalid torso quarter-width profile")
            neckline = torso.get("necklineWrap")
            if neckline is not None:
                if neckline["method"] != "collar-base-quarter-ring-with-local-blend":
                    raise ValueError("Unknown neckline placement method")
                edge = np.array(neckline["patternEdgeM"], dtype=float)*scale
                ring = np.array(neckline["axisAnchorGarmentCodeM"], dtype=float)*scale
                angles = np.array(neckline["edgeAnglesRadians"], dtype=float)
                ring_radius = float(neckline["circumferenceM"])*scale/(2*math.pi)
                blend_distance = float(neckline["blendDistanceM"])*scale
                if edge.shape != (2,2) or ring.shape != (3,) or angles.shape != (2,) or not np.isfinite(np.concatenate((edge.ravel(),ring,angles,[ring_radius,blend_distance]))).all() or ring_radius <= 0 or blend_distance <= 0 or np.linalg.norm(edge[1]-edge[0]) <= 0:
                    raise ValueError("Invalid neckline ring specification")
            shoulder = torso.get("shoulderPlacement")
            if shoulder is not None:
                if shoulder["method"] != "measured-shoulder-to-collar-edge":
                    raise ValueError("Unknown shoulder placement method")
                shoulder_edge = np.array(shoulder["patternEdgeM"], dtype=float)*scale
                shoulder_targets = np.array(shoulder["edgeTargetsGarmentCodeM"], dtype=float)*scale
                shoulder_fade = float(shoulder["blendDistanceM"])*scale
                if shoulder_edge.shape != (2,2) or shoulder_targets.shape != (2,3) or not np.isfinite(np.concatenate((shoulder_edge.ravel(), shoulder_targets.ravel(), [shoulder_fade]))).all() or shoulder_fade <= 0 or np.linalg.norm(shoulder_edge[1]-shoulder_edge[0]) <= 0:
                    raise ValueError("Invalid measured shoulder placement specification")
            armhole = torso.get("armholePlacement")
            if armhole is not None:
                if armhole["method"] != "measured-radial-section-paired-armscye":
                    raise ValueError("Unknown measured armhole placement")
                fade = float(armhole["blendDistanceM"])
                if not math.isfinite(fade) or fade <= 0 or len(armhole["edges"]) != 2:
                    raise ValueError("Invalid armhole transition")
                for item in armhole["edges"]:
                    edge = np.array(item["patternEdgeM"], dtype=float)
                    targets = np.array(item["targetPolylineGarmentCodeM"], dtype=float)
                    if edge.shape != (2, 2) or targets.ndim != 2 or targets.shape[1] != 3 or len(targets) < 2 or not np.isfinite(np.concatenate((edge.ravel(), targets.ravel()))).all() or np.linalg.norm(edge[1]-edge[0]) <= 0:
                        raise ValueError("Invalid armhole curve")
                if not np.allclose(armhole["edges"][0]["targetPolylineGarmentCodeM"][-1], armhole["edges"][1]["targetPolylineGarmentCodeM"][0], atol=1e-9):
                    raise ValueError("Disconnected armhole curves")
            def torso_transform(panel, vertex, anchor=anchor, profile=profile, side=side, depth=depth, neckline=neckline, shoulder=shoulder, armhole=armhole):
                x, y = vertex
                width = np.interp(y, profile[:,0], profile[:,1])
                radius = width*2/math.pi
                angle = x/radius
                result = anchor + np.array([side*radius*math.sin(angle), y, depth*radius*math.cos(angle)])
                if shoulder is not None:
                    edge = np.array(shoulder["patternEdgeM"], dtype=float)*scale
                    targets = np.array(shoulder["edgeTargetsGarmentCodeM"], dtype=float)*scale
                    delta = edge[1]-edge[0]
                    fraction = min(1, max(0, np.dot(np.array(vertex)-edge[0],delta)/np.dot(delta,delta)))
                    distance = np.linalg.norm(np.array(vertex)-(edge[0]+fraction*delta))
                    influence = max(0, 1-distance/(shoulder["blendDistanceM"]*scale))
                    influence = influence*influence*(3-2*influence)
                    target = targets[0]*(1-fraction)+targets[1]*fraction
                    result = result*(1-influence)+target*influence
                if neckline is not None:
                    # Bind captured per-panel data; closures must not reuse
                    # another quarter's edge or ring during sewn averaging.
                    edge = np.array(neckline["patternEdgeM"])*scale
                    ring = np.array(neckline["axisAnchorGarmentCodeM"])*scale
                    delta = edge[1]-edge[0]
                    fraction = min(1, max(0, np.dot(np.array(vertex)-edge[0],delta)/np.dot(delta,delta)))
                    nearest = edge[0]+fraction*delta
                    distance = np.linalg.norm(np.array(vertex)-nearest)
                    blend = max(0, 1-distance/(neckline["blendDistanceM"]*scale))
                    angle = np.interp(fraction,[0,1],neckline["edgeAnglesRadians"])
                    radius = neckline["circumferenceM"]*scale/(2*math.pi)
                    target = ring+np.array([radius*math.sin(angle),0,radius*math.cos(angle)])
                    result = result*(1-blend)+target*blend
                if armhole is not None:
                    candidates = []
                    for item in armhole["edges"]:
                        edge = np.array(item["patternEdgeM"])*scale
                        targets = np.array(item["targetPolylineGarmentCodeM"])*scale
                        delta = edge[1]-edge[0]
                        fraction = min(1, max(0, np.dot(np.array(vertex)-edge[0],delta)/np.dot(delta,delta)))
                        distance = np.linalg.norm(np.array(vertex)-(edge[0]+fraction*delta))
                        position = fraction*(len(targets)-1)
                        index = min(len(targets)-2, int(position))
                        mix = position-index
                        target = targets[index]*(1-mix)+targets[index+1]*mix
                        candidates.append((distance, target))
                    distance, target = min(candidates, key=lambda row: row[0])
                    weight = max(0, 1-distance/(armhole["blendDistanceM"]*scale))
                    weight = weight*weight*(3-2*weight)
                    result = result*(1-weight)+target*weight
                return result
            panel = mesh.panels[name]
            panel.rot_trans_vertex = MethodType(torso_transform, panel)
            panel.rot_trans_panel = MethodType(lambda panel, vertices: np.array([panel.rot_trans_vertex(v) for v in vertices]), panel)
            panel.image2outfit_cylindrical = True
            # Outward winding differs for each quadrant.
            panel.image2outfit_reverse_winding = side*depth < 0
            records.append({"panel":name,"specification":torso,"vertexCount":len(panel.panel_vertices),"changes2dRestLengths":False,"grantsFitAcceptance":False})
            continue
        spec = source.get("image2outfitCylindricalWrap")
        if spec is None:
            continue
        if spec["method"] != "local-width-preserving-sleeve-cylinder":
            raise ValueError("Unknown cylindrical placement method")
        sign = spec["axisDirection"]
        if sign not in (-1, 1):
            raise ValueError("Cylinder axis direction must be signed")
        anchor = np.array(spec["axisAnchorGarmentCodeM"], dtype=float) * scale
        cap = float(spec["capLocalYM"]) * scale
        base = float(spec["tubeBaseLocalYM"]) * scale
        cuff = float(spec["cuffLocalYM"]) * scale
        cap_depth = float(spec.get("capAxisDepthM", spec["capLocalYM"] - spec["tubeBaseLocalYM"])) * scale
        cuff_bounds = np.array(spec["cuffBoundsXM"], dtype=float) * scale
        base_bounds = np.array(spec["tubeBaseBoundsXM"], dtype=float) * scale
        if not np.isfinite(np.concatenate((anchor, cuff_bounds, base_bounds, [cap, base, cuff]))).all():
            raise ValueError("Nonfinite cylindrical placement")
        if not cap > base > cuff or not cuff_bounds[1] > cuff_bounds[0] or not base_bounds[1] > base_bounds[0]:
            raise ValueError("Invalid sleeve cylinder bounds")
        if not math.isfinite(cap_depth) or not 0 < cap_depth <= cap-base:
            raise ValueError("Invalid sleeve cap axial depth")
        cuff_axis = float(spec.get("cuffAxisDistanceM", spec["capLocalYM"]-spec["cuffLocalYM"])) * scale
        if not math.isfinite(cuff_axis) or cuff_axis <= cap_depth:
            raise ValueError("Invalid explicit sleeve cuff distance")
        orientation = spec.get("circumferenceOrientation", "apex-anterior-seam-posterior")
        if orientation not in {"apex-anterior-seam-posterior", "apex-superior-seam-inferior-front-anterior"}:
            raise ValueError("Unknown sleeve circumference orientation")
        apex_up = orientation == "apex-superior-seam-inferior-front-anterior"
        width_profile = None
        if "tubeWidthBoundsProfileM" in spec:
            width_profile = np.array(spec["tubeWidthBoundsProfileM"], dtype=float) * scale
            if (width_profile.ndim != 2 or width_profile.shape[1] != 3
                    or len(width_profile) < 2 or not np.isfinite(width_profile).all()
                    or not np.all(np.diff(width_profile[:, 0]) > 0)
                    or not np.all(width_profile[:, 2] > width_profile[:, 1])
                    or not np.allclose(width_profile[0], [cuff, *cuff_bounds], rtol=0, atol=1e-8*scale)
                    or not np.allclose(width_profile[-1], [base, *base_bounds], rtol=0, atol=1e-8*scale)):
                raise ValueError("Invalid explicit sleeve tube width profile")
        contour_rings = None
        if "tubeContourPlacement" in spec:
            contour_spec = spec["tubeContourPlacement"]
            if (contour_spec["method"] != "measured-neutral-arclength-rings"
                    or not apex_up or width_profile is None):
                raise ValueError("Incompatible sleeve contour placement")
            contour_rings = []
            for entry in contour_spec["rings"]:
                local_y = float(entry["localYM"]) * scale
                points = np.array(entry["supportGarmentCodeM"], dtype=float) * scale
                if (points.ndim != 2 or points.shape[1] != 3 or len(points) < 4
                        or not np.isfinite(points).all() or not math.isfinite(local_y)
                        or not np.allclose(points[0], points[-1], rtol=0, atol=1e-8*scale)):
                    raise ValueError("Invalid closed sleeve support ring")
                lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
                if not np.all(lengths > 1e-8*scale):
                    raise ValueError("Collapsed sleeve support ring segment")
                parameter = np.concatenate(([0.0], np.cumsum(lengths)))
                parameter /= parameter[-1]
                contour_rings.append((local_y, parameter, points))
            if (len(contour_rings) < 2
                    or any(b[0] <= a[0] for a, b in zip(contour_rings, contour_rings[1:]))
                    or abs(contour_rings[0][0]-cuff) > 1e-8*scale
                    or abs(contour_rings[-1][0]-base) > 1e-8*scale):
                raise ValueError("Sleeve contours must span ordered cuff-to-base rows")

        def transform(panel, vertex, anchor=anchor, cap=cap, base=base,
                      cuff=cuff, cb=cuff_bounds, bb=base_bounds, sign=sign, cap_depth=cap_depth, cuff_axis=cuff_axis, apex_up=apex_up, width_profile=width_profile, contour_rings=contour_rings):
            x, y = vertex
            t = min(1.0, max(0.0, (y-cuff)/(base-cuff)))
            lo, hi = cb * (1-t) + bb * t
            if width_profile is not None:
                lo = np.interp(y, width_profile[:, 0], width_profile[:, 1])
                hi = np.interp(y, width_profile[:, 0], width_profile[:, 2])
            circumference = hi-lo
            angle = 2 * math.pi * (x-lo)/circumference - math.pi
            if apex_up:
                # GC Y is Blender Z, GC +Z is Blender anterior (-Y).
                # The cap midpoint is superior; positive local X cap edges
                # run anterior and both tube boundary edges meet inferiorly.
                angle = math.pi/2 - angle
            radius = circumference/(2*math.pi)
            # Cap height in the flat pattern is not its depth along the arm.
            # Compress the cap in 3D while retaining the shoulder anchor,
            # full tube circumference, cuff position and all 2D rest lengths.
            axial = (cap-y)*cap_depth/(cap-base) if y >= base else cap_depth + (base-y)/(base-cuff)*(cuff_axis-cap_depth)
            if contour_rings is not None and y <= base:
                u = min(1.0, max(0.0, (x-lo)/circumference))
                lower = 0
                while lower < len(contour_rings)-2 and y > contour_rings[lower+1][0]:
                    lower += 1
                low_y, low_u, low_points = contour_rings[lower]
                high_y, high_u, high_points = contour_rings[lower+1]
                blend = min(1.0, max(0.0, (y-low_y)/(high_y-low_y)))
                low_point = np.array([np.interp(u, low_u, low_points[:, k]) for k in range(3)])
                high_point = np.array([np.interp(u, high_u, high_points[:, k]) for k in range(3)])
                return low_point*(1-blend) + high_point*blend
            return anchor + np.array([sign*axial, radius*math.sin(angle), radius*math.cos(angle)])

        panel = mesh.panels[name]
        panel.rot_trans_vertex = MethodType(transform, panel)
        panel.rot_trans_panel = MethodType(lambda panel, vertices: np.array([panel.rot_trans_vertex(v) for v in vertices]), panel)
        panel.image2outfit_cylindrical = True
        panel.image2outfit_reverse_winding = (sign > 0) if apex_up else (sign < 0)
        records.append({"panel": name, "specification": spec, "vertexCount": len(panel.panel_vertices), "changes2dRestLengths": False, "grantsFitAcceptance": False})
    # Resolve paired armholes only after every torso transform is installed.
    for name, source in pattern["panels"].items():
        cap_spec = source.get("image2outfitCylindricalWrap", {}).get("sewnCapPlacement")
        if cap_spec is None:
            continue
        if cap_spec["method"] != "follow-paired-torso-armhole-placement":
            raise ValueError("Unknown sewn cap placement method")
        fade = float(cap_spec["blendDistanceM"])*scale
        if not math.isfinite(fade) or fade <= 0 or len(cap_spec["edges"]) != 4:
            raise ValueError("Invalid sewn cap blend specification")
        bindings = []
        for entry in cap_spec["edges"]:
            edge = np.array(entry["patternEdgeM"], dtype=float)*scale
            target = np.array(entry["targetPatternEdgeM"], dtype=float)*scale
            key = entry["targetPanelKey"]
            if key not in mesh.panels or pattern["panels"][key].get("image2outfitTorsoWrap") is None:
                raise ValueError("Sewn cap target has no torso transform")
            if edge.shape != (2,2) or target.shape != (2,2) or not np.isfinite(np.concatenate((edge.ravel(),target.ravel()))).all() or np.linalg.norm(edge[1]-edge[0]) <= 0:
                raise ValueError("Invalid sewn cap edge binding")
            bindings.append((edge, target, mesh.panels[key]))
        panel = mesh.panels[name]
        original_transform = panel.rot_trans_vertex
        def cap_transform(panel, vertex, original=original_transform, bindings=bindings, fade=fade):
            result = original(vertex)
            candidates = []
            for edge, target, torso_panel in bindings:
                delta = edge[1]-edge[0]
                fraction = min(1, max(0, np.dot(np.array(vertex)-edge[0],delta)/np.dot(delta,delta)))
                distance = np.linalg.norm(np.array(vertex)-(edge[0]+fraction*delta))
                paired = target[0]*(1-fraction)+target[1]*fraction
                candidates.append((distance, torso_panel.rot_trans_vertex(paired)))
            distance, target = min(candidates, key=lambda row: row[0])
            weight = max(0, 1-distance/fade)
            weight = weight*weight*(3-2*weight)
            return result*(1-weight)+target*weight
        panel.rot_trans_vertex = MethodType(cap_transform, panel)
        panel.rot_trans_panel = MethodType(lambda panel, vertices: np.array([panel.rot_trans_vertex(v) for v in vertices]), panel)
    if records:
        original_order = mesh._order_face_vertices
        def order(panel, vertices):
            if not getattr(panel, "image2outfit_cylindrical", False):
                return original_order(panel, vertices)
            # Curved panels have no single 3D normal. Retain consistent local
            # 2D winding rather than comparing them against the old flat normal.
            for face in panel.panel_faces:
                a, b, c = [np.array(panel.panel_vertices[i]) for i in face]
                cross = (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
                if (cross < 0) != getattr(panel, "image2outfit_reverse_winding", False):
                    face[1], face[2] = face[2], face[1]
        mesh._order_face_vertices = order
    return records


def main() -> int:
    args = parse_args()
    input_path = args.input.resolve()
    output_path = args.output.resolve()
    payload: dict[str, Any] = {
        "schemaVersion": 1,
        "attemptType": "garmentcode-post-review-sewn-mesh-preflight",
        "checkedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputPath": str(input_path),
        "inputSha256": sha256(input_path) if input_path.is_file() else None,
        "outputMode": "in-memory-sewn-mesh-preflight",
        "productMeshArtifactWritten": False,
        "avatarFitEvaluated": False,
        "clothSimulationEvaluated": False,
        "releaseReady": False,
        "status": "ERROR",
    }
    try:
        actual_python, lock_sha256 = validate_runtime(args)
        sys.path.insert(0, str(args.upstream_root.resolve()))
        from pygarment.meshgen.boxmeshgen import BoxMesh  # noqa: PLC0415

        payload.update(
            {
                "pythonVersion": actual_python,
                "pygarmentVersion": args.pygarment_version,
                "upstreamRevision": args.upstream_revision,
                "requirementsLockSha256": lock_sha256,
            }
        )
        input_data = json.loads(input_path.read_text(encoding="utf-8"))
        pattern = input_data.get("pattern")
        parameters = input_data.get("parameters")
        adapter = (
            parameters.get("image2outfit")
            if isinstance(parameters, dict)
            else None
        )
        if not isinstance(pattern, dict) or not isinstance(adapter, dict):
            raise ValueError("BoxMesh input is missing the pattern or adapter metadata")
        payload["panelPoseInputAudit"] = _panel_pose_input_audit(pattern)
        stitch_ids = _mapped_stitch_ids(pattern, adapter)
        raw_panel_key_map = adapter.get("panelKeyMap")
        pattern_panels = pattern.get("panels")
        if (
            not isinstance(pattern_panels, dict)
            or not isinstance(raw_panel_key_map, dict)
            or set(pattern_panels) - set(raw_panel_key_map)
            or any(
                not isinstance(panel_key, str)
                or not isinstance(piece_id, str)
                for panel_key, piece_id in raw_panel_key_map.items()
            )
        ):
            raise ValueError("BoxMesh audit requires a complete panel-to-piece mapping")
        panel_key_map = raw_panel_key_map
        mesh = BoxMesh(str(input_path), res=1.0)
        mesh.load_panels()
        mesh.gen_panel_meshes()
        payload["cylindricalPlacement"] = _initialize_cylindrical_panels(mesh, pattern, input_data["properties"]["units_in_meter"])
        same_panel = mesh._stitch_vertices()
        _valid, invalid_indices = mesh._is_stitching_valid(same_panel)
        diagnostics = _stitch_diagnostics(mesh, stitch_ids, same_panel)
        endpoint_conflict_clusters = _endpoint_conflict_clusters(
            mesh, stitch_ids, same_panel, invalid_indices, panel_key_map
        )
        closed_loop_stitches = _intentional_closed_loop_stitches(
            mesh, stitch_ids, same_panel, invalid_indices
        )
        closed_loop_ids = {item["stitchId"] for item in closed_loop_stitches}
        blocking_invalid_stitches = [
            item
            for item in diagnostics["invalidStitches"]
            if item["stitchId"] not in closed_loop_ids
        ]
        payload.update(
            {
                "patternPanels": len(pattern.get("panels", {})),
                "panelEdgeCount": sum(
                    len(panel.get("edges", []))
                    for panel in pattern.get("panels", {}).values()
                ),
                "stitchPairs": len(stitch_ids),
                **diagnostics,
                "endpointConflictClusterCount": len(endpoint_conflict_clusters),
                "endpointConflictClusters": endpoint_conflict_clusters,
                "intentionalClosedLoopStitchCount": len(closed_loop_stitches),
                "intentionalClosedLoopStitches": closed_loop_stitches,
                "blockingInvalidStitchCount": len(blocking_invalid_stitches),
                "blockingInvalidStitches": blocking_invalid_stitches,
            }
        )
        if blocking_invalid_stitches:
            payload["status"] = "FAIL"
            payload["failureMeaning"] = (
                "GarmentCode BoxMesh rejected stitch-vertex relations that were not proven to be paired closed boundary loops; mesh finalization did not run."
            )
        else:
            mesh.finalise_mesh()
            topology = _finalized_mesh_topology(mesh, panel_key_map)
            payload.update(
                {
                    "status": (
                        "PASS"
                        if topology["degenerateFaceCount"] == 0
                        and topology["nonManifoldEdgeCount"] == 0
                        else "FAIL"
                    ),
                    "inMemoryMeshAssembly": True,
                    "meshVertexCount": topology["vertexCount"],
                    "meshFaceCount": topology["faceCount"],
                    "meshTopologyAudit": topology,
                }
            )
            if not mesh.vertices or not mesh.faces:
                raise ValueError("BoxMesh finalized an empty in-memory mesh")
            if topology["degenerateFaceCount"] or topology["nonManifoldEdgeCount"]:
                payload["failureMeaning"] = (
                    "Paired closed-loop stitches were classified and finalization ran, "
                    "but the sewn mesh contains degenerate faces or non-manifold edges."
                )
    except Exception as error:
        payload["status"] = "ERROR"
        payload["exceptionType"] = type(error).__name__
        payload["message"] = str(error)

    if args.mesh_output is not None and payload["status"] == "PASS":
        scale = input_data["properties"]["units_in_meter"]
        if not isinstance(scale, (int, float)) or scale <= 0:
            raise ValueError("Sewn mesh has no declared unit scale")
        exchange = {
            "schemaVersion": 1, "productId": adapter["productId"], "units": "meter",
            "coordinateSystem": "blender-z-up",
            "canonicalInputs": {"patternSha256": adapter["patternContractSha256"],
                                "stitchGraphSha256": adapter["stitchGraphSha256"]},
            "inputSha256": sha256(input_path), "upstreamRevision": args.upstream_revision,
            "vertices": [[float(vertex[0]) / scale, -float(vertex[2]) / scale, float(vertex[1]) / scale] for vertex in mesh.vertices],
            "faces": [[int(v) for v in face] for face in mesh.faces],
            "facePieceIds": topology["facePieceIds"],
            "topology": topology,
        }
        write_json(args.mesh_output.resolve(), exchange)
        payload["meshExchangePath"] = str(args.mesh_output.resolve())
        payload["meshExchangeSha256"] = sha256(args.mesh_output.resolve())
        payload["meshExchangeBoundary"] = "Local unfit sewn surface; no product acceptance implied"
    write_json(output_path, payload)
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["status"] == "PASS" else 2 if payload["status"] == "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
