#!/usr/bin/env python3
"""Spike-free straight-wide fit candidate for Siroino Wide Cargo.

Latest main still rendered as tight upper-thigh leggings with calf balloons and
showed thin spikes around the waist.  The v20 cross-section already produced a
stable 0.40 m straight-wide silhouette, but its shared shape-key helper corrupted
the Basis mesh.  This candidate keeps that proven one-shell profile, attached
material regions and armature weights, while deliberately deferring size shape
keys until five-view and bone-pose renders pass without spikes.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_entry_v8 as production

build = production.build
base = production.v7
_original_create_outfit = build.create_outfit


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def lerp(start: float, end: float, amount: float) -> float:
    return start + (end - start) * amount


def smoothstep(edge0: float, edge1: float, value: float) -> float:
    if abs(edge1 - edge0) <= 1e-9:
        return 1.0 if value >= edge1 else 0.0
    amount = clamp((value - edge0) / (edge1 - edge0), 0.0, 1.0)
    return amount * amount * (3.0 - 2.0 * amount)


def remove_object(obj: bpy.types.Object) -> None:
    if obj.name in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)


def pants_surface(point) -> bool:
    if not (0.095 <= point.z <= 0.805):
        return False
    if abs(point.x) > 0.34:
        return False
    if point.z < 0.180 and abs(point.y) > 0.065:
        return False
    return True


def profile_down(z: float) -> float:
    return 1.0 - smoothstep(0.095, 0.620, z)


def target_cross_section(x: float, y: float, z: float) -> tuple[float, float]:
    side = -1.0 if x < 0.0 else 1.0
    down = profile_down(z)
    center_abs = lerp(0.088, 0.070, down)
    outer_radius = lerp(0.118, 0.132, down)
    inner_gap = lerp(0.010, 0.009, down)
    inner_radius = max(0.045, center_abs - inner_gap)
    depth_radius = lerp(0.102, 0.112, down)

    center_x = side * center_abs
    local_x = x - center_x
    if abs(local_x) <= 1e-9 and abs(y) <= 1e-9:
        return x, y
    angle = math.atan2(y, local_x)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    outer_weight = clamp((side * cosine + 1.0) * 0.5, 0.0, 1.0)
    radius_x = lerp(inner_radius, outer_radius, outer_weight)
    return center_x + cosine * radius_x, sine * depth_radius


def apply_straight_leg_profile(obj: bpy.types.Object) -> None:
    for vertex in obj.data.vertices:
        x, y, z = vertex.co
        upper_amount = smoothstep(0.620, 0.805, z)
        fitted_x = x * lerp(1.105, 1.055, upper_amount)
        fitted_y = y * lerp(1.125, 1.075, upper_amount)
        target_x, target_y = target_cross_section(x, y, z)
        target_amount = 1.0 - smoothstep(0.540, 0.680, z)

        if z >= 0.430 and abs(x) < 0.022:
            bridge_amount = smoothstep(0.003, 0.022, abs(x))
            target_amount *= lerp(0.25, 1.0, bridge_amount)

        vertex.co.x = lerp(fitted_x, target_x, target_amount)
        vertex.co.y = lerp(fitted_y, target_y, target_amount)
        if z < 0.125:
            vertex.co.z += 0.004 * (1.0 - smoothstep(0.095, 0.125, z))
    obj.data.update(calc_edges=True)


def assign_material_regions(
    pants: bpy.types.Object,
    fabric: bpy.types.Material,
    strap: bpy.types.Material,
) -> None:
    base.tune_material(fabric, base=(0.020, 0.024, 0.032), roughness=0.72)
    base.tune_material(strap, base=(0.006, 0.008, 0.012), roughness=0.42)
    pants.data.materials.clear()
    pants.data.materials.append(fabric)
    pants.data.materials.append(strap)
    for polygon in pants.data.polygons:
        mean_z = sum(pants.data.vertices[index].co.z for index in polygon.vertices) / len(polygon.vertices)
        polygon.material_index = 1 if mean_z >= 0.755 or 0.430 <= mean_z <= 0.470 else 0
    pants.data.update()


def create_single_shell_pants(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    fabric: bpy.types.Material,
    strap: bpy.types.Material,
) -> bpy.types.Object:
    pants = build.c.extract_surface(
        body,
        armature,
        "Cargo_Continuous_Pants",
        pants_surface,
        fabric,
        0.0120,
    )
    apply_straight_leg_profile(pants)
    build.clean_topology(pants)
    assign_material_regions(pants, fabric, strap)
    # Shape keys are intentionally deferred.  Bone weights and the armature
    # modifier remain available for the required crouch/sit/prone pose renders.
    return pants


def create_outfit_as_single_shell(body, armature, fabric, strap, metal):
    generated = _original_create_outfit(body, armature, fabric, strap, metal)
    for obj in generated:
        remove_object(obj)
    return [create_single_shell_pants(body, armature, fabric, strap)]


def degenerate_triangles(obj: bpy.types.Object) -> int:
    obj.data.calc_loop_triangles()
    count = 0
    for triangle in obj.data.loop_triangles:
        a, b, c = (obj.data.vertices[index].co for index in triangle.vertices)
        if (b - a).cross(c - a).length_squared <= 1e-20:
            count += 1
    return count


def band_extent(obj: bpy.types.Object, minimum_z: float, maximum_z: float) -> dict[str, float | int]:
    vertices = [vertex for vertex in obj.data.vertices if minimum_z <= vertex.co.z <= maximum_z]
    if not vertices:
        return {"vertices": 0, "width": 0.0, "depth": 0.0}
    xs = [vertex.co.x for vertex in vertices]
    ys = [vertex.co.y for vertex in vertices]
    return {"vertices": len(vertices), "width": max(xs) - min(xs), "depth": max(ys) - min(ys)}


def relative_jump(first: float, second: float) -> float:
    return abs(first - second) / max(abs(first), abs(second), 1e-6)


def audit_wearability() -> dict[str, object]:
    expected_name = "Cargo_Continuous_Pants"
    pants = bpy.data.objects.get(expected_name)
    garment_meshes = sorted(
        obj.name for obj in bpy.data.objects
        if obj.type == "MESH"
        and not obj.name.startswith("SiroinoSotai_PC")
        and obj.name != "Studio_Floor"
    )
    checks: dict[str, object] = {
        "garmentMeshNames": garment_meshes,
        "singleShellOnly": garment_meshes == [expected_name],
        "shapeKeysDeferred": True,
    }
    if pants is None:
        return {"schemaVersion": 1, "passed": False, "checks": checks}

    pants.data.calc_loop_triangles()
    xs = [vertex.co.x for vertex in pants.data.vertices]
    ys = [vertex.co.y for vertex in pants.data.vertices]
    zs = [vertex.co.z for vertex in pants.data.vertices]
    inner_lower_vertices = [
        vertex for vertex in pants.data.vertices
        if vertex.co.z <= 0.42 and abs(vertex.co.x) <= 0.040
    ]
    foot_like_vertices = [
        vertex for vertex in pants.data.vertices
        if vertex.co.z < 0.180 and abs(vertex.co.y) > 0.090
    ]
    bands = {
        "upperThigh": band_extent(pants, 0.46, 0.55),
        "knee": band_extent(pants, 0.30, 0.40),
        "hem": band_extent(pants, 0.10, 0.18),
    }
    width_jump_upper_knee = relative_jump(float(bands["upperThigh"]["width"]), float(bands["knee"]["width"]))
    width_jump_knee_hem = relative_jump(float(bands["knee"]["width"]), float(bands["hem"]["width"]))
    depth_jump_upper_knee = relative_jump(float(bands["upperThigh"]["depth"]), float(bands["knee"]["depth"]))
    depth_jump_knee_hem = relative_jump(float(bands["knee"]["depth"]), float(bands["hem"]["depth"]))
    shape_key_count = 0 if pants.data.shape_keys is None else max(0, len(pants.data.shape_keys.key_blocks) - 1)
    metrics = {
        "vertices": len(pants.data.vertices),
        "triangles": len(pants.data.loop_triangles),
        "shapeKeys": shape_key_count,
        "minimumX": min(xs, default=0.0),
        "maximumX": max(xs, default=0.0),
        "minimumY": min(ys, default=0.0),
        "maximumY": max(ys, default=0.0),
        "minimumZ": min(zs, default=0.0),
        "maximumZ": max(zs, default=0.0),
        "totalWidth": max(xs, default=0.0) - min(xs, default=0.0),
        "totalDepth": max(ys, default=0.0) - min(ys, default=0.0),
        "lowerInnerCoverageVertices": len(inner_lower_vertices),
        "footLikeVertices": len(foot_like_vertices),
        "degenerateTriangles": degenerate_triangles(pants),
        "uvLayers": len(pants.data.uv_layers),
        "materialSlots": len(pants.data.materials),
        "bands": bands,
        "widthJumpUpperKnee": width_jump_upper_knee,
        "widthJumpKneeHem": width_jump_knee_hem,
        "depthJumpUpperKnee": depth_jump_upper_knee,
        "depthJumpKneeHem": depth_jump_knee_hem,
    }
    checks["metrics"] = metrics

    finite_bounds = (
        max(abs(metrics["minimumX"]), abs(metrics["maximumX"])) < 0.5
        and max(abs(metrics["minimumY"]), abs(metrics["maximumY"])) < 0.5
        and -0.05 < metrics["minimumZ"] < 0.2
        and metrics["maximumZ"] < 1.0
    )
    continuity = (
        width_jump_upper_knee <= 0.16
        and width_jump_knee_hem <= 0.14
        and depth_jump_upper_knee <= 0.18
        and depth_jump_knee_hem <= 0.16
    )
    checks.update({
        "topologyPassed": metrics["degenerateTriangles"] == 0,
        "finiteBoundsPassed": finite_bounds,
        "heightPassed": 0.085 <= metrics["minimumZ"] <= 0.135 and metrics["maximumZ"] >= 0.79,
        "wideSilhouettePassed": 0.38 <= metrics["totalWidth"] <= 0.46 and 0.20 <= metrics["totalDepth"] <= 0.28,
        "profileContinuityPassed": continuity,
        "innerLegCoveragePassed": len(inner_lower_vertices) >= 40,
        "footExclusionPassed": len(foot_like_vertices) == 0,
        "shapeKeyIsolationPassed": shape_key_count == 0,
        "uvPassed": len(pants.data.uv_layers) > 0,
        "materialSeparationPassed": len(pants.data.materials) >= 2,
    })
    passed = all([
        checks["singleShellOnly"], checks["topologyPassed"], checks["finiteBoundsPassed"],
        checks["heightPassed"], checks["wideSilhouettePassed"], checks["profileContinuityPassed"],
        checks["innerLegCoveragePassed"], checks["footExclusionPassed"], checks["shapeKeyIsolationPassed"],
        checks["uvPassed"], checks["materialSeparationPassed"],
    ])
    return {"schemaVersion": 1, "passed": passed, "checks": checks}


def record_wearability(report: dict[str, object]) -> None:
    _, job = build.c.load_job()
    manifest_path = build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    manifest["wearabilityAudit"] = report
    manifest["designRevision"] = "v21-clean-straight-wide-base"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


build.create_outfit = create_outfit_as_single_shell

if __name__ == "__main__":
    build.main()
    report = audit_wearability()
    record_wearability(report)
    base.save_distribution_blend()
    if report.get("passed") is not True:
        raise RuntimeError(f"single-shell wearability audit failed: {report}")
    raise SystemExit(0)
