#!/usr/bin/env python3
"""Wide-volume single-shell rebuild for Siroino Wide Cargo.

The v17 render fixed exposed skin and disconnected seams, but the silhouette was
still body-hugging. Its fixed leg centre (|x|=0.09) incorrectly classified most
calf vertices as inner cloth, so the intended flare was barely applied.

This revision keeps one continuous waist-to-ankle shell and changes only the
volume model:

* the leg centre narrows from the upper thigh toward the ankle,
* outer cloth receives both radial scaling and an additive outward offset,
* front/back depth grows independently to create real fabric volume,
* the ankle cut starts higher and excludes source-foot polygons,
* topology is cleaned again after reshaping, before shape keys are authored.
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


def remove_object(obj: bpy.types.Object) -> None:
    if obj.name in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)


def pants_surface(point) -> bool:
    """Select lower-body cloth with a foot-free ankle opening."""
    if not (0.095 <= point.z <= 0.805):
        return False
    if abs(point.x) > 0.34:
        return False
    # At the lowest rings, accept only the compact ankle cross-section. Source
    # instep and toe polygons extend farther along Y and are excluded here.
    if point.z < 0.180 and abs(point.y) > 0.065:
        return False
    return True


def apply_wide_cargo_profile(obj: bpy.types.Object) -> None:
    """Expand outer cloth into a visibly wide, loose cargo silhouette."""
    ankle_z = 0.095
    transition_z = 0.570
    span = transition_z - ankle_z

    for vertex in obj.data.vertices:
        x, y, z = vertex.co
        if z >= transition_z:
            hip_t = clamp((z - transition_z) / (0.805 - transition_z), 0.0, 1.0)
            vertex.co.x *= 1.105 - 0.020 * hip_t
            vertex.co.y *= 1.145 - 0.025 * hip_t
            continue

        down = clamp((transition_z - z) / span, 0.0, 1.0)
        side = -1.0 if x < 0.0 else 1.0

        # Siroino's leg centres are wider at the upper thigh and substantially
        # narrower at the calf/ankle. A fixed 0.09 m centre caused v17 to miss
        # the actual outside calf. Interpolate 0.09 -> 0.055 m downward.
        center_abs = 0.090 - 0.035 * down
        leg_center_x = side * center_abs
        local_x = x - leg_center_x
        is_outer = abs(x) >= center_abs

        if is_outer:
            width_scale = 1.45 + 1.95 * down
            outward_offset = 0.018 + 0.065 * down
            vertex.co.x = (
                leg_center_x
                + local_x * width_scale
                + side * outward_offset
            )
        else:
            # Keep the inner surface continuous and near the centreline.
            width_scale = 1.05 + 0.12 * down
            vertex.co.x = leg_center_x + local_x * width_scale

        depth_scale = 1.30 + 0.65 * down
        depth_offset = 0.015 + 0.035 * down
        y_sign = -1.0 if y < 0.0 else 1.0
        vertex.co.y = y * depth_scale + y_sign * depth_offset

        if z < 0.125:
            vertex.co.z += 0.006 * (
                1.0 - clamp((z - ankle_z) / 0.030, 0.0, 1.0)
            )

    obj.data.update(calc_edges=True)


def create_single_shell_pants(body, armature, fabric) -> bpy.types.Object:
    pants = build.c.extract_surface(
        body,
        armature,
        "Cargo_Continuous_Pants",
        pants_surface,
        fabric,
        0.0130,
    )
    apply_wide_cargo_profile(pants)
    # Re-run topology cleanup after the nonlinear profile transform. This also
    # removes the four residual near-zero triangles observed in v17.
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
    foot_like_vertices = [
        vertex
        for vertex in pants.data.vertices
        if vertex.co.z < 0.180 and abs(vertex.co.y) > 0.090
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
        "totalWidth": max(xs, default=0.0) - min(xs, default=0.0),
        "totalDepth": max(ys, default=0.0) - min(ys, default=0.0),
        "lowerInnerCoverageVertices": len(inner_lower_vertices),
        "footLikeVertices": len(foot_like_vertices),
        "degenerateTriangles": degenerates,
    }
    checks["metrics"] = metrics

    topology_pass = degenerates == 0
    height_pass = (
        0.085 <= metrics["minimumZ"] <= 0.135
        and metrics["maximumZ"] >= 0.79
    )
    width_pass = metrics["totalWidth"] >= 0.38
    depth_pass = metrics["totalDepth"] >= 0.26
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
    manifest["designRevision"] = "v18-wide-volume-single-shell"
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
