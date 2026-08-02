#!/usr/bin/env python3
"""Rear-safe Siroino Wide Cargo rebuild.

The v23 shell passed global bounds checks but could still expose the inner thigh
and intersect the rear pelvis because its audit only measured whole-garment
width/depth.  This revision adds asymmetric rear-seat clearance, a smooth
centre/crotch mapping, stronger inner-leg coverage, and explicit rear/inner
coverage gates before previews are accepted.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import bpy

import siroino_wide_cargo_release_refit_v23 as v23

build = v23.build
base = v23.base


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
    """Keep a continuous waist-to-ankle source shell with no foot surface."""
    if not (0.105 <= point.z <= 0.815):
        return False
    if abs(point.x) > 0.345:
        return False
    if point.z < 0.190 and abs(point.y) > 0.062:
        return False
    return True


def target_cross_section(x: float, y: float, z: float) -> tuple[float, float]:
    """Return a straight-wide leg section with extra rear-seat clearance."""
    side = -1.0 if x < 0.0 else 1.0
    down = 1.0 - smoothstep(0.105, 0.640, z)
    centre_x = side * lerp(0.086, 0.071, down)
    outer_radius = lerp(0.116, 0.128, down)
    inner_radius = lerp(0.069, 0.062, down)
    front_depth = lerp(0.098, 0.105, down)
    rear_depth = lerp(0.116, 0.109, down)

    local_x = x - centre_x
    angle = math.atan2(y, local_x)
    c = math.cos(angle)
    s = math.sin(angle)
    outer_weight = clamp((side * c + 1.0) * 0.5, 0.0, 1.0)
    radius_x = lerp(inner_radius, outer_radius, outer_weight)
    radius_y = rear_depth if s >= 0.0 else front_depth
    return centre_x + c * radius_x, s * radius_y


def apply_profile(obj: bpy.types.Object) -> None:
    """Apply a rear-safe profile without creating centre-line spikes."""
    for vertex in obj.data.vertices:
        x, y, z = vertex.co
        target_x, target_y = target_cross_section(x, y, z)

        # Carry the controlled wide section through the upper thigh.  The
        # previous 0.68 cut-off left the rear pelvis almost body-tight.
        section_mix = 1.0 - smoothstep(0.610, 0.755, z)
        upper_t = smoothstep(0.610, 0.815, z)
        fitted_x = x * lerp(1.085, 1.055, upper_t)
        fitted_y_scale = lerp(1.105, 1.075, upper_t)
        if y > 0.0:
            fitted_y_scale += lerp(0.050, 0.030, upper_t)
        fitted_y = y * fitted_y_scale

        # Near the centre seam, fade X remapping rather than disabling the
        # whole profile.  Y still receives clearance, preventing a rear crotch
        # pinch while avoiding the old needle-like waist spikes.
        centre_mix = smoothstep(0.006, 0.046, abs(x))
        x_mix = section_mix * centre_mix
        new_x = lerp(fitted_x, target_x, x_mix)
        new_y = lerp(fitted_y, target_y, section_mix)

        # Add a local rear-seat/yoke allowance.  Front geometry is unchanged;
        # the positive-Y side is the rear in the Siroino source coordinates.
        rear_zone = smoothstep(0.485, 0.610, z) * (1.0 - smoothstep(0.765, 0.815, z))
        centre_zone = 1.0 - smoothstep(0.020, 0.155, abs(x))
        if y > 0.0:
            new_y += 0.010 * rear_zone * (0.55 + 0.45 * centre_zone)

        # Pull the inner thigh slightly toward the centre to eliminate the
        # vertical skin slit visible from the rear, without merging the legs.
        inner_zone = (
            (1.0 - smoothstep(0.030, 0.100, abs(x)))
            * smoothstep(0.395, 0.485, z)
            * (1.0 - smoothstep(0.605, 0.690, z))
        )
        new_x *= 1.0 - 0.10 * inner_zone

        vertex.co.x = clamp(new_x, -0.230, 0.230)
        vertex.co.y = clamp(new_y, -0.150, 0.160)
        vertex.co.z = clamp(z, 0.105, 0.820)

    obj.data.update(calc_edges=True)


def assign_materials(pants: bpy.types.Object, fabric, strap) -> None:
    base.tune_material(fabric, base=(0.026, 0.031, 0.043), roughness=0.76)
    base.tune_material(strap, base=(0.004, 0.006, 0.010), roughness=0.32)
    pants.data.materials.clear()
    pants.data.materials.append(fabric)
    pants.data.materials.append(strap)
    for polygon in pants.data.polygons:
        mean_z = sum(pants.data.vertices[i].co.z for i in polygon.vertices) / len(polygon.vertices)
        polygon.material_index = 1 if mean_z >= 0.752 or 0.405 <= mean_z <= 0.438 else 0
    pants.data.update()


def create_rear_safe_outfit(body, armature, fabric, strap, metal):
    del metal
    pants = build.c.extract_surface(
        body,
        armature,
        "Cargo_Continuous_Pants",
        pants_surface,
        fabric,
        0.015,
    )
    apply_profile(pants)
    build.clean_topology(pants)
    apply_profile(pants)
    assign_materials(pants, fabric, strap)
    return [pants]


def triangle_degenerates(obj: bpy.types.Object) -> int:
    obj.data.calc_loop_triangles()
    total = 0
    for tri in obj.data.loop_triangles:
        a, b, c = (obj.data.vertices[i].co for i in tri.vertices)
        if (b - a).cross(c - a).length_squared <= 1e-20:
            total += 1
    return total


def longest_edge(obj: bpy.types.Object) -> float:
    maximum = 0.0
    for edge in obj.data.edges:
        a = obj.data.vertices[edge.vertices[0]].co
        b = obj.data.vertices[edge.vertices[1]].co
        maximum = max(maximum, (a - b).length)
    return maximum


def extent(obj: bpy.types.Object, z0: float, z1: float) -> dict[str, float | int]:
    points = [v.co for v in obj.data.vertices if z0 <= v.co.z <= z1]
    if not points:
        return {"vertices": 0, "width": 0.0, "depth": 0.0, "rear": 0.0, "front": 0.0}
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    return {
        "vertices": len(points),
        "width": max(xs) - min(xs),
        "depth": max(ys) - min(ys),
        "rear": max(ys),
        "front": min(ys),
    }


def audit() -> dict[str, object]:
    pants = bpy.data.objects.get("Cargo_Continuous_Pants")
    garment_names = sorted(
        obj.name for obj in bpy.data.objects
        if obj.type == "MESH"
        and not obj.name.startswith("SiroinoSotai_PC")
        and obj.name != "Studio_Floor"
    )
    checks: dict[str, object] = {"garmentMeshNames": garment_names}
    if pants is None:
        return {"schemaVersion": 1, "passed": False, "checks": checks}

    pants.data.calc_loop_triangles()
    coordinates = [component for v in pants.data.vertices for component in v.co]
    finite = all(math.isfinite(float(value)) for value in coordinates)
    xs = [v.co.x for v in pants.data.vertices]
    ys = [v.co.y for v in pants.data.vertices]
    zs = [v.co.z for v in pants.data.vertices]
    bands = {
        "seat": extent(pants, 0.610, 0.755),
        "upperThigh": extent(pants, 0.485, 0.600),
        "knee": extent(pants, 0.300, 0.405),
        "hem": extent(pants, 0.105, 0.185),
    }
    inner_thigh = [
        v.co for v in pants.data.vertices
        if 0.430 <= v.co.z <= 0.610 and abs(v.co.x) <= 0.045
    ]
    rear_bridge = [
        p for p in inner_thigh
        if p.y >= 0.020 and 0.470 <= p.z <= 0.610
    ]
    degenerates = triangle_degenerates(pants)
    max_edge = longest_edge(pants)
    total_width = max(xs, default=0.0) - min(xs, default=0.0)
    total_depth = max(ys, default=0.0) - min(ys, default=0.0)
    shape_keys = 0 if pants.data.shape_keys is None else max(0, len(pants.data.shape_keys.key_blocks) - 1)
    foot_intrusions = sum(1 for v in pants.data.vertices if v.co.z < 0.10 or (v.co.z < 0.18 and abs(v.co.y) > 0.12))

    metrics = {
        "vertices": len(pants.data.vertices),
        "triangles": len(pants.data.loop_triangles),
        "minimumZ": min(zs, default=0.0),
        "maximumZ": max(zs, default=0.0),
        "totalWidth": total_width,
        "totalDepth": total_depth,
        "maximumEdgeLength": max_edge,
        "degenerateTriangles": degenerates,
        "uvLayers": len(pants.data.uv_layers),
        "materialSlots": len(pants.data.materials),
        "shapeKeys": shape_keys,
        "footIntrusionVertices": foot_intrusions,
        "innerThighCoverageVertices": len(inner_thigh),
        "rearBridgeVertices": len(rear_bridge),
        "bands": bands,
    }
    checks["metrics"] = metrics
    checks.update({
        "singleShellOnly": garment_names == ["Cargo_Continuous_Pants"],
        "finiteCoordinatesPassed": finite,
        "spikeGuardPassed": max_edge <= 0.075,
        "topologyPassed": degenerates == 0,
        "uvPassed": len(pants.data.uv_layers) > 0,
        "materialSeparationPassed": len(pants.data.materials) >= 2,
        "shapeKeyIsolationPassed": shape_keys == 0,
        "footAndFloorClearancePassed": foot_intrusions == 0 and min(zs, default=0.0) >= 0.10,
        "controlledVolumePassed": 0.35 <= total_width <= 0.46 and 0.21 <= total_depth <= 0.31,
        "rearSeatClearancePassed": float(bands["seat"]["rear"]) >= 0.105,
        "innerThighCoveragePassed": len(inner_thigh) >= 24,
        "rearCrotchBridgePassed": len(rear_bridge) >= 8,
        "straightWideProfilePassed": (
            abs(float(bands["upperThigh"]["width"]) - float(bands["knee"]["width"])) <= 0.075
            and abs(float(bands["knee"]["width"]) - float(bands["hem"]["width"])) <= 0.070
            and abs(float(bands["upperThigh"]["depth"]) - float(bands["knee"]["depth"])) <= 0.065
        ),
    })
    required = [
        "singleShellOnly", "finiteCoordinatesPassed", "spikeGuardPassed",
        "topologyPassed", "uvPassed", "materialSeparationPassed",
        "shapeKeyIsolationPassed", "footAndFloorClearancePassed",
        "controlledVolumePassed", "rearSeatClearancePassed",
        "innerThighCoveragePassed", "rearCrotchBridgePassed",
        "straightWideProfilePassed",
    ]
    return {"schemaVersion": 1, "passed": all(bool(checks[k]) for k in required), "checks": checks}


def record(report: dict[str, object]) -> None:
    _, job = build.c.load_job()
    path = build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    manifest["status"] = "WORKING"
    manifest["designRevision"] = "v24-rear-safe-inner-thigh-covered"
    manifest["wearabilityAudit"] = report
    gates = manifest.setdefault("technicalGates", {})
    gates["latestGeometryRender"] = "PASS" if report.get("passed") is True else "FAIL"
    gates["humanVisualReview"] = "PENDING"
    gates["humanPoseReview"] = "PENDING"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


build.create_outfit = create_rear_safe_outfit


if __name__ == "__main__":
    build.main()
    result = audit()
    record(result)
    base.save_distribution_blend()
    if result.get("passed") is not True:
        raise RuntimeError(f"v24 rear coverage audit failed: {result}")
    raise SystemExit(0)
