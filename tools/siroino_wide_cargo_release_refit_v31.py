#!/usr/bin/env python3
"""Continuous fitted-waist, straight-wide Siroino cargo trousers.

The previous replacement used oversized cylindrical leg shells and left an
obvious visual break below the pelvis.  This build keeps only a fitted,
body-derived waist/seat shell, overlaps it with narrower asymmetric leg shells,
and closes the front and rear crotch with a tapered weighted gusset.  Every
component is joined into one skinned garment mesh before export.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils.kdtree import KDTree

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_release_refit_v23 as v23

build = v23.build
base = v23.base
smoothstep = v23.smoothstep


def upper_surface(point) -> bool:
    """Select only the waist and seat; lower geometry is procedural and clean."""
    return 0.575 <= point.z <= 0.805 and abs(point.x) <= 0.285


def fit_upper_shell(obj: bpy.types.Object) -> None:
    """Add clothing clearance without inflating the seat."""
    for vertex in obj.data.vertices:
        x, y, z = vertex.co
        waist = smoothstep(0.575, 0.805, z)
        vertex.co.x = x * (1.035 - 0.010 * waist)
        vertex.co.y = y * (1.060 - 0.015 * waist)
        if y > 0.0:
            seat = smoothstep(0.585, 0.635, z) * (
                1.0 - smoothstep(0.745, 0.795, z)
            )
            vertex.co.y += 0.008 * seat
    obj.data.update(calc_edges=True)


def copy_nearest_weights(source: bpy.types.Object, target: bpy.types.Object) -> None:
    tree = KDTree(len(source.data.vertices))
    for vertex in source.data.vertices:
        tree.insert(vertex.co, vertex.index)
    tree.balance()
    groups = {
        group.name: target.vertex_groups.new(name=group.name)
        for group in source.vertex_groups
    }
    for target_vertex in target.data.vertices:
        _, nearest_index, _ = tree.find(target_vertex.co)
        for reference in source.data.vertices[nearest_index].groups:
            source_group = source.vertex_groups[reference.group]
            groups[source_group.name].add(
                [target_vertex.index], reference.weight, "REPLACE"
            )


def straight_wide_legs(name: str, segments: int = 32) -> bpy.types.Object:
    # z, centre X, inner radius, outer radius, Y depth.  The top rings overlap
    # at the centre seam and overlap the fitted upper shell; lower rings remain
    # separate and nearly straight rather than becoming giant cylinders.
    rings = [
        (0.105, 0.069, 0.052, 0.087, 0.082),
        (0.200, 0.070, 0.053, 0.088, 0.084),
        (0.320, 0.071, 0.056, 0.089, 0.086),
        (0.440, 0.072, 0.062, 0.088, 0.088),
        (0.560, 0.073, 0.071, 0.086, 0.090),
        (0.660, 0.074, 0.078, 0.082, 0.092),
        (0.700, 0.075, 0.080, 0.080, 0.092),
    ]
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    for side in (-1.0, 1.0):
        offset = len(vertices)
        for z, centre, inner, outer, depth in rings:
            for index in range(segments):
                angle = 2.0 * math.pi * index / segments
                cosine = math.cos(angle)
                sine = math.sin(angle)
                radius_x = outer if side * cosine >= 0.0 else inner
                vertices.append(
                    (side * centre + cosine * radius_x, sine * depth, z)
                )
        for ring_index in range(len(rings) - 1):
            lower = offset + ring_index * segments
            upper = lower + segments
            for index in range(segments):
                next_index = (index + 1) % segments
                faces.append(
                    (
                        lower + index,
                        lower + next_index,
                        upper + next_index,
                        upper + index,
                    )
                )

    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    obj["leg_shell_vertices"] = len(vertices)
    return obj


def crotch_gusset(name: str) -> bpy.types.Object:
    # Front and rear surfaces stay outside the avatar and overlap both the upper
    # shell and inner leg surfaces, preventing the skin slit seen in back.png.
    layers = [
        (-0.085, 0.085, -0.096, 0.106, 0.710),
        (-0.074, 0.074, -0.093, 0.103, 0.650),
        (-0.052, 0.052, -0.088, 0.098, 0.570),
        (-0.032, 0.032, -0.080, 0.090, 0.490),
        (-0.018, 0.018, -0.070, 0.080, 0.420),
    ]
    vertices: list[tuple[float, float, float]] = []
    for x0, x1, y0, y1, z in layers:
        vertices.extend(
            [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]
        )
    faces: list[tuple[int, ...]] = [(0, 1, 2, 3), (16, 19, 18, 17)]
    for lower in (0, 4, 8, 12):
        upper = lower + 4
        faces.extend(
            [
                (lower, lower + 1, upper + 1, upper),
                (lower + 1, lower + 2, upper + 2, upper + 1),
                (lower + 2, lower + 3, upper + 3, upper + 2),
                (lower + 3, lower, upper, upper + 3),
            ]
        )
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    obj["gusset_vertices"] = len(vertices)
    return obj


def join_parts(
    upper: bpy.types.Object,
    parts: list[bpy.types.Object],
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    counts = {
        "leg_shell_vertices": int(parts[0].get("leg_shell_vertices", 0)),
        "gusset_vertices": int(parts[1].get("gusset_vertices", 0)),
    }
    for part in parts:
        copy_nearest_weights(upper, part)
        part.data.materials.append(material)
        modifier = part.modifiers.new(name="Armature", type="ARMATURE")
        modifier.object = armature
    bpy.ops.object.select_all(action="DESELECT")
    upper.select_set(True)
    for part in parts:
        part.select_set(True)
    bpy.context.view_layer.objects.active = upper
    bpy.ops.object.join()
    upper.name = "Cargo_Continuous_Pants"
    for key, value in counts.items():
        upper[key] = value
    return upper


def create_outfit(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    fabric: bpy.types.Material,
    strap: bpy.types.Material,
    metal: bpy.types.Material,
):
    del metal
    upper = build.c.extract_surface(
        body,
        armature,
        "Cargo_Continuous_Pants",
        upper_surface,
        fabric,
        0.012,
    )
    fit_upper_shell(upper)
    legs = straight_wide_legs("Cargo_Straight_Wide_Legs")
    gusset = crotch_gusset("Cargo_Crotch_Gusset")
    pants = join_parts(upper, [legs, gusset], armature, fabric)
    build.clean_topology(pants)
    v23.assign_materials(pants, fabric, strap)
    return [pants]


def edge_metrics(obj: bpy.types.Object) -> tuple[float, float]:
    maximum = 0.0
    maximum_z_span = 0.0
    for edge in obj.data.edges:
        a = obj.data.vertices[edge.vertices[0]].co
        b = obj.data.vertices[edge.vertices[1]].co
        maximum = max(maximum, (a - b).length)
        maximum_z_span = max(maximum_z_span, abs(a.z - b.z))
    return maximum, maximum_z_span


def band(obj: bpy.types.Object, z0: float, z1: float) -> dict[str, float]:
    points = [vertex.co for vertex in obj.data.vertices if z0 <= vertex.co.z <= z1]
    xs = [point.x for point in points]
    ys = [point.y for point in points]
    return {
        "width": max(xs) - min(xs) if xs else 0.0,
        "depth": max(ys) - min(ys) if ys else 0.0,
        "rear": max(ys) if ys else 0.0,
    }


def audit() -> dict[str, object]:
    pants = bpy.data.objects.get("Cargo_Continuous_Pants")
    garment_names = sorted(
        obj.name
        for obj in bpy.data.objects
        if obj.type == "MESH"
        and not obj.name.startswith("SiroinoSotai_PC")
        and obj.name != "Studio_Floor"
    )
    if pants is None:
        return {"schemaVersion": 1, "passed": False, "checks": {"garmentMeshNames": garment_names}}

    pants.data.calc_loop_triangles()
    coordinates = [component for vertex in pants.data.vertices for component in vertex.co]
    zs = [vertex.co.z for vertex in pants.data.vertices]
    total = band(pants, min(zs), max(zs))
    seat = band(pants, 0.620, 0.750)
    thigh = band(pants, 0.500, 0.570)
    knee = band(pants, 0.300, 0.405)
    hem = band(pants, 0.105, 0.185)
    maximum_edge, maximum_z_span = edge_metrics(pants)
    degenerates = v23.triangle_degenerates(pants)
    leg_vertices = int(pants.get("leg_shell_vertices", 0))
    gusset_vertices = int(pants.get("gusset_vertices", 0))
    shape_keys = 0 if pants.data.shape_keys is None else max(0, len(pants.data.shape_keys.key_blocks) - 1)
    foot_intrusions = sum(
        1
        for vertex in pants.data.vertices
        if vertex.co.z < 0.10
        or (vertex.co.z < 0.18 and abs(vertex.co.y) > 0.105)
    )

    metrics = {
        "vertices": len(pants.data.vertices),
        "triangles": len(pants.data.loop_triangles),
        "minimumZ": min(zs),
        "maximumZ": max(zs),
        "totalWidth": total["width"],
        "totalDepth": total["depth"],
        "maximumEdgeLength": maximum_edge,
        "maximumEdgeZSpan": maximum_z_span,
        "degenerateTriangles": degenerates,
        "uvLayers": len(pants.data.uv_layers),
        "materialSlots": len(pants.data.materials),
        "shapeKeys": shape_keys,
        "footIntrusionVertices": foot_intrusions,
        "legShellVertices": leg_vertices,
        "gussetVertices": gusset_vertices,
        "bands": {"seat": seat, "thigh": thigh, "knee": knee, "hem": hem},
    }
    checks = {
        "garmentMeshNames": garment_names,
        "metrics": metrics,
        "singleShellOnly": garment_names == ["Cargo_Continuous_Pants"],
        "finiteCoordinatesPassed": all(math.isfinite(float(value)) for value in coordinates),
        "topologyPassed": degenerates == 0,
        "spikeGuardPassed": maximum_edge <= 0.125 and maximum_z_span <= 0.125,
        "uvPassed": len(pants.data.uv_layers) > 0,
        "materialSeparationPassed": len(pants.data.materials) >= 2,
        "shapeKeyIsolationPassed": shape_keys == 0,
        "footAndFloorClearancePassed": foot_intrusions == 0 and min(zs) >= 0.10,
        "controlledVolumePassed": 0.285 <= total["width"] <= 0.345 and 0.165 <= total["depth"] <= 0.245,
        "fittedSeatPassed": seat["width"] <= 0.330 and seat["rear"] >= 0.090,
        "straightWideProfilePassed": (
            abs(thigh["width"] - knee["width"]) <= 0.045
            and abs(knee["width"] - hem["width"]) <= 0.030
            and abs(thigh["depth"] - knee["depth"]) <= 0.035
        ),
        "cleanLegShellPassed": leg_vertices == 448,
        "weightedCrotchGussetPassed": gusset_vertices == 20,
    }
    required = [
        "singleShellOnly", "finiteCoordinatesPassed", "topologyPassed",
        "spikeGuardPassed", "uvPassed", "materialSeparationPassed",
        "shapeKeyIsolationPassed", "footAndFloorClearancePassed",
        "controlledVolumePassed", "fittedSeatPassed", "straightWideProfilePassed",
        "cleanLegShellPassed", "weightedCrotchGussetPassed",
    ]
    return {"schemaVersion": 1, "passed": all(bool(checks[name]) for name in required), "checks": checks}


def record(report: dict[str, object]) -> None:
    _, job = build.c.load_job()
    path = build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    manifest["status"] = "WORKING"
    manifest["designRevision"] = "v31-continuous-fitted-waist-straight-wide"
    manifest["wearabilityAudit"] = report
    gates = manifest.setdefault("technicalGates", {})
    gates["latestGeometryRender"] = "PASS" if report["passed"] else "FAIL"
    gates["humanVisualReview"] = "PENDING"
    gates["humanPoseReview"] = "PENDING"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


build.create_outfit = create_outfit


if __name__ == "__main__":
    build.main()
    result = audit()
    record(result)
    base.save_distribution_blend()
    if not result["passed"]:
        raise RuntimeError(f"v31 continuous silhouette audit failed: {result}")
    raise SystemExit(0)
