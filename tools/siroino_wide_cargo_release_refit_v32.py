#!/usr/bin/env python3
"""Product-quality Siroino Wide Cargo v32.

This revision keeps the continuous source faces, performs topology cleanup
before deterministic edge subdivision, fits the waist and upper thigh toward
the body, flattens the two open hem boundaries, adds restrained drape, and
creates visibly separated waistband, knee, and cargo-side material panels.
Stale render evidence is removed before every attempt.
"""
from __future__ import annotations

import json
import math
import shutil
import sys
from pathlib import Path

import bmesh
import bpy

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_release_refit_v29 as previous

build = previous.build
base = previous.base
smoothstep = previous.smoothstep
clamp = previous.clamp
HEM_Z = previous.HEM_Z
SPIKE_LIMIT = previous.SPIKE_LIMIT


def clear_stale_render_evidence() -> None:
    _, job = build.c.load_job()
    preview_root = build.c.repo_path(job["productRoot"]) / "Previews"
    if not preview_root.exists():
        return
    for pattern in ("*.png", "*.webp"):
        for path in preview_root.glob(pattern):
            path.unlink(missing_ok=True)
    shutil.rmtree(preview_root / "Poses", ignore_errors=True)
    for pattern in ("*.png.meta", "*.webp.meta"):
        for path in preview_root.glob(pattern):
            path.unlink(missing_ok=True)
    (preview_root / "Poses.meta").unlink(missing_ok=True)


def fit_waist_and_drape(obj: bpy.types.Object) -> None:
    previous.apply_product_profile(obj)
    for vertex in obj.data.vertices:
        x, y, z = vertex.co

        # Pull the open waist edge toward the exact body instead of leaving
        # the wing-like flare visible in front/back and side views.
        waist = smoothstep(0.665, 0.810, z)
        vertex.co.x *= 1.0 - 0.145 * waist
        vertex.co.y *= 1.0 - 0.100 * waist

        # Reduce the oversized hip and upper-thigh envelope while preserving
        # room below the seat and avoiding a leggings silhouette.
        upper = smoothstep(0.455, 0.555, z) * (1.0 - smoothstep(0.660, 0.735, z))
        vertex.co.x *= 1.0 - 0.055 * upper
        vertex.co.y *= 1.0 - 0.035 * upper

        # Use a shallow straight-wide taper and a tiny vertical side-seam wave
        # so the lower leg reads as cloth rather than an extruded box.
        lower = 1.0 - smoothstep(HEM_Z, 0.455, z)
        vertex.co.x *= 1.0 - 0.025 * lower
        vertex.co.y *= 1.0 - 0.020 * lower
        side = smoothstep(0.105, 0.155, abs(vertex.co.x))
        drape = math.sin((z - HEM_Z) * math.pi * 5.2) * 0.0022 * side
        vertex.co.x += math.copysign(drape, vertex.co.x) if abs(vertex.co.x) > 1e-6 else 0.0

        # Keep the shell outside the feet and floor while retaining an open hem.
        vertex.co.z = max(float(vertex.co.z), HEM_Z)
    obj.data.update(calc_edges=True)


def boundary_components(bm: bmesh.types.BMesh) -> list[list[bmesh.types.BMEdge]]:
    return previous.boundary_components(bm)


def flatten_hem_boundaries(obj: bpy.types.Object) -> int:
    """Make both open leg hems level without capping or intersecting shoes."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    adjusted = 0
    for edges in boundary_components(bm):
        vertices = {vertex for edge in edges for vertex in edge.verts}
        if not vertices:
            continue
        mean_z = sum(float(vertex.co.z) for vertex in vertices) / len(vertices)
        mean_x = sum(float(vertex.co.x) for vertex in vertices) / len(vertices)
        z_span = max(float(vertex.co.z) for vertex in vertices) - min(
            float(vertex.co.z) for vertex in vertices
        )
        if mean_z <= 0.215 and abs(mean_x) >= 0.020 and z_span <= 0.160:
            for vertex in vertices:
                vertex.co.z = HEM_Z
            adjusted += 1
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update(calc_edges=True)
    obj["flattened_hem_boundaries"] = adjusted
    return adjusted


def subdivide_long_interior_edges(
    obj: bpy.types.Object,
    limit: float = SPIKE_LIMIT,
) -> int:
    """Subdivide after cleanup until every interior edge satisfies the limit."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    total = 0
    for _ in range(6):
        long_edges = [
            edge
            for edge in bm.edges
            if len(edge.link_faces) > 1
            and (edge.verts[0].co - edge.verts[1].co).length > limit
        ]
        if not long_edges:
            break
        total += len(long_edges)
        bmesh.ops.subdivide_edges(
            bm,
            edges=long_edges,
            cuts=1,
            use_grid_fill=False,
        )
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update(calc_edges=True)
    obj["subdivided_long_interior_edges"] = total
    return total


def unwrap_uv(obj: bpy.types.Object) -> None:
    previous.unwrap_uv(obj)


def assign_materials(pants: bpy.types.Object, fabric, strap) -> None:
    # Deliberately stronger separation than v31: matte charcoal cloth against
    # near-black smooth technical panels, visible in neutral studio lighting.
    base.tune_material(fabric, base=(0.060, 0.070, 0.088), roughness=0.92)
    base.tune_material(strap, base=(0.003, 0.004, 0.007), roughness=0.20)
    pants.data.materials.clear()
    pants.data.materials.append(fabric)
    pants.data.materials.append(strap)
    for polygon in pants.data.polygons:
        points = [pants.data.vertices[index].co for index in polygon.vertices]
        mean_x = sum(float(point.x) for point in points) / len(points)
        mean_y = sum(float(point.y) for point in points) / len(points)
        mean_z = sum(float(point.z) for point in points) / len(points)
        waistband = mean_z >= 0.748
        knee_panel = 0.360 <= mean_z <= 0.435
        side_panel = abs(mean_x) >= 0.122 and 0.245 <= mean_z <= 0.705
        cargo_patch = abs(mean_x) >= 0.108 and abs(mean_y) >= 0.055 and 0.500 <= mean_z <= 0.650
        polygon.material_index = 1 if waistband or knee_panel or side_panel or cargo_patch else 0
    pants.data.update()


def create_outfit(body, armature, fabric, strap, metal):
    del metal
    pants = build.c.extract_surface(
        body,
        armature,
        "Cargo_Continuous_Pants",
        previous.pants_surface,
        fabric,
        0.011,
    )
    fit_waist_and_drape(pants)

    # Keep source faces. Deleting long faces caused the visible triangular hem
    # notches in v31. Cleanup first, then subdivide the actual final topology.
    build.clean_topology(pants)
    fit_waist_and_drape(pants)
    flattened = flatten_hem_boundaries(pants)
    subdivided = subdivide_long_interior_edges(pants)
    unwrap_uv(pants)
    assign_materials(pants, fabric, strap)
    pants["flattened_hem_boundaries"] = flattened
    pants["subdivided_long_interior_edges"] = subdivided
    pants["removed_stretched_faces"] = 0
    return [pants]


def hem_boundary_metrics(obj: bpy.types.Object) -> dict[str, object]:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    hems: list[dict[str, float | int]] = []
    for edges in boundary_components(bm):
        vertices = {vertex for edge in edges for vertex in edge.verts}
        if not vertices:
            continue
        zs = [float(vertex.co.z) for vertex in vertices]
        xs = [float(vertex.co.x) for vertex in vertices]
        mean_z = sum(zs) / len(zs)
        if mean_z <= 0.215:
            hems.append(
                {
                    "vertices": len(vertices),
                    "meanX": sum(xs) / len(xs),
                    "meanZ": mean_z,
                    "zSpan": max(zs) - min(zs),
                }
            )
    bm.free()
    return {"count": len(hems), "components": hems}


def audit() -> dict[str, object]:
    report = previous.audit()
    pants = bpy.data.objects.get("Cargo_Continuous_Pants")
    if pants is None:
        return report

    checks = report["checks"]
    metrics = checks["metrics"]
    longest, longest_interior = previous.edge_metrics(pants)
    hems = hem_boundary_metrics(pants)
    waist = previous.band(pants, 0.755, 0.815)
    upper = previous.band(pants, 0.475, 0.590)
    knee = previous.band(pants, 0.300, 0.405)
    hem = previous.band(pants, HEM_Z, 0.205)
    degenerates = previous.triangle_degenerates(pants)
    material_faces = [0, 0]
    for polygon in pants.data.polygons:
        if 0 <= polygon.material_index < len(material_faces):
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
            "subdividedLongInteriorEdges": int(
                pants.get("subdivided_long_interior_edges", 0)
            ),
            "flattenedHemBoundaries": int(pants.get("flattened_hem_boundaries", 0)),
            "hemBoundaryMetrics": hems,
            "waistBand": waist,
            "materialFaceCounts": material_faces,
            "degenerateTriangles": degenerates,
        }
    )
    checks.update(
        {
            "sourceStretchResolved": longest_interior <= SPIKE_LIMIT,
            "spikeGuardPassed": longest_interior <= SPIKE_LIMIT,
            "topologyPassed": degenerates == 0,
            "uvPassed": uv_finite,
            "materialSeparationPassed": (
                len(pants.data.materials) >= 2
                and min(material_faces) / total_faces >= 0.08
            ),
            "levelOpenHemsPassed": (
                int(hems["count"]) >= 2
                and all(float(item["zSpan"]) <= 0.006 for item in hems["components"])
            ),
            "waistVolumePassed": waist["width"] <= 0.325 and waist["depth"] <= 0.190,
            "upperThighVolumePassed": upper["width"] <= 0.335 and upper["depth"] <= 0.185,
            "straightWideProfilePassed": (
                abs(upper["width"] - knee["width"]) <= 0.050
                and abs(knee["width"] - hem["width"]) <= 0.045
                and abs(upper["depth"] - knee["depth"]) <= 0.045
            ),
        }
    )
    required = [
        "singleShellOnly",
        "finiteCoordinatesPassed",
        "sourceStretchResolved",
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
        "levelOpenHemsPassed",
        "waistVolumePassed",
        "upperThighVolumePassed",
        "straightWideProfilePassed",
    ]
    report["passed"] = all(bool(checks.get(name)) for name in required)
    return report


def record(report: dict[str, object]) -> None:
    _, job = build.c.load_job()
    path = build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    manifest["status"] = "WORKING"
    manifest["designRevision"] = "v32-waist-hem-drape-panels"
    manifest["wearabilityAudit"] = report
    gates = manifest.setdefault("technicalGates", {})
    gates["blender"] = "PASS" if report["passed"] else "FAIL"
    gates["fbx"] = "PASS" if report["passed"] else "FAIL"
    gates["uvMapping"] = "PASS" if report["passed"] else "FAIL"
    gates["latestGeometryRender"] = "PASS" if report["passed"] else "FAIL"
    gates["exactBodyPoseRenders"] = "PENDING"
    gates["humanVisualReview"] = "PENDING"
    gates["humanPoseReview"] = "PENDING"
    gates["humanRuntimeReview"] = "PENDING"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


build.create_outfit = create_outfit


if __name__ == "__main__":
    clear_stale_render_evidence()
    build.main()
    result = audit()
    record(result)
    base.save_distribution_blend()
    if not result["passed"]:
        raise RuntimeError(f"v32 visual and geometry audit failed: {result}")
    raise SystemExit(0)
