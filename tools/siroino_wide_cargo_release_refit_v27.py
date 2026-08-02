#!/usr/bin/env python3
"""Excise malformed stretched faces from the rear-safe wide-cargo shell.

The source-surface extraction contains a small number of polygons whose edges
span from an ankle/hem vertex to the crotch.  They remain topologically valid,
so ordinary degenerate cleanup cannot remove them, but after profiling they
render as diagonal waist spikes.  This revision removes only faces containing
an edge longer than 120 mm, deletes newly loose vertices, then runs the normal
triangulation cleanup and all v25 rear/silhouette gates.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bmesh
import bpy

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_release_refit_v26 as v26

v25 = v26.v25
build = v26.build
base = v26.base


def remove_stretched_faces(obj: bpy.types.Object, maximum_edge: float = 0.120) -> int:
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bad_faces = []
    for face in bm.faces:
        if any((edge.verts[0].co - edge.verts[1].co).length > maximum_edge for edge in face.edges):
            bad_faces.append(face)
    removed = len(bad_faces)
    if bad_faces:
        bmesh.ops.delete(bm, geom=bad_faces, context="FACES")
        loose_vertices = [vertex for vertex in bm.verts if not vertex.link_faces]
        if loose_vertices:
            bmesh.ops.delete(bm, geom=loose_vertices, context="VERTS")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update(calc_edges=True)
    obj["removed_stretched_faces"] = removed
    return removed


def create_outfit_v27(body, armature, fabric, strap, metal):
    del metal
    pants = build.c.extract_surface(
        body,
        armature,
        "Cargo_Continuous_Pants",
        v25.pants_surface,
        fabric,
        0.0120,
    )
    v26.apply_profile_v26(pants)
    removed = remove_stretched_faces(pants)
    if removed == 0:
        raise RuntimeError("Expected at least one stretched source face to be removed")
    build.clean_topology(pants)
    v25.assign_materials(pants, fabric, strap)
    return [pants]


def record(report: dict[str, object]) -> None:
    pants = bpy.data.objects.get("Cargo_Continuous_Pants")
    checks = report.setdefault("checks", {})
    metrics = checks.setdefault("metrics", {})
    metrics["removedStretchedFaces"] = int(pants.get("removed_stretched_faces", 0)) if pants else 0
    checks["stretchedSourceFacesRemoved"] = metrics["removedStretchedFaces"] > 0
    report["passed"] = bool(report.get("passed")) and bool(checks["stretchedSourceFacesRemoved"])

    _, job = build.c.load_job()
    path = build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    manifest["status"] = "WORKING"
    manifest["designRevision"] = "v27-stretched-face-free-rear-coverage"
    manifest["wearabilityAudit"] = report
    gates = manifest.setdefault("technicalGates", {})
    gates["latestGeometryRender"] = "PASS" if report.get("passed") is True else "FAIL"
    gates["humanVisualReview"] = "PENDING"
    gates["humanPoseReview"] = "PENDING"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


build.create_outfit = create_outfit_v27


if __name__ == "__main__":
    build.main()
    result = v25.audit()
    record(result)
    base.save_distribution_blend()
    if result.get("passed") is not True:
        raise RuntimeError(f"v27 stretched-face/rear audit failed: {result}")
    raise SystemExit(0)
