#!/usr/bin/env python3
"""Stable spike-guarded single-shell build for Siroino Wide Cargo."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_build as build
import siroino_wide_cargo_entry as base


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def smoothstep(a: float, b: float, value: float) -> float:
    if abs(b - a) <= 1e-9:
        return 1.0 if value >= b else 0.0
    t = clamp((value - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def pants_surface(point) -> bool:
    if not (0.105 <= point.z <= 0.805):
        return False
    if abs(point.x) > 0.34:
        return False
    if point.z < 0.185 and abs(point.y) > 0.064:
        return False
    return True


def target_cross_section(x: float, y: float, z: float) -> tuple[float, float]:
    side = -1.0 if x < 0.0 else 1.0
    down = 1.0 - smoothstep(0.105, 0.62, z)
    center_x = side * lerp(0.087, 0.071, down)
    outer_radius = lerp(0.112, 0.126, down)
    inner_radius = lerp(0.061, 0.059, down)
    depth_radius = lerp(0.096, 0.106, down)
    local_x = x - center_x
    angle = math.atan2(y, local_x)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    outer_weight = clamp((side * cosine + 1.0) * 0.5, 0.0, 1.0)
    radius_x = lerp(inner_radius, outer_radius, outer_weight)
    return center_x + cosine * radius_x, sine * depth_radius


def apply_profile(obj: bpy.types.Object) -> None:
    for vertex in obj.data.vertices:
        x, y, z = vertex.co
        target_x, target_y = target_cross_section(x, y, z)
        lower_mix = 1.0 - smoothstep(0.53, 0.68, z)
        fitted_x = x * lerp(1.09, 1.045, smoothstep(0.62, 0.805, z))
        fitted_y = y * lerp(1.10, 1.055, smoothstep(0.62, 0.805, z))
        if z > 0.43 and abs(x) < 0.028:
            lower_mix *= smoothstep(0.006, 0.028, abs(x))
        vertex.co.x = clamp(lerp(fitted_x, target_x, lower_mix), -0.225, 0.225)
        vertex.co.y = clamp(lerp(fitted_y, target_y, lower_mix), -0.145, 0.145)
        vertex.co.z = clamp(z, 0.105, 0.815)
    obj.data.update(calc_edges=True)


def assign_materials(pants: bpy.types.Object, fabric, strap) -> None:
    base.tune_material(fabric, base=(0.032, 0.038, 0.052), roughness=0.78)
    base.tune_material(strap, base=(0.004, 0.006, 0.010), roughness=0.30)
    pants.data.materials.clear()
    pants.data.materials.append(fabric)
    pants.data.materials.append(strap)
    for polygon in pants.data.polygons:
        mean_z = sum(pants.data.vertices[index].co.z for index in polygon.vertices) / len(
            polygon.vertices
        )
        polygon.material_index = 1 if mean_z >= 0.748 or 0.390 <= mean_z <= 0.425 else 0
    pants.data.update()


def create_clean_outfit(body, armature, fabric, strap, metal):
    del metal
    pants = build.c.extract_surface(
        body,
        armature,
        "Cargo_Continuous_Pants",
        pants_surface,
        fabric,
        0.011,
    )
    apply_profile(pants)
    build.clean_topology(pants)
    apply_profile(pants)
    assign_materials(pants, fabric, strap)
    return [pants]


def triangle_degenerates(obj: bpy.types.Object) -> int:
    obj.data.calc_loop_triangles()
    return sum(
        1
        for triangle in obj.data.loop_triangles
        if (
            obj.data.vertices[triangle.vertices[1]].co
            - obj.data.vertices[triangle.vertices[0]].co
        )
        .cross(
            obj.data.vertices[triangle.vertices[2]].co
            - obj.data.vertices[triangle.vertices[0]].co
        )
        .length_squared
        <= 1e-20
    )


def longest_edge(obj: bpy.types.Object) -> float:
    return max(
        (
            obj.data.vertices[edge.vertices[0]].co
            - obj.data.vertices[edge.vertices[1]].co
        ).length
        for edge in obj.data.edges
    )


def extent(obj: bpy.types.Object, z0: float, z1: float) -> dict[str, float | int]:
    points = [vertex.co for vertex in obj.data.vertices if z0 <= vertex.co.z <= z1]
    if not points:
        return {"vertices": 0, "width": 0.0, "depth": 0.0}
    xs = [point.x for point in points]
    ys = [point.y for point in points]
    return {
        "vertices": len(points),
        "width": max(xs) - min(xs),
        "depth": max(ys) - min(ys),
    }


def jump(a: float, b: float) -> float:
    return abs(a - b) / max(abs(a), abs(b), 1e-6)


def audit() -> dict[str, object]:
    pants = bpy.data.objects.get("Cargo_Continuous_Pants")
    garment_names = sorted(
        obj.name
        for obj in bpy.data.objects
        if obj.type == "MESH"
        and not obj.name.startswith("SiroinoSotai_PC")
        and obj.name != "Studio_Floor"
    )
    checks: dict[str, object] = {"garmentMeshNames": garment_names}
    if pants is None:
        return {"schemaVersion": 1, "passed": False, "checks": checks}

    coordinates = [component for vertex in pants.data.vertices for component in vertex.co]
    xs = [vertex.co.x for vertex in pants.data.vertices]
    ys = [vertex.co.y for vertex in pants.data.vertices]
    zs = [vertex.co.z for vertex in pants.data.vertices]
    bands = {
        "upperThigh": extent(pants, 0.46, 0.55),
        "knee": extent(pants, 0.30, 0.40),
        "hem": extent(pants, 0.105, 0.18),
    }
    degenerates = triangle_degenerates(pants)
    maximum_edge = longest_edge(pants)
    total_width = max(xs, default=0.0) - min(xs, default=0.0)
    total_depth = max(ys, default=0.0) - min(ys, default=0.0)
    shape_keys = (
        0
        if pants.data.shape_keys is None
        else max(0, len(pants.data.shape_keys.key_blocks) - 1)
    )
    foot_intrusions = sum(
        1
        for vertex in pants.data.vertices
        if vertex.co.z < 0.10 or (vertex.co.z < 0.18 and abs(vertex.co.y) > 0.12)
    )
    metrics = {
        "vertices": len(pants.data.vertices),
        "triangles": len(pants.data.loop_triangles),
        "minimumZ": min(zs, default=0.0),
        "maximumZ": max(zs, default=0.0),
        "totalWidth": total_width,
        "totalDepth": total_depth,
        "maximumEdgeLength": maximum_edge,
        "degenerateTriangles": degenerates,
        "uvLayers": len(pants.data.uv_layers),
        "materialSlots": len(pants.data.materials),
        "shapeKeys": shape_keys,
        "footIntrusionVertices": foot_intrusions,
        "bands": bands,
    }
    checks["metrics"] = metrics
    checks.update(
        {
            "singleShellOnly": garment_names == ["Cargo_Continuous_Pants"],
            "finiteCoordinatesPassed": all(
                math.isfinite(float(value)) for value in coordinates
            ),
            "spikeGuardPassed": maximum_edge <= 0.075,
            "topologyPassed": degenerates == 0,
            "uvPassed": len(pants.data.uv_layers) > 0,
            "materialSeparationPassed": len(pants.data.materials) >= 2,
            "shapeKeyIsolationPassed": shape_keys == 0,
            "footAndFloorClearancePassed": foot_intrusions == 0
            and min(zs, default=0.0) >= 0.10,
            "controlledVolumePassed": 0.34 <= total_width <= 0.45
            and 0.19 <= total_depth <= 0.29,
            "profileContinuityPassed": (
                jump(float(bands["upperThigh"]["width"]), float(bands["knee"]["width"])) <= 0.18
                and jump(float(bands["knee"]["width"]), float(bands["hem"]["width"])) <= 0.16
                and jump(float(bands["upperThigh"]["depth"]), float(bands["knee"]["depth"])) <= 0.20
                and jump(float(bands["knee"]["depth"]), float(bands["hem"]["depth"])) <= 0.18
            ),
        }
    )
    required = [
        "singleShellOnly",
        "finiteCoordinatesPassed",
        "spikeGuardPassed",
        "topologyPassed",
        "uvPassed",
        "materialSeparationPassed",
        "shapeKeyIsolationPassed",
        "footAndFloorClearancePassed",
        "controlledVolumePassed",
        "profileContinuityPassed",
    ]
    return {
        "schemaVersion": 1,
        "passed": all(bool(checks[name]) for name in required),
        "checks": checks,
    }


def record(report: dict[str, object]) -> None:
    _, job = build.c.load_job()
    path = build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    manifest["status"] = "WORKING"
    manifest["designRevision"] = "v23-spike-guarded-clean-single-shell"
    manifest["wearabilityAudit"] = report
    manifest.setdefault("technicalGates", {})["latestGeometryRender"] = (
        "PASS" if report.get("passed") is True else "FAIL"
    )
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


build.create_outfit = create_clean_outfit


if __name__ == "__main__":
    build.main()
    result = audit()
    record(result)
    base.save_distribution_blend()
    if result.get("passed") is not True:
        raise RuntimeError(f"wearability audit failed: {result}")
    raise SystemExit(0)
