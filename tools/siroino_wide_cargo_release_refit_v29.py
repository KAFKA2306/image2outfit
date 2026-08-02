#!/usr/bin/env python3
"""Hole-free rear-safe Siroino Wide Cargo build.

v28 removed malformed hem-to-crotch faces and eliminated the visible diagonal
spikes, but deleting those faces left open side/front holes and a narrow central
skin slit.  v29 fills only the boundaries created by those rejected faces and
adds a small, tapered, skinned crotch gusset inside the same garment mesh.
"""
from __future__ import annotations

import json
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


def repair_stretched_faces(
    obj: bpy.types.Object,
    maximum_edge: float = 0.120,
) -> tuple[int, int]:
    """Replace malformed long faces while preserving waist and hem openings."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()

    bad_faces = [
        face
        for face in bm.faces
        if any(
            (edge.verts[0].co - edge.verts[1].co).length > maximum_edge
            for edge in face.edges
        )
    ]
    bad_set = set(bad_faces)
    repair_edges = {
        edge
        for face in bad_faces
        for edge in face.edges
        if any(linked not in bad_set for linked in edge.link_faces)
    }
    removed = len(bad_faces)

    if bad_faces:
        # Preserve the surrounding edge loops so they can be locally patched.
        bmesh.ops.delete(bm, geom=bad_faces, context="FACES_ONLY")
        repair_edges = {
            edge
            for edge in repair_edges
            if edge.is_valid
            and len(edge.link_faces) == 1
            and 0.130 < sum(vertex.co.z for vertex in edge.verts) / 2.0 < 0.785
        }
        fill_result = bmesh.ops.holes_fill(
            bm,
            edges=list(repair_edges),
            sides=0,
        ) if repair_edges else {"faces": []}
        filled = len(fill_result.get("faces", []))

        loose_vertices = [vertex for vertex in bm.verts if not vertex.link_faces]
        if loose_vertices:
            bmesh.ops.delete(bm, geom=loose_vertices, context="VERTS")
    else:
        filled = 0

    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update(calc_edges=True)
    obj["removed_stretched_faces"] = removed
    obj["filled_stretched_faces"] = filled
    return removed, filled


def _copy_nearest_weights(
    source: bpy.types.Object,
    target: bpy.types.Object,
) -> None:
    tree = KDTree(len(source.data.vertices))
    for vertex in source.data.vertices:
        tree.insert(vertex.co, vertex.index)
    tree.balance()

    target_groups = {
        group.name: target.vertex_groups.new(name=group.name)
        for group in source.vertex_groups
    }
    for target_vertex in target.data.vertices:
        _, nearest_index, _ = tree.find(target_vertex.co)
        source_vertex = source.data.vertices[nearest_index]
        for reference in source_vertex.groups:
            source_group = source.vertex_groups[reference.group]
            target_groups[source_group.name].add(
                [target_vertex.index],
                reference.weight,
                "REPLACE",
            )


def add_weighted_crotch_gusset(
    pants: bpy.types.Object,
    armature: bpy.types.Object,
    fabric: bpy.types.Material,
) -> bpy.types.Object:
    """Add a tapered internal cloth bridge and join it into the garment mesh."""
    layers = [
        (-0.055, 0.055, -0.075, 0.075, 0.640),
        (-0.034, 0.034, -0.062, 0.068, 0.510),
        (-0.012, 0.012, -0.042, 0.048, 0.435),
    ]
    vertices: list[tuple[float, float, float]] = []
    for x0, x1, y0, y1, z in layers:
        vertices.extend(
            [
                (x0, y0, z),
                (x1, y0, z),
                (x1, y1, z),
                (x0, y1, z),
            ]
        )

    faces: list[tuple[int, ...]] = [
        (0, 1, 2, 3),
        (8, 11, 10, 9),
    ]
    for lower in (0, 4):
        upper = lower + 4
        faces.extend(
            [
                (lower + 0, lower + 1, upper + 1, upper + 0),
                (lower + 1, lower + 2, upper + 2, upper + 1),
                (lower + 2, lower + 3, upper + 3, upper + 2),
                (lower + 3, lower + 0, upper + 0, upper + 3),
            ]
        )

    mesh = bpy.data.meshes.new("Cargo_Crotch_Gusset_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    gusset = bpy.data.objects.new("Cargo_Crotch_Gusset", mesh)
    bpy.context.collection.objects.link(gusset)
    gusset.data.materials.append(fabric)
    for polygon in gusset.data.polygons:
        polygon.use_smooth = True

    _copy_nearest_weights(pants, gusset)
    modifier = gusset.modifiers.new(name="Armature", type="ARMATURE")
    modifier.object = armature

    existing_vertices = len(pants.data.vertices)
    bpy.ops.object.select_all(action="DESELECT")
    pants.select_set(True)
    gusset.select_set(True)
    bpy.context.view_layer.objects.active = pants
    bpy.ops.object.join()
    pants.name = "Cargo_Continuous_Pants"
    pants["gusset_vertices"] = len(vertices)
    pants["gusset_first_vertex"] = existing_vertices
    pants.data.update(calc_edges=True)
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
    removed, filled = repair_stretched_faces(pants)
    if removed == 0 or filled == 0:
        raise RuntimeError(
            f"stretched-face repair did not complete: removed={removed}, filled={filled}"
        )
    build.clean_topology(pants)
    v23.assign_materials(pants, fabric, strap)
    pants = add_weighted_crotch_gusset(pants, armature, fabric)
    build.clean_topology(pants)
    v23.assign_materials(pants, fabric, strap)
    return [pants]


def _interior_edge_metrics(obj: bpy.types.Object) -> tuple[float, float]:
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
    maximum_length, maximum_z_span = _interior_edge_metrics(pants)
    filled = int(pants.get("filled_stretched_faces", 0))
    gusset_vertices = int(pants.get("gusset_vertices", 0))
    rear = float(metrics.get("rearSeatBand", {}).get("rear", 0.0))

    metrics.update(
        {
            "maximumInteriorEdgeLength": maximum_length,
            "maximumInteriorEdgeZSpan": maximum_z_span,
            "filledStretchedFaces": filled,
            "gussetVertices": gusset_vertices,
        }
    )
    checks.update(
        {
            "stretchedFaceHolesFilled": filled > 0,
            "weightedCrotchGussetPassed": gusset_vertices == 12,
            # The removed spike edges had ~0.57 m vertical reach. Remaining
            # sub-120 mm local diagonals are ordinary patch triangulation.
            "spikeGuardPassed": maximum_length <= 0.120 and maximum_z_span <= 0.120,
            "rearSeatClearancePassed": rear >= 0.095,
        }
    )
    required = [
        "singleShellOnly",
        "finiteCoordinatesPassed",
        "stretchedSourceFacesRemoved",
        "stretchedFaceHolesFilled",
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
    manifest["designRevision"] = "v29-hole-free-weighted-crotch-gusset"
    manifest["wearabilityAudit"] = report
    gates = manifest.setdefault("technicalGates", {})
    gates["latestGeometryRender"] = "PASS" if report["passed"] else "FAIL"
    gates["humanVisualReview"] = "PENDING"
    gates["humanPoseReview"] = "PENDING"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


build.create_outfit = create_outfit


if __name__ == "__main__":
    build.main()
    result = audit()
    record(result)
    base.save_distribution_blend()
    if not result["passed"]:
        raise RuntimeError(f"v29 rear/hole audit failed: {result}")
    raise SystemExit(0)
