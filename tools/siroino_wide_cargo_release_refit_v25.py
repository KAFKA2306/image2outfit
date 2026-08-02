#!/usr/bin/env python3
"""Visually restrained rear-safe Siroino Wide Cargo v25.

v24 closed the rear inner-thigh exposure but carried its procedural leg section
too high into the pelvis, producing an inflated seat and deleting the intended
straight-wide proportion.  v25 keeps one continuous shell, returns the waist and
seat to an avatar-following fit, reserves the wide section for the legs, retains
rear/crotch clearance, softens the excessive normal-map relief, and audits rear
coverage independently from silhouette volume.
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

import siroino_wide_cargo_release_refit_v24 as v24

build = v24.build
base = v24.base
clamp = v24.clamp
lerp = v24.lerp
smoothstep = v24.smoothstep


def pants_surface(point) -> bool:
    if not (0.105 <= point.z <= 0.805):
        return False
    if abs(point.x) > 0.335:
        return False
    if point.z < 0.185 and abs(point.y) > 0.062:
        return False
    return True


def target_cross_section(x: float, y: float, z: float) -> tuple[float, float]:
    """Straight-wide, shallow-depth section used only below the upper thigh."""
    side = -1.0 if x < 0.0 else 1.0
    down = 1.0 - smoothstep(0.105, 0.560, z)
    centre_x = side * lerp(0.080, 0.069, down)
    outer_radius = lerp(0.098, 0.111, down)
    inner_radius = lerp(0.058, 0.055, down)
    front_depth = lerp(0.086, 0.096, down)
    rear_depth = lerp(0.096, 0.101, down)

    local_x = x - centre_x
    angle = math.atan2(y, local_x)
    c = math.cos(angle)
    s = math.sin(angle)
    outer_weight = clamp((side * c + 1.0) * 0.5, 0.0, 1.0)
    radius_x = lerp(inner_radius, outer_radius, outer_weight)
    radius_y = rear_depth if s >= 0.0 else front_depth
    return centre_x + c * radius_x, s * radius_y


def apply_profile(obj: bpy.types.Object) -> None:
    for vertex in obj.data.vertices:
        x, y, z = vertex.co
        target_x, target_y = target_cross_section(x, y, z)

        # The controlled leg section ends below the seat.  Above it, follow the
        # avatar with a modest clothing allowance instead of ballooning outward.
        section_mix = 1.0 - smoothstep(0.540, 0.675, z)
        waist_t = smoothstep(0.600, 0.805, z)
        fitted_x = x * lerp(1.070, 1.045, waist_t)
        fitted_y_scale = lerp(1.075, 1.050, waist_t)
        if y > 0.0:
            fitted_y_scale += lerp(0.025, 0.015, waist_t)
        fitted_y = y * fitted_y_scale

        # Keep the crotch bridge body-derived.  Applying an ellipse to centre
        # vertices caused the inflated/pinched centre seam seen in v24.
        centre_mix = smoothstep(0.012, 0.044, abs(x))
        x_mix = section_mix * centre_mix
        y_mix = section_mix * centre_mix
        new_x = lerp(fitted_x, target_x, x_mix)
        new_y = lerp(fitted_y, target_y, y_mix)

        # Local rear allowance closes the back/inner-thigh exposure while the
        # side profile remains shallow.  Positive Y is rear in this asset.
        rear_zone = smoothstep(0.475, 0.555, z) * (1.0 - smoothstep(0.700, 0.790, z))
        centre_zone = 1.0 - smoothstep(0.018, 0.145, abs(x))
        if y > 0.0:
            new_y += 0.0065 * rear_zone * (0.62 + 0.38 * centre_zone)

        # Close the visual inner-thigh slit without merging the legs below the
        # anatomical crotch transition.
        inner_zone = (
            (1.0 - smoothstep(0.025, 0.085, abs(x)))
            * smoothstep(0.430, 0.490, z)
            * (1.0 - smoothstep(0.585, 0.655, z))
        )
        new_x *= 1.0 - 0.055 * inner_zone

        vertex.co.x = clamp(new_x, -0.205, 0.205)
        vertex.co.y = clamp(new_y, -0.125, 0.130)
        vertex.co.z = clamp(z, 0.105, 0.812)

    obj.data.update(calc_edges=True)


def soften_normal_relief(material: bpy.types.Material, strength: float) -> None:
    if not material.use_nodes or material.node_tree is None:
        return
    for node in material.node_tree.nodes:
        if node.bl_idname == "ShaderNodeNormalMap" and "Strength" in node.inputs:
            node.inputs["Strength"].default_value = strength
        elif node.bl_idname == "ShaderNodeBump" and "Strength" in node.inputs:
            node.inputs["Strength"].default_value = min(strength, 0.12)


def assign_materials(pants: bpy.types.Object, fabric, strap) -> None:
    base.tune_material(fabric, base=(0.022, 0.027, 0.039), roughness=0.80)
    base.tune_material(strap, base=(0.006, 0.008, 0.013), roughness=0.43)
    soften_normal_relief(fabric, 0.16)
    soften_normal_relief(strap, 0.10)

    pants.data.materials.clear()
    pants.data.materials.append(fabric)
    pants.data.materials.append(strap)
    for polygon in pants.data.polygons:
        centre = sum((pants.data.vertices[i].co for i in polygon.vertices), start=polygon.center.copy() * 0.0) / len(polygon.vertices)
        waistband = centre.z >= 0.755
        knee_panel = 0.392 <= centre.z <= 0.422
        cargo_side_panel = 0.500 <= centre.z <= 0.615 and abs(centre.x) >= 0.125
        polygon.material_index = 1 if waistband or knee_panel or cargo_side_panel else 0
        polygon.use_smooth = True
    pants.data.update()


def create_outfit_v25(body, armature, fabric, strap, metal):
    del metal
    pants = build.c.extract_surface(
        body,
        armature,
        "Cargo_Continuous_Pants",
        pants_surface,
        fabric,
        0.0120,
    )
    # Clean first, then profile exactly once.  v24 profiled twice, changing the
    # source angle on the second pass and exaggerating the hip section.
    build.clean_topology(pants)
    apply_profile(pants)
    assign_materials(pants, fabric, strap)
    return [pants]


def edge_metrics(obj: bpy.types.Object) -> dict[str, object]:
    usage: dict[tuple[int, int], int] = {}
    for polygon in obj.data.polygons:
        vertices = list(polygon.vertices)
        for index, a in enumerate(vertices):
            b = vertices[(index + 1) % len(vertices)]
            key = (min(a, b), max(a, b))
            usage[key] = usage.get(key, 0) + 1

    maximum = 0.0
    maximum_interior = 0.0
    detail: dict[str, object] = {}
    for edge in obj.data.edges:
        a_index, b_index = edge.vertices
        a = obj.data.vertices[a_index].co
        b = obj.data.vertices[b_index].co
        length = (a - b).length
        boundary = usage.get((min(a_index, b_index), max(a_index, b_index)), 0) <= 1
        if length > maximum:
            maximum = length
            detail = {
                "length": length,
                "boundary": boundary,
                "a": [float(a.x), float(a.y), float(a.z)],
                "b": [float(b.x), float(b.y), float(b.z)],
            }
        if not boundary:
            maximum_interior = max(maximum_interior, length)
    return {
        "maximumEdgeLength": maximum,
        "maximumInteriorEdgeLength": maximum_interior,
        "longestEdge": detail,
    }


def extent(obj: bpy.types.Object, z0: float, z1: float) -> dict[str, float | int]:
    points = [vertex.co for vertex in obj.data.vertices if z0 <= vertex.co.z <= z1]
    if not points:
        return {"vertices": 0, "width": 0.0, "depth": 0.0, "rear": 0.0, "front": 0.0}
    xs = [point.x for point in points]
    ys = [point.y for point in points]
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
    coordinates = [component for vertex in pants.data.vertices for component in vertex.co]
    xs = [vertex.co.x for vertex in pants.data.vertices]
    ys = [vertex.co.y for vertex in pants.data.vertices]
    zs = [vertex.co.z for vertex in pants.data.vertices]
    bands = {
        "seat": extent(pants, 0.625, 0.755),
        "upperThigh": extent(pants, 0.475, 0.590),
        "knee": extent(pants, 0.300, 0.405),
        "hem": extent(pants, 0.105, 0.185),
    }
    inner_thigh = [
        vertex.co for vertex in pants.data.vertices
        if 0.440 <= vertex.co.z <= 0.610 and abs(vertex.co.x) <= 0.045
    ]
    rear_bridge = [
        point for point in inner_thigh
        if point.y >= 0.018 and 0.470 <= point.z <= 0.610
    ]
    degenerates = v24.triangle_degenerates(pants)
    edges = edge_metrics(pants)
    total_width = max(xs, default=0.0) - min(xs, default=0.0)
    total_depth = max(ys, default=0.0) - min(ys, default=0.0)
    shape_keys = 0 if pants.data.shape_keys is None else max(0, len(pants.data.shape_keys.key_blocks) - 1)
    foot_intrusions = sum(
        1 for vertex in pants.data.vertices
        if vertex.co.z < 0.10 or (vertex.co.z < 0.18 and abs(vertex.co.y) > 0.115)
    )
    finite = all(math.isfinite(float(value)) for value in coordinates)

    metrics = {
        "vertices": len(pants.data.vertices),
        "triangles": len(pants.data.loop_triangles),
        "minimumZ": min(zs, default=0.0),
        "maximumZ": max(zs, default=0.0),
        "totalWidth": total_width,
        "totalDepth": total_depth,
        **edges,
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
        # Interior edges are the spike signal.  A long, nearly horizontal open
        # waist boundary is recorded but is not itself a spike.
        "spikeGuardPassed": float(edges["maximumInteriorEdgeLength"]) <= 0.075,
        "topologyPassed": degenerates == 0,
        "uvPassed": len(pants.data.uv_layers) > 0,
        "materialSeparationPassed": len(pants.data.materials) >= 2,
        "shapeKeyIsolationPassed": shape_keys == 0,
        "footAndFloorClearancePassed": foot_intrusions == 0 and min(zs, default=0.0) >= 0.10,
        "controlledVolumePassed": 0.335 <= total_width <= 0.385 and 0.185 <= total_depth <= 0.245,
        "restrainedSeatPassed": (
            float(bands["seat"]["width"]) <= 0.365
            and float(bands["seat"]["depth"]) <= 0.225
            and float(bands["seat"]["rear"]) >= 0.096
        ),
        "rearSeatClearancePassed": float(bands["seat"]["rear"]) >= 0.096,
        "innerThighCoveragePassed": len(inner_thigh) >= 24,
        "rearCrotchBridgePassed": len(rear_bridge) >= 8,
        "straightWideProfilePassed": (
            abs(float(bands["upperThigh"]["width"]) - float(bands["knee"]["width"])) <= 0.055
            and abs(float(bands["knee"]["width"]) - float(bands["hem"]["width"])) <= 0.050
            and abs(float(bands["upperThigh"]["depth"]) - float(bands["knee"]["depth"])) <= 0.045
        ),
    })
    required = [
        "singleShellOnly", "finiteCoordinatesPassed", "spikeGuardPassed",
        "topologyPassed", "uvPassed", "materialSeparationPassed",
        "shapeKeyIsolationPassed", "footAndFloorClearancePassed",
        "controlledVolumePassed", "restrainedSeatPassed",
        "rearSeatClearancePassed", "innerThighCoveragePassed",
        "rearCrotchBridgePassed", "straightWideProfilePassed",
    ]
    return {"schemaVersion": 1, "passed": all(bool(checks[key]) for key in required), "checks": checks}


def record(report: dict[str, object]) -> None:
    _, job = build.c.load_job()
    path = build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    manifest["status"] = "WORKING"
    manifest["designRevision"] = "v25-restrained-seat-rear-safe"
    manifest["wearabilityAudit"] = report
    gates = manifest.setdefault("technicalGates", {})
    gates["latestGeometryRender"] = "PASS" if report.get("passed") is True else "FAIL"
    gates["humanVisualReview"] = "PENDING"
    gates["humanPoseReview"] = "PENDING"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


build.create_outfit = create_outfit_v25


if __name__ == "__main__":
    build.main()
    result = audit()
    record(result)
    base.save_distribution_blend()
    if result.get("passed") is not True:
        raise RuntimeError(f"v25 rear/silhouette audit failed: {result}")
    raise SystemExit(0)
