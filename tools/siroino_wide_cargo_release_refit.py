#!/usr/bin/env python3
"""Rendered-fit rebuild for Siroino Wide Cargo.

The previous render proved that a continuous upper shell alone was insufficient:
the lower legs remained detached tubes, bare skin was visible from knee to ankle,
and the waistband and pockets floated away from the avatar.

This revision reduces the outfit to three body-derived cloth shells:

* one continuous waist-to-mid-calf under-shell,
* one overlapping wide left leg,
* one overlapping wide right leg.

Every decorative object is removed until this basic pants silhouette passes
actual front/back/side and pose renders. The wide legs overlap the under-shell
well above the knee, so no bare inner thigh or calf can appear at the seam.
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


def scale_shell_about_center(
    obj: bpy.types.Object,
    *,
    minimum_z: float,
    maximum_z: float,
    top_width: float,
    bottom_width: float,
    top_depth: float,
    bottom_depth: float,
) -> None:
    coordinates = [vertex.co.copy() for vertex in obj.data.vertices]
    center_x = sum(co.x for co in coordinates) / max(1, len(coordinates))
    center_y = sum(co.y for co in coordinates) / max(1, len(coordinates))
    span = max(maximum_z - minimum_z, 1e-6)
    for vertex in obj.data.vertices:
        down = 1.0 - clamp((vertex.co.z - minimum_z) / span, 0.0, 1.0)
        width_scale = top_width + (bottom_width - top_width) * down
        depth_scale = top_depth + (bottom_depth - top_depth) * down
        vertex.co.x = center_x + (vertex.co.x - center_x) * width_scale
        vertex.co.y = center_y + (vertex.co.y - center_y) * depth_scale
    obj.data.update(calc_edges=True)


def create_body_derived_pants(body, armature, fabric) -> list[bpy.types.Object]:
    # This under-shell extends below the wide-leg overlap. It is intentionally
    # continuous across pelvis and inner thighs and guarantees that no body skin
    # is visible if the outer leg shells separate during a pose.
    upper = build.c.extract_surface(
        body,
        armature,
        "Cargo_Continuous_Upper",
        lambda point: 0.245 <= point.z <= 0.805,
        fabric,
        0.0080,
    )
    for vertex in upper.data.vertices:
        t = clamp((vertex.co.z - 0.245) / 0.560, 0.0, 1.0)
        vertex.co.x *= 1.055 - 0.025 * t
        vertex.co.y *= 1.070 - 0.030 * t
    upper.data.update(calc_edges=True)
    build.c.add_nearest_shape_keys(upper, body)

    legs: list[bpy.types.Object] = []
    for side_name, side in (("L", -1), ("R", 1)):
        lower = build.c.extract_surface(
            body,
            armature,
            f"Cargo_WideLeg_{side_name}",
            lambda point, side=side: (
                0.020 <= point.z <= 0.485
                and (point.x <= 0.0 if side < 0 else point.x >= 0.0)
            ),
            fabric,
            0.0120,
        )
        scale_shell_about_center(
            lower,
            minimum_z=0.020,
            maximum_z=0.485,
            top_width=1.12,
            bottom_width=1.72,
            top_depth=1.10,
            bottom_depth=1.38,
        )
        build.c.add_nearest_shape_keys(lower, body)
        legs.append(lower)

    return [upper, *legs]


def create_outfit_as_actual_pants(body, armature, fabric, strap, metal):
    generated = _original_create_outfit(body, armature, fabric, strap, metal)
    for obj in generated:
        remove_object(obj)
    return create_body_derived_pants(body, armature, fabric)


def degenerate_triangles(obj: bpy.types.Object) -> int:
    mesh = obj.data
    mesh.calc_loop_triangles()
    count = 0
    for triangle in mesh.loop_triangles:
        a, b, c = (mesh.vertices[index].co for index in triangle.vertices)
        if (b - a).cross(c - a).length_squared <= 1e-20:
            count += 1
    return count


def bounds(obj: bpy.types.Object) -> dict[str, float]:
    xs = [vertex.co.x for vertex in obj.data.vertices]
    ys = [vertex.co.y for vertex in obj.data.vertices]
    zs = [vertex.co.z for vertex in obj.data.vertices]
    return {
        "minimumX": min(xs, default=0.0),
        "maximumX": max(xs, default=0.0),
        "minimumY": min(ys, default=0.0),
        "maximumY": max(ys, default=0.0),
        "minimumZ": min(zs, default=0.0),
        "maximumZ": max(zs, default=0.0),
    }


def audit_wearability() -> dict[str, object]:
    required = (
        "Cargo_Continuous_Upper",
        "Cargo_WideLeg_L",
        "Cargo_WideLeg_R",
    )
    missing = [name for name in required if name not in bpy.data.objects]
    checks: dict[str, object] = {
        "requiredObjectsPresent": not missing,
        "missing": missing,
    }

    object_metrics: dict[str, dict[str, float | int]] = {}
    topology_pass = True
    for name in required:
        obj = bpy.data.objects.get(name)
        if obj is None:
            topology_pass = False
            continue
        item = bounds(obj)
        item["vertices"] = len(obj.data.vertices)
        item["degenerateTriangles"] = degenerate_triangles(obj)
        object_metrics[name] = item
        topology_pass = topology_pass and item["degenerateTriangles"] == 0
    checks["objects"] = object_metrics
    checks["topologyPassed"] = topology_pass

    upper = object_metrics.get("Cargo_Continuous_Upper", {})
    upper_pass = (
        upper.get("minimumZ", 1.0) <= 0.27
        and upper.get("maximumZ", 0.0) >= 0.79
        and upper.get("vertices", 0) >= 3000
    )
    checks["continuousInnerCoveragePassed"] = upper_pass

    leg_pass = True
    for name, side in (("Cargo_WideLeg_L", -1), ("Cargo_WideLeg_R", 1)):
        item = object_metrics.get(name, {})
        width = item.get("maximumX", 0.0) - item.get("minimumX", 0.0)
        depth = item.get("maximumY", 0.0) - item.get("minimumY", 0.0)
        reaches_center = (
            item.get("maximumX", -1.0) >= -0.018
            if side < 0
            else item.get("minimumX", 1.0) <= 0.018
        )
        item["width"] = width
        item["depth"] = depth
        item["reachesCenterline"] = int(reaches_center)
        leg_pass = leg_pass and (
            item.get("minimumZ", 1.0) <= 0.04
            and item.get("maximumZ", 0.0) >= 0.46
            and width >= 0.16
            and depth >= 0.14
            and reaches_center
        )
    checks["wideLegCoveragePassed"] = leg_pass

    garment_mesh_names = sorted(
        obj.name
        for obj in bpy.data.objects
        if obj.type == "MESH"
        and not obj.name.startswith("SiroinoSotai_PC")
        and obj.name != "Studio_Floor"
    )
    only_expected = garment_mesh_names == sorted(required)
    checks["garmentMeshNames"] = garment_mesh_names
    checks["noFloatingDecorationPassed"] = only_expected

    passed = not missing and topology_pass and upper_pass and leg_pass and only_expected
    return {"schemaVersion": 1, "passed": passed, "checks": checks}


def record_wearability(report: dict[str, object]) -> None:
    _, job = build.c.load_job()
    manifest_path = build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    manifest["wearabilityAudit"] = report
    manifest["designRevision"] = "v16-overlapping-wide-legs"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


build.create_outfit = create_outfit_as_actual_pants

if __name__ == "__main__":
    exit_code = build.main()
    if exit_code == 0:
        report = audit_wearability()
        record_wearability(report)
        if report.get("passed") is not True:
            raise RuntimeError(f"geometric wearability audit failed: {report}")
        base.save_distribution_blend()
    raise SystemExit(exit_code)
