#!/usr/bin/env python3
"""Final tapered-yoke geometry for Siroino wide cargo trousers.

This revision removes the rectangular front/back crotch flap left by v33.  A
short tapered centre yoke joins the fitted seat to two non-crossing leg shells,
so the crotch reads as a conventional trouser fork rather than an apron panel.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_release_refit_v32 as v32

build = v32.build
base = v32.base


def build_geometry(segments: int = 48) -> v32.MeshBuilder:
    mesh = v32.MeshBuilder()

    # A compact lower ring expands into the seat over only 80 mm.  The tapered
    # transition avoids the long constant-width panel visible in v33.
    pelvis_specs = [
        (0.540, 0.056, 0.060, 0.068),
        (0.620, 0.150, 0.100, 0.112),
        (0.700, 0.157, 0.102, 0.114),
        (0.775, 0.149, 0.100, 0.110),
        (0.840, 0.142, 0.102, 0.108),
    ]
    pelvis_rings = [
        mesh.add_ring(
            v32.pelvis_ring(
                half_width=width,
                front_depth=front,
                rear_depth=rear,
                z=z,
                segments=segments,
            )
        )
        for z, width, front, rear in pelvis_specs
    ]
    for lower, upper in zip(pelvis_rings, pelvis_rings[1:]):
        mesh.bridge(lower, upper)

    # Independent leg shells never cross the centre plane.  Their top rings
    # overlap the yoke laterally and vertically, hiding the join while retaining
    # a narrow, conventional crotch fork.
    leg_specs = [
        (0.105, 0.078, 0.068, 0.079, 0.080, 0.084),
        (0.200, 0.078, 0.068, 0.080, 0.082, 0.086),
        (0.320, 0.078, 0.069, 0.082, 0.084, 0.088),
        (0.440, 0.078, 0.070, 0.084, 0.086, 0.090),
        (0.530, 0.078, 0.071, 0.086, 0.090, 0.095),
        (0.600, 0.078, 0.073, 0.089, 0.098, 0.104),
        (0.660, 0.078, 0.076, 0.091, 0.104, 0.110),
    ]
    for side in (-1.0, 1.0):
        rings = [
            mesh.add_ring(
                v32.asymmetric_ellipse_ring(
                    center_x=center,
                    inner_radius=inner,
                    outer_radius=outer,
                    front_depth=front,
                    rear_depth=rear,
                    z=z,
                    side=side,
                    segments=segments,
                )
            )
            for z, center, inner, outer, front, rear in leg_specs
        ]
        for lower, upper in zip(rings, rings[1:]):
            mesh.bridge(lower, upper)

    # Shallow outer-thigh cargo pockets preserve the design cue without turning
    # the side silhouette into a rectangular block.
    mesh.add_box((-0.166, -0.052, 0.475), (-0.154, 0.058, 0.590))
    mesh.add_box((0.154, -0.052, 0.475), (0.166, 0.058, 0.590))
    return mesh


def audit() -> dict[str, object]:
    report = v32.audit()
    garment = bpy.data.objects.get("Cargo_Continuous_Pants")
    if garment is None:
        return report

    checks = report["checks"]
    metrics = checks["metrics"]
    zs = [vertex.co.z for vertex in garment.data.vertices]
    seat = v32.band(garment, 0.620, 0.750)
    thigh = v32.band(garment, 0.500, 0.570)
    knee = v32.band(garment, 0.300, 0.405)
    hem = v32.band(garment, 0.100, 0.190)
    metrics["bands"] = {"seat": seat, "thigh": thigh, "knee": knee, "hem": hem}

    checks.update(
        {
            "sourceFaceIndependencePassed": min(zs) >= 0.10 and max(zs) <= 0.85,
            "spikeGuardPassed": (
                float(metrics["maximumEdgeLength"]) <= 0.140
                and float(metrics["maximumEdgeZSpan"]) <= 0.100
            ),
            "fittedSeatPassed": (
                float(seat["width"]) <= 0.335
                and 0.105 <= float(seat["rear"]) <= 0.120
            ),
            "straightWideProfilePassed": (
                abs(float(thigh["width"]) - float(knee["width"])) <= 0.045
                and abs(float(knee["width"]) - float(hem["width"])) <= 0.030
                and abs(float(thigh["depth"]) - float(knee["depth"])) <= 0.045
            ),
            "waistCoveragePassed": max(zs) >= 0.83,
            "seamOcclusionPassed": (
                float(seat["depth"]) <= 0.230
                and float(thigh["depth"]) >= 0.180
            ),
            "taperedForkPassed": (
                float(metrics["centerCoverageVertices"]) >= 20
                and float(thigh["width"]) >= 0.315
            ),
        }
    )
    required = [
        "singleMeshObjectPassed",
        "finiteCoordinatesPassed",
        "topologyPassed",
        "sourceFaceIndependencePassed",
        "spikeGuardPassed",
        "uvPassed",
        "materialSeparationPassed",
        "shapeKeyIsolationPassed",
        "weightingPassed",
        "footAndFloorClearancePassed",
        "controlledVolumePassed",
        "fittedSeatPassed",
        "innerThighCoveragePassed",
        "straightWideProfilePassed",
        "waistCoveragePassed",
        "seamOcclusionPassed",
        "taperedForkPassed",
    ]
    report["passed"] = all(bool(checks[name]) for name in required)
    return report


def record(report: dict[str, object]) -> None:
    _, job = build.c.load_job()
    path = build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    manifest["status"] = "WORKING"
    manifest["designRevision"] = "v34-tapered-crotch-yoke"
    manifest["wearabilityAudit"] = report
    gates = manifest.setdefault("technicalGates", {})
    gates["latestGeometryRender"] = "PASS" if report["passed"] else "FAIL"
    gates["humanVisualReview"] = "PENDING"
    gates["humanPoseReview"] = "PENDING"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


v32.build_geometry = build_geometry
v32.build.create_outfit = v32.create_outfit


if __name__ == "__main__":
    build.main()
    result = audit()
    record(result)
    base.save_distribution_blend()
    if not result["passed"]:
        raise RuntimeError(f"v34 final garment audit failed: {result}")
    raise SystemExit(0)
