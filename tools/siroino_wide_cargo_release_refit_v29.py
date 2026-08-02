#!/usr/bin/env python3
"""Rear-safe, spike-free Siroino Wide Cargo v29 candidate."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bmesh
import bpy

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_release_refit_v23 as v23

build = v23.build
base = v23.base
smoothstep = v23.smoothstep
clamp = v23.clamp


def apply_rear_safe_profile(obj: bpy.types.Object) -> None:
    """Apply the straight-wide profile once and reinforce rear coverage."""
    v23.apply_profile(obj)
    for vertex in obj.data.vertices:
        x, y, z = vertex.co
        centre = 1.0 - smoothstep(0.018, 0.150, abs(x))
        if y > 0.0:
            crotch = smoothstep(0.475, 0.555, z) * (
                1.0 - smoothstep(0.700, 0.790, z)
            )
            seat = smoothstep(0.575, 0.635, z) * (
                1.0 - smoothstep(0.755, 0.805, z)
            )
            vertex.co.y = clamp(
                y
                + 0.0065 * crotch * (0.62 + 0.38 * centre)
                + 0.0120 * seat * (0.72 + 0.28 * centre),
                -0.145,
                0.145,
            )

        inner = (
            (1.0 - smoothstep(0.025, 0.085, abs(x)))
            * smoothstep(0.430, 0.490, z)
            * (1.0 - smoothstep(0.585, 0.655, z))
        )
        vertex.co.x *= 1.0 - 0.055 * inner
    obj.data.update(calc_edges=True)


def remove_stretched_faces(obj: bpy.types.Object, limit: float = 0.120) -> int:
    """Delete malformed source faces spanning from hem to crotch."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bad = [
        face
        for face in bm.faces
        if any(
            (edge.verts[0].co - edge.verts[1].co).length > limit
            for edge in face.edges
        )
    ]
    removed = len(bad)
    if bad:
        bmesh.ops.delete(bm, geom=bad, context="FACES")
        loose = [vertex for vertex in bm.verts if not vertex.link_faces]
        if loose:
            bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update(calc_edges=True)
    obj["removed_stretched_faces"] = removed
    return removed


def create_outfit(body, armature, fabric, strap, metal):
    del metal
    pants = build.c.extract_surface(
        body,
        armature,
        "Cargo_Continuous_Pants",
        v23.pants_surface,
        fabric,
        0.011,
    )
    apply_rear_safe_profile(pants)
    removed = remove_stretched_faces(pants)
    if removed == 0:
        raise RuntimeError("No stretched source faces were removed")
    build.clean_topology(pants)
    v23.assign_materials(pants, fabric, strap)
    return [pants]


def edge_metrics(obj: bpy.types.Object) -> tuple[float, float]:
    usage: dict[tuple[int, int], int] = {}
    for polygon in obj.data.polygons:
        vertices = list(polygon.vertices)
        for index, a in enumerate(vertices):
            b = vertices[(index + 1) % len(vertices)]
            key = (min(a, b), max(a, b))
            usage[key] = usage.get(key, 0) + 1
    longest = 0.0
    longest_interior = 0.0
    for edge in obj.data.edges:
        a_index, b_index = edge.vertices
        a = obj.data.vertices[a_index].co
        b = obj.data.vertices[b_index].co
        length = (a - b).length
        longest = max(longest, length)
        if usage.get((min(a_index, b_index), max(a_index, b_index)), 0) > 1:
            longest_interior = max(longest_interior, length)
    return longest, longest_interior


def band(obj: bpy.types.Object, z0: float, z1: float) -> dict[str, float]:
    points = [vertex.co for vertex in obj.data.vertices if z0 <= vertex.co.z <= z1]
    xs = [point.x for point in points]
    ys = [point.y for point in points]
    return {
        "width": max(xs) - min(xs) if xs else 0.0,
        "depth": max(ys) - min(ys) if ys else 0.0,
        "rear": max(ys) if ys else 0.0,
    }


def audit() -> dict[str, object]:
    report = v23.audit()
    pants = bpy.data.objects.get("Cargo_Continuous_Pants")
    if pants is None:
        return report

    checks = report["checks"]
    metrics = checks["metrics"]
    longest, longest_interior = edge_metrics(pants)
    seat = band(pants, 0.625, 0.755)
    upper = band(pants, 0.475, 0.590)
    knee = band(pants, 0.300, 0.405)
    hem = band(pants, 0.105, 0.185)
    inner = [
        vertex.co
        for vertex in pants.data.vertices
        if 0.440 <= vertex.co.z <= 0.610 and abs(vertex.co.x) <= 0.045
    ]
    rear_bridge = [
        point
        for point in inner
        if point.y >= 0.018 and 0.470 <= point.z <= 0.610
    ]
    removed = int(pants.get("removed_stretched_faces", 0))

    metrics.update(
        {
            "maximumEdgeLength": longest,
            "maximumInteriorEdgeLength": longest_interior,
            "removedStretchedFaces": removed,
            "innerThighCoverageVertices": len(inner),
            "rearBridgeVertices": len(rear_bridge),
            "rearSeatBand": seat,
        }
    )
    checks.update(
        {
            "stretchedSourceFacesRemoved": removed > 0,
            "spikeGuardPassed": longest_interior <= 0.075,
            "rearSeatClearancePassed": seat["rear"] >= 0.096,
            "innerThighCoveragePassed": len(inner) >= 24,
            "rearCrotchBridgePassed": len(rear_bridge) >= 8,
            "straightWideProfilePassed": (
                abs(upper["width"] - knee["width"]) <= 0.075
                and abs(knee["width"] - hem["width"]) <= 0.070
                and abs(upper["depth"] - knee["depth"]) <= 0.065
            ),
        }
    )
    required = [
        "singleShellOnly",
        "finiteCoordinatesPassed",
        "stretchedSourceFacesRemoved",
        "spikeGuardPassed",
        "topologyPassed",
        "uvPassed",
        "materialSeparationPassed",
        "shapeKeyIsolationPassed",
        "footAndFloorClearancePassed",
        "controlledVolumePassed",
        "profileContinuityPassed",
        "rearSeatClearancePassed",
        "innerThighCoveragePassed",
        "rearCrotchBridgePassed",
        "straightWideProfilePassed",
    ]
    report["passed"] = all(bool(checks[name]) for name in required)
    return report


def record(report: dict[str, object]) -> None:
    _, job = build.c.load_job()
    path = build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    manifest["status"] = "WORKING"
    manifest["designRevision"] = "v29-products-root-rear-safe"
    manifest["wearabilityAudit"] = report
    gates = manifest.setdefault("technicalGates", {})
    gates["latestGeometryRender"] = "PASS" if report["passed"] else "FAIL"
    gates["humanVisualReview"] = "PENDING"
    gates["humanPoseReview"] = "PENDING"
    gates["humanRuntimeReview"] = "PENDING"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


build.create_outfit = create_outfit


if __name__ == "__main__":
    build.main()
    result = audit()
    record(result)
    base.save_distribution_blend()
    if not result["passed"]:
        raise RuntimeError(f"v29 rear/topology audit failed: {result}")
    raise SystemExit(0)
