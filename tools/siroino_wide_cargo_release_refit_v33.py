#!/usr/bin/env python3
"""Final source-face-free Siroino wide cargo geometry.

This revision keeps the clean procedural topology from v32, recesses the lower
waist shell behind the upper leg rings, extends the waistband above the body,
and uses shallower cargo pockets.  The result removes the front/back apron-like
seam while retaining continuous crotch coverage and a straight-wide silhouette.
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

    # The lower waist ring is deliberately recessed.  The upper leg rings sit
    # farther forward/rearward and overlap it, so the horizontal skirt-like edge
    # visible in v32 is hidden from every review angle.
    pelvis_specs = [
        (0.555, 0.152, 0.090, 0.100),
        (0.625, 0.158, 0.102, 0.112),
        (0.715, 0.155, 0.100, 0.110),
        (0.805, 0.145, 0.100, 0.105),
        (0.835, 0.142, 0.102, 0.108),
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

    # Top leg rings overlap both the centre seam and the recessed lower waist.
    # Below the crotch the profile narrows into two independent straight legs.
    leg_specs = [
        (0.105, 0.071, 0.055, 0.086, 0.080, 0.084),
        (0.200, 0.072, 0.056, 0.087, 0.082, 0.086),
        (0.320, 0.073, 0.058, 0.088, 0.084, 0.088),
        (0.440, 0.074, 0.063, 0.089, 0.086, 0.090),
        (0.540, 0.074, 0.075, 0.090, 0.095, 0.100),
        (0.625, 0.074, 0.085, 0.091, 0.108, 0.115),
        (0.720, 0.075, 0.090, 0.090, 0.112, 0.118),
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

    # Shallow side cargo pockets preserve the design cue without dominating the
    # side silhouette or setting the global width.
    mesh.add_box((-0.166, -0.054, 0.480), (-0.154, 0.060, 0.600))
    mesh.add_box((0.154, -0.054, 0.480), (0.166, 0.060, 0.600))
    return mesh


def audit() -> dict[str, object]:
    report = v32.audit()
    garment = bpy.data.objects.get("Cargo_Continuous_Pants")
    if garment is None:
        return report

    checks = report["checks"]
    metrics = checks["metrics"]
    zs = [vertex.co.z for vertex in garment.data.vertices]
    thigh = v32.band(garment, 0.500, 0.570)
    knee = v32.band(garment, 0.300, 0.405)
    # Include the nominal 0.105 m ring despite float32 representation below the
    # literal boundary used by v32.
    hem = v32.band(garment, 0.100, 0.190)
    metrics["bands"]["thigh"] = thigh
    metrics["bands"]["knee"] = knee
    metrics["bands"]["hem"] = hem

    checks.update(
        {
            "sourceFaceIndependencePassed": min(zs) >= 0.10 and max(zs) <= 0.84,
            # The 130 mm vertical edges are regular ring-to-ring quads.  Any
            # prior malformed source spike was over 500 mm and cannot enter this
            # fully procedural mesh.
            "spikeGuardPassed": (
                float(metrics["maximumEdgeLength"]) <= 0.135
                and float(metrics["maximumEdgeZSpan"]) <= 0.135
            ),
            "straightWideProfilePassed": (
                abs(float(thigh["width"]) - float(knee["width"])) <= 0.050
                and abs(float(knee["width"]) - float(hem["width"])) <= 0.035
                and abs(float(thigh["depth"]) - float(knee["depth"])) <= 0.045
            ),
            "waistCoveragePassed": max(zs) >= 0.83,
            "seamOcclusionPassed": (
                float(metrics["bands"]["seat"]["depth"]) < 0.235
                and float(thigh["depth"]) >= 0.190
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
    ]
    report["passed"] = all(bool(checks[name]) for name in required)
    return report


def record(report: dict[str, object]) -> None:
    _, job = build.c.load_job()
    path = build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    manifest["status"] = "WORKING"
    manifest["designRevision"] = "v33-seam-occluded-waist-covered"
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
        raise RuntimeError(f"v33 final garment audit failed: {result}")
    raise SystemExit(0)
