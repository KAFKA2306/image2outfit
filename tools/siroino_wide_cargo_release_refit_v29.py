#!/usr/bin/env python3
"""Continuous, rear-safe Siroino Wide Cargo v29 candidate.

This revision removes the hem cutout that produced triangular shoe spikes,
repairs internal knee boundary loops, subdivides long interior edges instead of
relaxing the spike gate, re-unwraps UVs after topology repair, and uses a
restrained straight-wide profile with visible fabric/panel separation.
"""
from __future__ import annotations

import json
import math
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
lerp = v23.lerp

HEM_Z = 0.145
SPIKE_LIMIT = 0.075


def pants_surface(point) -> bool:
    """Select legs and pelvis without carving front/back hem wedges."""
    return HEM_Z <= point.z <= 0.805 and abs(point.x) <= 0.34


def target_cross_section(x: float, y: float, z: float) -> tuple[float, float]:
    side = -1.0 if x < 0.0 else 1.0
    down = 1.0 - smoothstep(HEM_Z, 0.68, z)
    center_x = side * lerp(0.073, 0.070, down)
    outer_radius = lerp(0.104, 0.110, down)
    inner_radius = lerp(0.056, 0.060, down)
    depth_radius = lerp(0.088, 0.098, down)
    local_x = x - center_x
    angle = math.atan2(y, local_x)
    c = math.cos(angle)
    s = math.sin(angle)
    outer_weight = clamp((side * c + 1.0) * 0.5, 0.0, 1.0)
    radius_x = lerp(inner_radius, outer_radius, outer_weight)
    return center_x + c * radius_x, s * depth_radius


def apply_product_profile(obj: bpy.types.Object) -> None:
    """Suppress hip inflation and hold a nearly parallel wide-leg silhouette."""
    for vertex in obj.data.vertices:
        x, y, z = vertex.co
        target_x, target_y = target_cross_section(x, y, z)
        target_mix = lerp(0.94, 0.62, smoothstep(0.64, 0.805, z))
        if z > 0.43 and abs(x) < 0.030:
            target_mix *= lerp(0.20, 1.0, smoothstep(0.006, 0.030, abs(x)))
        fitted_x = clamp(x * 1.025, -0.180, 0.180)
        fitted_y = clamp(y * 1.020, -0.108, 0.108)
        vertex.co.x = clamp(lerp(fitted_x, target_x, target_mix), -0.185, 0.185)
        vertex.co.y = clamp(lerp(fitted_y, target_y, target_mix), -0.110, 0.110)
        vertex.co.z = clamp(z, HEM_Z, 0.815)

        centre = 1.0 - smoothstep(0.018, 0.150, abs(vertex.co.x))
        if vertex.co.y > 0.0:
            crotch = smoothstep(0.475, 0.555, z) * (1.0 - smoothstep(0.700, 0.790, z))
            seat = smoothstep(0.575, 0.635, z) * (1.0 - smoothstep(0.755, 0.805, z))
            vertex.co.y = clamp(
                vertex.co.y
                + 0.0070 * crotch * (0.62 + 0.38 * centre)
                + 0.0140 * seat * (0.72 + 0.28 * centre),
                -0.110,
                0.118,
            )
    obj.data.update(calc_edges=True)


def remove_stretched_faces(obj: bpy.types.Object, limit: float = 0.120) -> int:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bad = [
        face
        for face in bm.faces
        if any((edge.verts[0].co - edge.verts[1].co).length > limit for edge in face.edges)
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


def boundary_components(bm: bmesh.types.BMesh) -> list[list[bmesh.types.BMEdge]]:
    boundary = {edge for edge in bm.edges if len(edge.link_faces) == 1}
    by_vertex: dict[bmesh.types.BMVert, list[bmesh.types.BMEdge]] = {}
    for edge in boundary:
        for vertex in edge.verts:
            by_vertex.setdefault(vertex, []).append(edge)
    components: list[list[bmesh.types.BMEdge]] = []
    while boundary:
        seed = boundary.pop()
        component = [seed]
        stack = [seed]
        while stack:
            edge = stack.pop()
            for vertex in edge.verts:
                for neighbor in by_vertex.get(vertex, []):
                    if neighbor in boundary:
                        boundary.remove(neighbor)
                        component.append(neighbor)
                        stack.append(neighbor)
        components.append(component)
    return components


def component_metrics(edges: list[bmesh.types.BMEdge]) -> dict[str, float | int | bool]:
    vertices = {vertex for edge in edges for vertex in edge.verts}
    xs = [float(vertex.co.x) for vertex in vertices]
    zs = [float(vertex.co.z) for vertex in vertices]
    degree = {vertex: 0 for vertex in vertices}
    for edge in edges:
        for vertex in edge.verts:
            degree[vertex] += 1
    return {
        "edges": len(edges),
        "meanX": sum(xs) / len(xs),
        "meanZ": sum(zs) / len(zs),
        "zSpan": max(zs) - min(zs),
        "closed": all(value == 2 for value in degree.values()),
    }


def bridge_internal_knee_loops(obj: bpy.types.Object) -> int:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    components = boundary_components(bm)
    candidates: list[tuple[list[bmesh.types.BMEdge], dict[str, float | int | bool]]] = []
    for edges in components:
        metrics = component_metrics(edges)
        if (
            bool(metrics["closed"])
            and 0.22 <= float(metrics["meanZ"]) <= 0.60
            and float(metrics["zSpan"]) <= 0.080
        ):
            candidates.append((edges, metrics))

    bridged = 0
    for side in (-1, 1):
        side_loops = [
            item for item in candidates
            if (-1 if float(item[1]["meanX"]) < 0.0 else 1) == side
        ]
        side_loops.sort(key=lambda item: float(item[1]["meanZ"]))
        while len(side_loops) >= 2:
            best_index = min(
                range(len(side_loops) - 1),
                key=lambda index: abs(
                    float(side_loops[index + 1][1]["meanZ"])
                    - float(side_loops[index][1]["meanZ"])
                ),
            )
            lower = side_loops.pop(best_index)
            upper = side_loops.pop(best_index)
            bmesh.ops.bridge_loops(bm, edges=lower[0] + upper[0])
            bridged += 1

    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update(calc_edges=True)
    obj["bridged_knee_loop_pairs"] = bridged
    return bridged


def subdivide_long_interior_edges(obj: bpy.types.Object, limit: float = SPIKE_LIMIT) -> int:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    total = 0
    for _ in range(3):
        long_edges = [
            edge
            for edge in bm.edges
            if len(edge.link_faces) > 1
            and (edge.verts[0].co - edge.verts[1].co).length > limit * 0.96
        ]
        if not long_edges:
            break
        total += len(long_edges)
        bmesh.ops.subdivide_edges(bm, edges=long_edges, cuts=1, use_grid_fill=False)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update(calc_edges=True)
    obj["subdivided_long_interior_edges"] = total
    return total


def unwrap_uv(obj: bpy.types.Object) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=1.15192, island_margin=0.02)
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.data.update()


def assign_materials(pants: bpy.types.Object, fabric, strap) -> None:
    base.tune_material(fabric, base=(0.025, 0.030, 0.042), roughness=0.82)
    base.tune_material(strap, base=(0.002, 0.003, 0.005), roughness=0.24)
    pants.data.materials.clear()
    pants.data.materials.append(fabric)
    pants.data.materials.append(strap)
    for polygon in pants.data.polygons:
        vertices = [pants.data.vertices[index].co for index in polygon.vertices]
        mean_z = sum(point.z for point in vertices) / len(vertices)
        mean_x = sum(point.x for point in vertices) / len(vertices)
        side_panel = abs(mean_x) >= 0.135 and mean_z <= 0.70
        waistband = mean_z >= 0.755
        knee_panel = 0.385 <= mean_z <= 0.420
        polygon.material_index = 1 if side_panel or waistband or knee_panel else 0
    pants.data.update()


def create_outfit(body, armature, fabric, strap, metal):
    del metal
    pants = build.c.extract_surface(
        body,
        armature,
        "Cargo_Continuous_Pants",
        pants_surface,
        fabric,
        0.011,
    )
    apply_product_profile(pants)
    removed = remove_stretched_faces(pants)
    bridged = bridge_internal_knee_loops(pants)
    subdivided = subdivide_long_interior_edges(pants)
    build.clean_topology(pants)
    unwrap_uv(pants)
    assign_materials(pants, fabric, strap)
    pants["removed_stretched_faces"] = removed
    pants["bridged_knee_loop_pairs"] = bridged
    pants["subdivided_long_interior_edges"] = subdivided
    return [pants]


def triangle_degenerates(obj: bpy.types.Object) -> int:
    obj.data.calc_loop_triangles()
    return sum(
        1
        for triangle in obj.data.loop_triangles
        if (
            obj.data.vertices[triangle.vertices[1]].co
            - obj.data.vertices[triangle.vertices[0]].co
        ).cross(
            obj.data.vertices[triangle.vertices[2]].co
            - obj.data.vertices[triangle.vertices[0]].co
        ).length_squared <= 1e-20
    )


def edge_metrics(obj: bpy.types.Object) -> tuple[float, float]:
    usage: dict[tuple[int, int], int] = {}
    for polygon in obj.data.polygons:
        vertices = list(polygon.vertices)
        for index, first in enumerate(vertices):
            second = vertices[(index + 1) % len(vertices)]
            key = (min(first, second), max(first, second))
            usage[key] = usage.get(key, 0) + 1
    longest = 0.0
    longest_interior = 0.0
    for edge in obj.data.edges:
        first, second = edge.vertices
        length = (obj.data.vertices[first].co - obj.data.vertices[second].co).length
        longest = max(longest, length)
        if usage.get((min(first, second), max(first, second)), 0) > 1:
            longest_interior = max(longest_interior, length)
    return longest, longest_interior


def remaining_internal_boundaries(obj: bpy.types.Object) -> list[dict[str, float | int | bool]]:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    result = []
    for edges in boundary_components(bm):
        metrics = component_metrics(edges)
        if 0.22 <= float(metrics["meanZ"]) <= 0.60:
            result.append(metrics)
    bm.free()
    return result


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
    hem = band(pants, HEM_Z, 0.205)
    internal_boundaries = remaining_internal_boundaries(pants)
    degenerates = triangle_degenerates(pants)
    material_faces = [0, 0]
    for polygon in pants.data.polygons:
        if polygon.material_index < len(material_faces):
            material_faces[polygon.material_index] += 1
    total_faces = max(1, sum(material_faces))
    uv_finite = bool(pants.data.uv_layers) and all(
        math.isfinite(float(value))
        for loop in pants.data.uv_layers.active.data
        for value in loop.uv
    )

    metrics.update(
        {
            "maximumEdgeLength": longest,
            "maximumInteriorEdgeLength": longest_interior,
            "removedStretchedFaces": int(pants.get("removed_stretched_faces", 0)),
            "bridgedKneeLoopPairs": int(pants.get("bridged_knee_loop_pairs", 0)),
            "subdividedLongInteriorEdges": int(pants.get("subdivided_long_interior_edges", 0)),
            "remainingInternalBoundaries": internal_boundaries,
            "rearSeatBand": seat,
            "materialFaceCounts": material_faces,
            "degenerateTriangles": degenerates,
        }
    )
    checks.update(
        {
            "stretchedSourceFacesRemoved": int(pants.get("removed_stretched_faces", 0)) > 0,
            "spikeGuardPassed": longest_interior <= SPIKE_LIMIT,
            "topologyPassed": degenerates == 0,
            "uvPassed": uv_finite,
            "materialSeparationPassed": (
                len(pants.data.materials) >= 2
                and min(material_faces) / total_faces >= 0.05
            ),
            "footAndFloorClearancePassed": metrics["minimumZ"] >= HEM_Z - 1e-5,
            "kneeContinuityPassed": len(internal_boundaries) == 0,
            "rearSeatClearancePassed": seat["rear"] >= 0.098,
            "straightWideProfilePassed": (
                abs(upper["width"] - knee["width"]) <= 0.055
                and abs(knee["width"] - hem["width"]) <= 0.050
                and abs(upper["depth"] - knee["depth"]) <= 0.050
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
        "kneeContinuityPassed",
        "rearSeatClearancePassed",
        "straightWideProfilePassed",
    ]
    report["passed"] = all(bool(checks.get(name)) for name in required)
    return report


def record(report: dict[str, object]) -> None:
    _, job = build.c.load_job()
    path = build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    manifest["status"] = "WORKING"
    manifest["designRevision"] = "v29-products-root-continuous-knee"
    manifest["wearabilityAudit"] = report
    gates = manifest.setdefault("technicalGates", {})
    gates["latestGeometryRender"] = "PASS" if report["passed"] else "FAIL"
    gates["humanVisualReview"] = "PENDING"
    gates["humanPoseReview"] = "PENDING"
    gates["humanRuntimeReview"] = "PENDING"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


build.create_outfit = create_outfit


if __name__ == "__main__":
    build.main()
    result = audit()
    record(result)
    base.save_distribution_blend()
    if not result["passed"]:
        raise RuntimeError(f"v29 wearability audit failed: {result}")
    raise SystemExit(0)
