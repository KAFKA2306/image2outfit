#!/usr/bin/env python3
"""Smooth elliptical single-shell rebuild for Siroino Wide Cargo.

The v18 render finally produced sufficient overall width and complete leg
coverage, but the silhouette changed abruptly at the knee: tight upper thighs,
box-shaped knees, and oversized bell hems. This revision removes every hard
inside/outside branch and maps each leg into a smoothly interpolated elliptical
cross-section from upper thigh to ankle.

The resulting garment remains one continuous body-derived shell. Its inner edges
stay close to the centreline, while the outer and front/back radii vary gradually
with height. A light XY-only smooth pass removes residual source-body contour
steps without shrinking the hem vertically.
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
    """Select a continuous lower-body shell with a clean ankle opening."""
    if not (0.095 <= point.z <= 0.805):
        return False
    if abs(point.x) > 0.34:
        return False
    # Exclude the source instep and toes while retaining the ankle circumference.
    if point.z < 0.180 and abs(point.y) > 0.065:
        return False
    return True


def profile_down(z: float) -> float:
    """Return a smooth 0-at-upper-thigh to 1-at-hem coordinate."""
    return 1.0 - smoothstep(0.095, 0.570, z)


def target_cross_section(
    x: float,
    y: float,
    z: float,
) -> tuple[float, float]:
    """Map a source-body point to a smooth asymmetric leg ellipse."""
    side = -1.0 if x < 0.0 else 1.0
    down = profile_down(z)

    # The centre narrows gently toward the ankle. Outer radius grows only
    # slightly, producing a straight wide-leg line rather than a bell flare.
    center_abs = lerp(0.088, 0.070, down)
    outer_radius = lerp(0.108, 0.125, down)
    inner_gap = lerp(0.010, 0.009, down)
    inner_radius = max(0.045, center_abs - inner_gap)
    depth_radius = lerp(0.096, 0.110, down)

    center_x = side * center_abs
    local_x = x - center_x
    if abs(local_x) <= 1e-9 and abs(y) <= 1e-9:
        return x, y

    angle = math.atan2(y, local_x)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    outer_direction = side * cosine
    outer_weight = clamp((outer_direction + 1.0) * 0.5, 0.0, 1.0)
    radius_x = lerp(inner_radius, outer_radius, outer_weight)

    return (
        center_x + cosine * radius_x,
        sine * depth_radius,
    )


def apply_smooth_elliptical_profile(obj: bpy.types.Object) -> None:
    """Blend body fit into the target wide-leg cross-sections continuously."""
    for vertex in obj.data.vertices:
        x, y, z = vertex.co

        # Keep the waist and upper pelvis close, but not skin-tight.
        upper_amount = smoothstep(0.570, 0.805, z)
        fitted_x = x * lerp(1.090, 1.055, upper_amount)
        fitted_y = y * lerp(1.115, 1.075, upper_amount)

        target_x, target_y = target_cross_section(x, y, z)
        # Full target below z=0.45, body-fitted above z=0.60, and a smooth
        # transition through the upper thigh. This removes the v18 knee step.
        target_amount = 1.0 - smoothstep(0.450, 0.600, z)

        # Preserve the central crotch bridge near the pelvis so the single shell
        # cannot open into two disconnected chaps during deformation.
        if z >= 0.400 and abs(x) < 0.030:
            bridge_amount = smoothstep(0.005, 0.030, abs(x))
            target_amount *= lerp(0.20, 1.0, bridge_amount)

        vertex.co.x = lerp(fitted_x, target_x, target_amount)
        vertex.co.y = lerp(fitted_y, target_y, target_amount)

        if z < 0.125:
            vertex.co.z += 0.004 * (
                1.0 - smoothstep(0.095, 0.125, z)
            )

    obj.data.update(calc_edges=True)


def smooth_xy(obj: bpy.types.Object) -> None:
    """Remove local contour steps without shortening the garment vertically."""
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    modifier = obj.modifiers.new("Wide cargo contour smoothing", "SMOOTH")
    modifier.factor = 0.16
    modifier.iterations = 3
    modifier.use_x = True
    modifier.use_y = True
    modifier.use_z = False
    while obj.modifiers.find(modifier.name) > 0:
        bpy.ops.object.modifier_move_up(modifier=modifier.name)
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    obj.select_set(False)


def create_single_shell_pants(body, armature, fabric) -> bpy.types.Object:
    pants = build.c.extract_surface(
        body,
        armature,
        "Cargo_Continuous_Pants",
        pants_surface,
        fabric,
        0.0120,
    )
    apply_smooth_elliptical_profile(pants)
    smooth_xy(pants)
    build.clean_topology(pants)
    build.c.add_nearest_shape_keys(pants, body)
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


def band_extent(
    obj: bpy.types.Object,
    minimum_z: float,
    maximum_z: float,
) -> dict[str, float | int]:
    vertices = [
        vertex
        for vertex in obj.data.vertices
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
    denominator = max(abs(first), abs(second), 1e-6)
    return abs(first - second) / denominator


def audit_wearability() -> dict[str, object]:
    expected_name = "Cargo_Continuous_Pants"
    pants = bpy.data.objects.get(expected_name)
    garment_meshes = sorted(
        obj.name
        for obj in bpy.data.objects
        if obj.type == "MESH"
        and not obj.name.startswith("SiroinoSotai_PC")
        and obj.name != "Studio_Floor"
    )

    checks: dict[str, object] = {
        "garmentMeshNames": garment_meshes,
        "singleShellPresent": pants is not None,
        "singleShellOnly": garment_meshes == [expected_name],
    }
    if pants is None:
        return {"schemaVersion": 1, "passed": False, "checks": checks}

    pants.data.calc_loop_triangles()
    xs = [vertex.co.x for vertex in pants.data.vertices]
    ys = [vertex.co.y for vertex in pants.data.vertices]
    zs = [vertex.co.z for vertex in pants.data.vertices]
    lower_vertices = [vertex for vertex in pants.data.vertices if vertex.co.z <= 0.42]
    inner_lower_vertices = [
        vertex for vertex in lower_vertices if abs(vertex.co.x) <= 0.040
    ]
    degenerates = degenerate_triangles(pants)

    bands = {
        "upperThigh": band_extent(pants, 0.46, 0.55),
        "knee": band_extent(pants, 0.30, 0.40),
        "hem": band_extent(pants, 0.10, 0.18),
    }
    width_jump_upper_knee = relative_jump(
        float(bands["upperThigh"]["width"]),
        float(bands["knee"]["width"]),
    )
    width_jump_knee_hem = relative_jump(
        float(bands["knee"]["width"]),
        float(bands["hem"]["width"]),
    )
    depth_jump_upper_knee = relative_jump(
        float(bands["upperThigh"]["depth"]),
        float(bands["knee"]["depth"]),
    )
    depth_jump_knee_hem = relative_jump(
        float(bands["knee"]["depth"]),
        float(bands["hem"]["depth"]),
    )

    metrics = {
        "vertices": len(pants.data.vertices),
        "triangles": len(pants.data.loop_triangles),
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
    height_pass = (
        0.085 <= metrics["minimumZ"] <= 0.135
        and metrics["maximumZ"] >= 0.79
    )
    width_pass = 0.36 <= metrics["totalWidth"] <= 0.46
    depth_pass = 0.20 <= metrics["totalDepth"] <= 0.27
    band_population_pass = all(
        int(item["vertices"]) >= 100 for item in bands.values()
    )
    continuity_pass = (
        width_jump_upper_knee <= 0.24
        and width_jump_knee_hem <= 0.20
        and depth_jump_upper_knee <= 0.22
        and depth_jump_knee_hem <= 0.18
    )
    inner_coverage_pass = len(inner_lower_vertices) >= 40

    checks.update(
        {
            "topologyPassed": topology_pass,
            "heightPassed": height_pass,
            "wideSilhouettePassed": width_pass and depth_pass,
            "profileBandsPopulated": band_population_pass,
            "profileContinuityPassed": continuity_pass,
            "innerLegCoveragePassed": inner_coverage_pass,
        }
    )
    passed = (
        garment_meshes == [expected_name]
        and topology_pass
        and height_pass
        and width_pass
        and depth_pass
        and band_population_pass
        and continuity_pass
        and inner_coverage_pass
    )
    return {"schemaVersion": 1, "passed": passed, "checks": checks}


def record_wearability(report: dict[str, object]) -> None:
    _, job = build.c.load_job()
    manifest_path = build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    manifest["wearabilityAudit"] = report
    manifest["designRevision"] = "v19-smooth-elliptical-wide-cargo"
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
