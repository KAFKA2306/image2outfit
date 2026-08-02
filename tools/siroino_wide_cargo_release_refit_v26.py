#!/usr/bin/env python3
"""Topology-safe rear correction for Siroino Wide Cargo.

The v25 profile achieved continuous rear and inner-thigh coverage, but cleaning
and triangulating the unprofiled body surface first left a diagonal whose ends
later moved from the hem to the crotch, producing visible waist spikes.  This
entry profiles the source polygons first and only then performs topology cleanup.
It also adds a local rear-seat allowance without changing the accepted straight
wide-leg bands.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_release_refit_v25 as v25

build = v25.build
base = v25.base
smoothstep = v25.smoothstep
clamp = v25.clamp


def apply_profile_v26(obj: bpy.types.Object) -> None:
    v25.apply_profile(obj)
    for vertex in obj.data.vertices:
        x, y, z = vertex.co
        if y <= 0.0:
            continue
        seat_zone = (
            smoothstep(0.575, 0.635, z)
            * (1.0 - smoothstep(0.755, 0.805, z))
        )
        centre_zone = 1.0 - smoothstep(0.020, 0.150, abs(x))
        vertex.co.y = clamp(
            y + 0.0120 * seat_zone * (0.72 + 0.28 * centre_zone),
            -0.125,
            0.130,
        )
    obj.data.update(calc_edges=True)


def create_outfit_v26(body, armature, fabric, strap, metal):
    del metal
    pants = build.c.extract_surface(
        body,
        armature,
        "Cargo_Continuous_Pants",
        v25.pants_surface,
        fabric,
        0.0120,
    )
    # Profile connected source polygons before triangulation.  Cleaning first
    # was the direct cause of the hem-to-crotch diagonal in the rejected v25.
    apply_profile_v26(pants)
    build.clean_topology(pants)
    v25.assign_materials(pants, fabric, strap)
    return [pants]


def record(report: dict[str, object]) -> None:
    _, job = build.c.load_job()
    path = build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    manifest["status"] = "WORKING"
    manifest["designRevision"] = "v26-topology-safe-rear-coverage"
    manifest["wearabilityAudit"] = report
    gates = manifest.setdefault("technicalGates", {})
    gates["latestGeometryRender"] = "PASS" if report.get("passed") is True else "FAIL"
    gates["humanVisualReview"] = "PENDING"
    gates["humanPoseReview"] = "PENDING"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


build.create_outfit = create_outfit_v26


if __name__ == "__main__":
    build.main()
    result = v25.audit()
    record(result)
    base.save_distribution_blend()
    if result.get("passed") is not True:
        raise RuntimeError(f"v26 rear/topology audit failed: {result}")
    raise SystemExit(0)
