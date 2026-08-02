#!/usr/bin/env python3
"""Controlled single-shell rebuild for Siroino Wide Cargo.

The v18 artifact proved that a continuous shell removes the disconnected-knee
failure, but its nonlinear profile produced calf balloons, a stepped knee and a
hem that still wrapped around the feet.  This revision keeps one deformable
pants shell while applying a smooth, moderate wide-leg profile, a true ankle
cut, and material regions that remain attached to the same mesh.
"""
from __future__ import annotations

import json
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


def smoothstep(value: float) -> float:
    value = clamp(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def remove_object(obj: bpy.types.Object) -> None:
    if obj.name in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)


def pants_surface(point) -> bool:
    """Select waist-to-ankle body polygons and exclude all foot geometry."""
    if not (0.155 <= point.z <= 0.805):
        return False
    if abs(point.x) > 0.34:
        return False
    # The source instep and toes project along Y below the ankle.  A compact
    # source-space cross-section produces a clean open hem before reshaping.
    if point.z < 0.215 and abs(point.y) > 0.060:
        return False
    return True


def apply_wide_cargo_profile(obj: bpy.types.Object) -> None:
    """Create a smooth straight-wide silhouette without a calf balloon."""
    hem_z = 0.155
    hip_transition_z = 0.595
    span = hip_transition_z - hem_z

    for vertex in obj.data.vertices:
        x, y, z = vertex.co
        if z >= hip_transition_z:
            hip_t = smoothstep((z - hip_transition_z) / (0.805 - hip_transition_z))
            vertex.co.x *= 1.075 - 0.020 * hip_t
            vertex.co.y *= 1.095 - 0.020 * hip_t
            continue

        down = smoothstep((hip_transition_z - z) / span)
        side = -1.0 if x < 0.0 else 1.0
        center_abs = 0.090 - 0.028 * down
        leg_center_x = side * center_abs
        local_x = x - leg_center_x
        outer = side * local_x >= 0.0

        # Moderate outer flare and a smaller inner expansion preserve a closed
        # crotch while reading as wide trousers rather than bells or gaiters.
        if outer:
            width_scale = 1.18 + 0.82 * down
            outward_offset = 0.006 + 0.026 * down
            vertex.co.x = leg_center_x + local_x * width_scale + side * outward_offset
        else:
            width_scale = 1.045 + 0.20 * down
            vertex.co.x = leg_center_x + local_x * width_scale

        # Keep profile depth controlled.  At the hem no additive depth is used,
        # so the garment cannot grow back over the instep after source filtering.
        depth_scale = 1.12 + 0.28 * down
        depth_offset = 0.006 * (1.0 - down)
        y_sign = -1.0 if y < 0.0 else 1.0
        vertex.co.y = y * depth_scale + y_sign * depth_offset

        # Raise only the lowest ring slightly, preserving visible shoe clearance.
        if z < 0.175:
            vertex.co.z += 0.006 * (1.0 - clamp((z - hem_z) / 0.020, 0.0, 1.0))

    obj.data.update(calc_edges=True)


def assign_material_regions(
    pants: bpy.types.Object,
    fabric: bpy.types.Material,
    strap: bpy.types.Material,
) -> None:
    """Add attached waistband and knee-panel contrast without floating meshes."""
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
        0.0100,
    )
    apply_wide_cargo_profile(pants)
    build.clean_topology(pants)
    assign_material_regions(pants, fabric, strap)
    build.c.add_nearest_shape_keys(pants, body)
    return pants


def create_outfit_as_single_shell(body, armature, fabric, strap, metal):
    generated = _original_create_outfit(body, armature, fabric, strap, metal)
    for obj in generated:
        remove_object(obj)
    return [create_single_shell_pants(body, armature, fabric, strap)]


def degenerate_triangles(obj: bpy.types.Object) -> int:
    mesh = obj.data
    mesh.calc_loop_triangles()
    count = 0
    for triangle in mesh.loop_triangles:
        a, b, c = (mesh.vertices[index].co for index in triangle.vertices)
        if (b - a).cross(c - a).length_squared <= 1e-20:
            count += 1
    return count


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
    inner_lower_vertices = [vertex for vertex in lower_vertices if abs(vertex.co.x) <= 0.040]
    foot_like_vertices = [
        vertex for vertex in pants.data.vertices
        if vertex.co.z < 0.205 and abs(vertex.co.y) > 0.082
    ]
    degenerates = degenerate_triangles(pants)
    uv_layer_count = len(pants.data.uv_layers)
    material_slots = len(pants.data.materials)

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
        "footLikeVertices": len(foot_like_vertices),
        "degenerateTriangles": degenerates,
        "uvLayers": uv_layer_count,
        "materialSlots": material_slots,
    }
    checks["metrics"] = metrics

    topology_pass = degenerates == 0
    height_pass = 0.145 <= metrics["minimumZ"] <= 0.190 and metrics["maximumZ"] >= 0.79
    width_pass = 0.34 <= metrics["totalWidth"] <= 0.46
    depth_pass = 0.20 <= metrics["totalDepth"] <= 0.28
    inner_coverage_pass = len(inner_lower_vertices) >= 40
    foot_exclusion_pass = len(foot_like_vertices) == 0
    uv_pass = uv_layer_count > 0
    material_pass = material_slots >= 2

    checks.update({
        "topologyPassed": topology_pass,
        "heightPassed": height_pass,
        "controlledWideSilhouettePassed": width_pass and depth_pass,
        "innerLegCoveragePassed": inner_coverage_pass,
        "footExclusionPassed": foot_exclusion_pass,
        "uvPassed": uv_pass,
        "materialSeparationPassed": material_pass,
    })
    passed = (
        garment_meshes == [expected_name]
        and topology_pass and height_pass and width_pass and depth_pass
        and inner_coverage_pass and foot_exclusion_pass and uv_pass and material_pass
    )
    return {"schemaVersion": 1, "passed": passed, "checks": checks}


def record_wearability(report: dict[str, object]) -> None:
    _, job = build.c.load_job()
    manifest_path = build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    manifest["wearabilityAudit"] = report
    manifest["designRevision"] = "v19-controlled-foot-free-single-shell"
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
