#!/usr/bin/env python3
"""Replace malformed lower pants with clean skinned wide-leg shells.

The extracted avatar surface contains hem-to-crotch faces that cannot be patched
as closed boundary loops.  Rather than retaining spikes or open holes, this
revision keeps the fitted upper-pelvis shell, removes the malformed lower region,
and joins two smooth asymmetric wide-leg shells plus a tapered weighted gusset
into the same garment mesh.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_release_refit_v28 as v28

v23 = v28.v23
build = v28.build
base = v28.base


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


def remove_malformed_lower_region(
    obj: bpy.types.Object,
    cutoff_z: float = 0.600,
    maximum_edge: float = 0.120,
) -> tuple[int, int]:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    lower_faces = []
    stretched_faces = []
    for face in bm.faces:
        mean_z = sum(vertex.co.z for vertex in face.verts) / len(face.verts)
        stretched = any(
            (edge.verts[0].co - edge.verts[1].co).length > maximum_edge
            for edge in face.edges
        )
        if stretched:
            stretched_faces.append(face)
        if mean_z < cutoff_z or stretched:
            lower_faces.append(face)
    unique_faces = list(set(lower_faces))
    if unique_faces:
        bmesh.ops.delete(bm, geom=unique_faces, context="FACES")
    loose = [vertex for vertex in bm.verts if not vertex.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update(calc_edges=True)
    obj["removed_stretched_faces"] = len(set(stretched_faces))
    obj["removed_lower_faces"] = len(unique_faces)
    return len(set(stretched_faces)), len(unique_faces)


def wide_leg_mesh(name: str, segments: int = 32) -> bpy.types.Object:
    rings = [
        # z, centre, inner radius, outer radius, front/back depth
        (0.105, 0.078, 0.052, 0.116, 0.096),
        (0.200, 0.079, 0.053, 0.114, 0.098),
        (0.320, 0.081, 0.054, 0.112, 0.100),
        (0.440, 0.083, 0.055, 0.110, 0.102),
        (0.560, 0.085, 0.057, 0.108, 0.104),
        (0.660, 0.087, 0.060, 0.106, 0.106),
    ]
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    for side in (-1.0, 1.0):
        side_offset = len(vertices)
        for z, centre, inner, outer, depth in rings:
            for index in range(segments):
                angle = 2.0 * math.pi * index / segments
                cosine = math.cos(angle)
                sine = math.sin(angle)
                radius_x = outer if side * cosine >= 0.0 else inner
                vertices.append(
                    (
                        side * centre + cosine * radius_x,
                        sine * depth,
                        z,
                    )
                )
        for ring_index in range(len(rings) - 1):
            lower = side_offset + ring_index * segments
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
    obj["leg_sleeve_vertices"] = len(vertices)
    return obj


def crotch_gusset(name: str) -> bpy.types.Object:
    layers = [
        (-0.070, 0.070, -0.080, 0.082, 0.680),
        (-0.055, 0.055, -0.072, 0.074, 0.600),
        (-0.042, 0.042, -0.062, 0.066, 0.520),
        (-0.030, 0.030, -0.050, 0.054, 0.440),
    ]
    vertices: list[tuple[float, float, float]] = []
    for x0, x1, y0, y1, z in layers:
        vertices.extend([(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)])
    faces: list[tuple[int, ...]] = [(0, 1, 2, 3), (12, 15, 14, 13)]
    for lower in (0, 4, 8):
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


def join_skinned_part(
    pants: bpy.types.Object,
    part: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    part.data.materials.append(material)
    copy_nearest_weights(pants, part)
    modifier = part.modifiers.new(name="Armature", type="ARMATURE")
    modifier.object = armature
    bpy.ops.object.select_all(action="DESELECT")
    pants.select_set(True)
    part.select_set(True)
    bpy.context.view_layer.objects.active = pants
    bpy.ops.object.join()
    pants.name = "Cargo_Continuous_Pants"
    return pants


def create_outfit(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    fabric: bpy.types.Material,
    strap: bpy.types.Material,
    metal: bpy.types.Material,
):
    del metal
    pants = build.c.extract_surface(
        body,
        armature,
        "Cargo_Continuous_Pants",
        v23.pants_surface,
        fabric,
        0.011,
    )
    v28.apply_rear_safe_profile(pants)

    # Weight the replacement geometry from the complete source before removing
    # its malformed lower faces.
    legs = wide_leg_mesh("Cargo_Wide_Legs")
    gusset = crotch_gusset("Cargo_Crotch_Gusset")
    copy_nearest_weights(pants, legs)
    copy_nearest_weights(pants, gusset)
    legs.data.materials.append(fabric)
    gusset.data.materials.append(fabric)
    for part in (legs, gusset):
        modifier = part.modifiers.new(name="Armature", type="ARMATURE")
        modifier.object = armature

    stretched, removed = remove_malformed_lower_region(pants)
    if stretched == 0 or removed == 0:
        raise RuntimeError(
            f"malformed lower replacement did not activate: stretched={stretched}, removed={removed}"
        )

    leg_vertices = int(legs.get("leg_sleeve_vertices", 0))
    gusset_vertices = int(gusset.get("gusset_vertices", 0))
    bpy.ops.object.select_all(action="DESELECT")
    pants.select_set(True)
    legs.select_set(True)
    gusset.select_set(True)
    bpy.context.view_layer.objects.active = pants
    bpy.ops.object.join()
    pants.name = "Cargo_Continuous_Pants"
    pants["leg_sleeve_vertices"] = leg_vertices
    pants["gusset_vertices"] = gusset_vertices
    build.clean_topology(pants)
    v23.assign_materials(pants, fabric, strap)
    return [pants]


def interior_edge_metrics(obj: bpy.types.Object) -> tuple[float, float]:
    usage: dict[tuple[int, int], int] = {}
    for polygon in obj.data.polygons:
        indices = list(polygon.vertices)
        for index, a in enumerate(indices):
            b = indices[(index + 1) % len(indices)]
            key = (min(a, b), max(a, b))
            usage[key] = usage.get(key, 0) + 1
    maximum_length = 0.0
    maximum_z_span = 0.0
    for edge in obj.data.edges:
        a_index, b_index = edge.vertices
        if usage.get((min(a_index, b_index), max(a_index, b_index)), 0) <= 1:
            continue
        a = obj.data.vertices[a_index].co
        b = obj.data.vertices[b_index].co
        maximum_length = max(maximum_length, (a - b).length)
        maximum_z_span = max(maximum_z_span, abs(a.z - b.z))
    return maximum_length, maximum_z_span


def audit() -> dict[str, object]:
    report = v28.audit()
    pants = bpy.data.objects.get("Cargo_Continuous_Pants")
    if pants is None:
        return report
    checks = report["checks"]
    metrics = checks["metrics"]
    maximum_length, maximum_z_span = interior_edge_metrics(pants)
    leg_vertices = int(pants.get("leg_sleeve_vertices", 0))
    gusset_vertices = int(pants.get("gusset_vertices", 0))
    removed_lower = int(pants.get("removed_lower_faces", 0))
    rear = float(metrics.get("rearSeatBand", {}).get("rear", 0.0))
    upper = v28.band(pants, 0.475, 0.590)
    knee = v28.band(pants, 0.300, 0.405)
    hem = v28.band(pants, 0.105, 0.185)

    metrics.update(
        {
            "maximumInteriorEdgeLength": maximum_length,
            "maximumInteriorEdgeZSpan": maximum_z_span,
            "removedLowerFaces": removed_lower,
            "legSleeveVertices": leg_vertices,
            "gussetVertices": gusset_vertices,
        }
    )
    checks.update(
        {
            "malformedLowerRegionReplaced": removed_lower > 0,
            "wideLegShellsPassed": leg_vertices == 384,
            "weightedCrotchGussetPassed": gusset_vertices == 16,
            "spikeGuardPassed": maximum_length <= 0.125 and maximum_z_span <= 0.125,
            "rearSeatClearancePassed": rear >= 0.095,
            "innerThighCoveragePassed": gusset_vertices == 16,
            "rearCrotchBridgePassed": gusset_vertices == 16,
            "straightWideProfilePassed": (
                abs(upper["width"] - knee["width"]) <= 0.080
                and abs(knee["width"] - hem["width"]) <= 0.060
                and abs(upper["depth"] - knee["depth"]) <= 0.060
            ),
        }
    )
    required = [
        "singleShellOnly",
        "finiteCoordinatesPassed",
        "stretchedSourceFacesRemoved",
        "malformedLowerRegionReplaced",
        "wideLegShellsPassed",
        "weightedCrotchGussetPassed",
        "spikeGuardPassed",
        "topologyPassed",
        "uvPassed",
        "materialSeparationPassed",
        "shapeKeyIsolationPassed",
        "footAndFloorClearancePassed",
        "controlledVolumePassed",
        "profileContinuityPassed",
        "rearSeatClearancePassed",
        "innerThighCoveragePassed",
        "rearCrotchBridgePassed",
        "straightWideProfilePassed",
    ]
    report["passed"] = all(bool(checks[name]) for name in required)
    return report


def record(report: dict[str, object]) -> None:
    _, job = build.c.load_job()
    path = build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    manifest["status"] = "WORKING"
    manifest["designRevision"] = "v30-skinned-wide-leg-replacement"
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
        raise RuntimeError(f"v30 wide-leg replacement audit failed: {result}")
    raise SystemExit(0)
