#!/usr/bin/env python3
"""Shape-key-isolated straight-leg rebuild for Siroino Wide Cargo.

v20 produced the intended continuous wide silhouette, but the actual five-view
render exposed long spikes from the waist and crotch. The same build reported
otherwise impossible Basis bounds while every height-band measurement remained
normal. The shared helper creates Basis and target keys with Blender's default
``from_mix=True`` behavior, so this revision removes shape-key generation from
the fit-validation stage and leaves the proven base mesh and bone weights intact.

The purpose of v21 is controlled isolation: five-view and six-pose renders must
first prove that the base pants are spike-free and wearable. Size shape keys are
reintroduced only through a safe ``from_mix=False`` implementation after that
visual gate passes.
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


def create_single_shell_pants(body, armature, fabric) -> bpy.types.Object:
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
    # Deliberately no shape keys in this isolation pass. The armature modifier
    # and transferred body weights remain active for all required pose renders.
    return pants


def create_outfit_as_single_shell(body, armature, fabric, strap, metal):
    generated = _original_create_outfit(body, armature, fabric, strap, metal)
    for obj in generated:
        remove_object(obj)
    return [create_single_shell_pants(body, armature, fabric)]


def degenerate_triangles(obj: bpy.types.Object) -> int:
    mesh = obj.data
    mesh.calc_loop_triangles()
    count = 0
    for triangle in mesh.loop_triangles:
        a, b, c = (mesh.vertices[index].co for index in triangle.vertices)
        if (b - a).cross(c - a).length_squared <= 1e-20:
            count += 1
    return count


def band_extent(obj: bpy.types.Object, minimum_z: float, maximum_z: float) -> dict[str, float | int]:
    vertices = [
        vertex for vertex in obj.data.vertices
        if minimum_z <= vertex.co.z <= maximum_z
    ]
    if not vertices:
        return {"vertices": 0, "width": 0.0, "depth": 0.0}
    xs = [vertex.co.x for vertex in vertices]
    ys = [vertex.co.y for vertex in vertices]
    return {
        "vertices": len(vertices),
        "width": max(xs) - min(xs),
        "depth": max(ys) - min(ys),
    }


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
        "singleShellPresent": pants is not None,
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
    degenerates = degenerate_triangles(pants)
    bands = {
        "upperThigh": band_extent(pants, 0.46, 0.55),
        "knee": band_extent(pants, 0.30, 0.40),
        "hem": band_extent(pants, 0.10, 0.18),
    }
    width_jump_upper_knee = relative_jump(
        float(bands["upperThigh"]["width"]), float(bands["knee"]["width"])
    )
    width_jump_knee_hem = relative_jump(
        float(bands["knee"]["width"]), float(bands["hem"]["width"])
    )
    depth_jump_upper_knee = relative_jump(
        float(bands["upperThigh"]["depth"]), float(bands["knee"]["depth"])
    )
    depth_jump_knee_hem = relative_jump(
        float(bands["knee"]["depth"]), float(bands["hem"]["depth"])
    )
    metrics = {
        "vertices": len(pants.data.vertices),
        "triangles": len(pants.data.loop_triangles),
        "shapeKeys": 0 if pants.data.shape_keys is None else len(pants.data.shape_keys.key_blocks) - 1,
        "minimumX": min(xs, default=0.0),
        "maximumX": max(xs, default=0.0),
        "minimumY": min(ys, default=0.0),
        "maximumY": max(ys, default=0.0),
        "minimumZ": min(zs, default=0.0),
        "maximumZ": max(zs, default=0.0),
        "totalWidth": max(xs, default=0.0) - min(xs, default=0.0),
        "totalDepth": max(ys, default=0.0) - min(ys, default=0.0),
        "lowerInnerCoverageVertices": len(inner_lower_vertices),
        "degenerateTriangles": degenerates,
        "bands": bands,
        "widthJumpUpperKnee": width_jump_upper_knee,
        "widthJumpKneeHem": width_jump_knee_hem,
        "depthJumpUpperKnee": depth_jump_upper_knee,
        "depthJumpKneeHem": depth_jump_knee_hem,
    }
    checks["metrics"] = metrics

    topology_pass = degenerates == 0
    finite_bounds_pass = (
        max(abs(metrics["minimumX"]), abs(metrics["maximumX"])) < 0.5
        and max(abs(metrics["minimumY"]), abs(metrics["maximumY"])) < 0.5
        and -0.05 < metrics["minimumZ"] < 0.2
        and metrics["maximumZ"] < 1.0
    )
    height_pass = 0.085 <= metrics["minimumZ"] <= 0.135 and metrics["maximumZ"] >= 0.79
    width_pass = 0.38 <= metrics["totalWidth"] <= 0.46
    depth_pass = 0.20 <= metrics["totalDepth"] <= 0.26
    band_population_pass = all(int(item["vertices"]) >= 100 for item in bands.values())
    continuity_pass = (
        width_jump_upper_knee <= 0.16
        and width_jump_knee_hem <= 0.14
        and depth_jump_upper_knee <= 0.18
        and depth_jump_knee_hem <= 0.16
    )
    inner_coverage_pass = len(inner_lower_vertices) >= 40
    no_shape_keys_pass = metrics["shapeKeys"] == 0
    checks.update({
        "topologyPassed": topology_pass,
        "finiteBoundsPassed": finite_bounds_pass,
        "heightPassed": height_pass,
        "wideSilhouettePassed": width_pass and depth_pass,
        "profileBandsPopulated": band_population_pass,
        "profileContinuityPassed": continuity_pass,
        "innerLegCoveragePassed": inner_coverage_pass,
        "shapeKeyIsolationPassed": no_shape_keys_pass,
    })
    passed = (
        garment_meshes == [expected_name]
        and topology_pass and finite_bounds_pass and height_pass
        and width_pass and depth_pass and band_population_pass
        and continuity_pass and inner_coverage_pass and no_shape_keys_pass
    )
    return {"schemaVersion": 1, "passed": passed, "checks": checks}


def record_wearability(report: dict[str, object]) -> None:
    _, job = build.c.load_job()
    manifest_path = build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    manifest["wearabilityAudit"] = report
    manifest["designRevision"] = "v21-shape-key-isolation"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


build.create_outfit = create_outfit_as_single_shell

if __name__ == "__main__":
    build.main()
    report = audit_wearability()
    record_wearability(report)
    base.save_distribution_blend()
    if report.get("passed") is not True:
        raise RuntimeError(f"single-shell wearability audit failed: {report}")
    raise SystemExit(0)
