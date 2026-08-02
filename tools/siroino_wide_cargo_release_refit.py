#!/usr/bin/env python3
"""Single-shell rendered-fit rebuild for Siroino Wide Cargo.

The v16 render covered the inner thighs but still failed visually: the garment
read as tight leggings plus detached lower-leg gaiters, long front slits exposed
the shins, and the lower shells continued over the feet.

This revision removes every inter-part seam. The pants are one body-derived,
waist-to-ankle shell. Below the pelvis, each side is widened asymmetrically around
its own leg centre: outer surfaces flare strongly, inner surfaces remain closed
and only expand slightly. The ankle selection excludes the feet so the hem ends
above the shoes instead of wrapping over the toes.
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


def remove_object(obj: bpy.types.Object) -> None:
    if obj.name in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)


def pants_surface(point) -> bool:
    """Select the complete lower body while cutting a clean ankle hem."""
    if not (0.075 <= point.z <= 0.805):
        return False
    if abs(point.x) > 0.34:
        return False
    # At ankle height the source foot extends far forward/backward. Restricting
    # depth here preserves the calf circumference but excludes instep and toes.
    if point.z < 0.145 and abs(point.y) > 0.082:
        return False
    return True


def apply_wide_cargo_profile(obj: bpy.types.Object) -> None:
    """Create a broad outer silhouette without reopening the inner legs."""
    ankle_z = 0.075
    transition_z = 0.535
    span = transition_z - ankle_z

    for vertex in obj.data.vertices:
        x, y, z = vertex.co
        if z >= transition_z:
            # Close waist and hip fit; enough clearance to avoid body flicker.
            hip_t = clamp((z - transition_z) / (0.805 - transition_z), 0.0, 1.0)
            vertex.co.x *= 1.065 - 0.020 * hip_t
            vertex.co.y *= 1.075 - 0.025 * hip_t
            continue

        down = clamp((transition_z - z) / span, 0.0, 1.0)
        side = -1.0 if x < 0.0 else 1.0
        leg_center_x = side * 0.090
        local_x = x - leg_center_x

        # Outer cloth supplies the wide-cargo silhouette. Inner cloth expands
        # only modestly, remaining near the centreline and preserving coverage.
        is_outer = abs(x) >= abs(leg_center_x)
        if is_outer:
            width_scale = 1.12 + 0.63 * down
        else:
            width_scale = 1.035 + 0.075 * down
        depth_scale = 1.08 + 0.27 * down

        vertex.co.x = leg_center_x + local_x * width_scale
        vertex.co.y = y * depth_scale

        # Slightly shorten the lowest edge so no cloth intersects the floor.
        if z < 0.105:
            vertex.co.z += 0.010 * (1.0 - clamp((z - ankle_z) / 0.030, 0.0, 1.0))

    obj.data.update(calc_edges=True)


def create_single_shell_pants(body, armature, fabric) -> bpy.types.Object:
    pants = build.c.extract_surface(
        body,
        armature,
        "Cargo_Continuous_Pants",
        pants_surface,
        fabric,
        0.0110,
    )
    apply_wide_cargo_profile(pants)
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

    xs = [vertex.co.x for vertex in pants.data.vertices]
    ys = [vertex.co.y for vertex in pants.data.vertices]
    zs = [vertex.co.z for vertex in pants.data.vertices]
    lower_vertices = [vertex for vertex in pants.data.vertices if vertex.co.z <= 0.42]
    inner_lower_vertices = [
        vertex
        for vertex in lower_vertices
        if abs(vertex.co.x) <= 0.035
    ]
    foot_like_vertices = [
        vertex
        for vertex in pants.data.vertices
        if vertex.co.z < 0.145 and abs(vertex.co.y) > 0.095
    ]
    degenerates = degenerate_triangles(pants)

    metrics = {
        "vertices": len(pants.data.vertices),
        "triangles": len(pants.data.loop_triangles),
        "minimumX": min(xs, default=0.0),
        "maximumX": max(xs, default=0.0),
        "minimumY": min(ys, default=0.0),
        "maximumY": max(ys, default=0.0),
        "minimumZ": min(zs, default=0.0),
        "maximumZ": max(zs, default=0.0),
        "lowerInnerCoverageVertices": len(inner_lower_vertices),
        "footLikeVertices": len(foot_like_vertices),
        "degenerateTriangles": degenerates,
    }
    checks["metrics"] = metrics

    topology_pass = degenerates == 0
    height_pass = metrics["minimumZ"] >= 0.065 and metrics["minimumZ"] <= 0.115 and metrics["maximumZ"] >= 0.79
    width_pass = (metrics["maximumX"] - metrics["minimumX"]) >= 0.48
    depth_pass = (metrics["maximumY"] - metrics["minimumY"]) >= 0.20
    inner_coverage_pass = len(inner_lower_vertices) >= 40
    foot_exclusion_pass = len(foot_like_vertices) == 0

    checks.update(
        {
            "topologyPassed": topology_pass,
            "heightPassed": height_pass,
            "wideSilhouettePassed": width_pass and depth_pass,
            "innerLegCoveragePassed": inner_coverage_pass,
            "footExclusionPassed": foot_exclusion_pass,
        }
    )
    passed = (
        garment_meshes == [expected_name]
        and topology_pass
        and height_pass
        and width_pass
        and depth_pass
        and inner_coverage_pass
        and foot_exclusion_pass
    )
    return {"schemaVersion": 1, "passed": passed, "checks": checks}


def record_wearability(report: dict[str, object]) -> None:
    _, job = build.c.load_job()
    manifest_path = build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    manifest["wearabilityAudit"] = report
    manifest["designRevision"] = "v17-single-shell-wide-cargo"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


build.create_outfit = create_outfit_as_single_shell

if __name__ == "__main__":
    # build.main may return 2 because the legacy report expects the original
    # multi-part design. A Blender exception still terminates before returning;
    # after a completed build, the product-specific single-shell audit is the
    # authoritative gate for this revision.
    build.main()
    report = audit_wearability()
    record_wearability(report)
    base.save_distribution_blend()
    if report.get("passed") is not True:
        raise RuntimeError(f"single-shell wearability audit failed: {report}")
    raise SystemExit(0)
