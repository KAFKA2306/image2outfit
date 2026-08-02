#!/usr/bin/env python3
"""Stable entrypoint for the reviewed Siroino Wide Cargo v38 product."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_current as current


def clear_stale_evidence(implementation: ModuleType) -> None:
    _, job = implementation.build.c.load_job()
    preview_root = implementation.build.c.repo_path(job["productRoot"]) / "Previews"
    if not preview_root.exists():
        return
    for pattern in ("*.png", "*.webp", "*.png.meta", "*.webp.meta"):
        for path in preview_root.glob(pattern):
            path.unlink(missing_ok=True)
    shutil.rmtree(preview_root / "Poses", ignore_errors=True)
    (preview_root / "Poses.meta").unlink(missing_ok=True)


def reviewed_geometry(
    implementation: ModuleType,
    segments: int = 48,
):
    mesh = implementation.MeshBuilder()

    # The seat shell is recessed behind the upper legs. Its lower edge is not
    # visible as the rectangular front/back flap present in earlier revisions.
    pelvis_specs = [
        (0.735, 0.140, 0.088, 0.096),
        (0.775, 0.150, 0.101, 0.111),
        (0.810, 0.146, 0.102, 0.110),
        (0.840, 0.142, 0.102, 0.108),
    ]
    pelvis_rings = [
        mesh.add_ring(
            implementation.pelvis_ring(
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

    # The sections remain separate below the fork and converge at z=.58. From
    # there upward they share the front and rear centre line and overlap by
    # 16 mm, closing the skin slit without creating long spike polygons.
    leg_specs = [
        (0.105, 0.078, 0.068, 0.079, 0.080, 0.084),
        (0.200, 0.078, 0.068, 0.080, 0.082, 0.086),
        (0.320, 0.078, 0.069, 0.082, 0.084, 0.088),
        (0.440, 0.078, 0.070, 0.084, 0.086, 0.090),
        (0.540, 0.078, 0.071, 0.086, 0.092, 0.097),
        (0.580, 0.000, 0.008, 0.176, 0.104, 0.110),
        (0.640, 0.000, 0.008, 0.176, 0.112, 0.118),
        (0.700, 0.000, 0.008, 0.176, 0.120, 0.126),
        (0.750, 0.000, 0.008, 0.176, 0.126, 0.132),
        (0.790, 0.000, 0.008, 0.176, 0.130, 0.136),
    ]
    for side in (-1.0, 1.0):
        rings = [
            mesh.add_ring(
                implementation.asymmetric_ellipse_ring(
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

    mesh.add_box((-0.168, -0.050, 0.475), (-0.155, 0.058, 0.590))
    mesh.add_box((0.155, -0.050, 0.475), (0.168, 0.058, 0.590))
    return mesh


def reviewed_audit(
    implementation: ModuleType,
    baseline_audit,
) -> dict[str, object]:
    report = baseline_audit()
    garment = implementation.bpy.data.objects.get("Cargo_Continuous_Pants")
    if garment is None:
        return report

    checks = report["checks"]
    metrics = checks["metrics"]
    zs = [vertex.co.z for vertex in garment.data.vertices]
    seat = implementation.band(garment, 0.620, 0.800)
    thigh = implementation.band(garment, 0.500, 0.570)
    knee = implementation.band(garment, 0.300, 0.405)
    hem = implementation.band(garment, 0.100, 0.190)

    front_centre = sum(
        1
        for vertex in garment.data.vertices
        if 0.580 <= vertex.co.z <= 0.800
        and abs(vertex.co.x) <= 0.010
        and vertex.co.y <= -0.100
    )
    rear_centre = sum(
        1
        for vertex in garment.data.vertices
        if 0.580 <= vertex.co.z <= 0.800
        and abs(vertex.co.x) <= 0.010
        and vertex.co.y >= 0.106
    )
    centre_levels = {
        round(vertex.co.z, 3)
        for vertex in garment.data.vertices
        if 0.580 <= vertex.co.z <= 0.800 and abs(vertex.co.x) <= 0.010
    }
    metrics["bands"] = {
        "seat": seat,
        "thigh": thigh,
        "knee": knee,
        "hem": hem,
    }
    metrics["frontCentreCoverageVertices"] = front_centre
    metrics["rearCentreCoverageVertices"] = rear_centre
    metrics["centreCoverageLevels"] = sorted(centre_levels)

    checks.update(
        {
            "sourceFaceIndependencePassed": min(zs) >= 0.10 and max(zs) <= 0.85,
            "spikeGuardPassed": (
                float(metrics["maximumEdgeLength"]) <= 0.155
                and float(metrics["maximumEdgeZSpan"]) <= 0.125
            ),
            "controlledVolumePassed": (
                float(metrics["totalWidth"]) <= 0.370
                and float(metrics["totalDepth"]) <= 0.275
            ),
            "fittedSeatPassed": (
                float(seat["width"]) <= 0.370
                and 0.110 <= float(seat["rear"]) <= 0.138
            ),
            "straightWideProfilePassed": (
                abs(float(thigh["width"]) - float(knee["width"])) <= 0.045
                and abs(float(knee["width"]) - float(hem["width"])) <= 0.030
                and abs(float(thigh["depth"]) - float(knee["depth"])) <= 0.045
            ),
            "waistCoveragePassed": max(zs) >= 0.83,
            "frontCentreCoveragePassed": front_centre >= 8,
            "rearCentreCoveragePassed": rear_centre >= 8,
            "continuousCentreLevelsPassed": len(centre_levels) >= 5,
            "panelFreeTransitionPassed": (
                float(seat["depth"]) >= 0.250
                and float(thigh["depth"]) <= 0.195
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
        "frontCentreCoveragePassed",
        "rearCentreCoveragePassed",
        "continuousCentreLevelsPassed",
        "panelFreeTransitionPassed",
    ]
    report["passed"] = all(bool(checks[name]) for name in required)
    return report


def record(implementation: ModuleType, report: dict[str, object]) -> None:
    _, job = implementation.build.c.load_job()
    path = implementation.build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    manifest["status"] = "WORKING"
    manifest["designRevision"] = "v38-reviewed-converged-crotch"
    manifest["wearabilityAudit"] = report
    gates = manifest.setdefault("technicalGates", {})
    gates["latestGeometryRender"] = "PASS" if report["passed"] else "FAIL"
    gates["humanVisualReview"] = "PENDING"
    gates["humanPoseReview"] = "PENDING"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    implementation = current
    clear_stale_evidence(implementation)
    baseline_audit = implementation.audit
    implementation.build_geometry = lambda segments=48: reviewed_geometry(
        implementation,
        segments,
    )
    implementation.build.create_outfit = implementation.create_outfit
    implementation.build.main()
    result = reviewed_audit(implementation, baseline_audit)
    record(implementation, result)
    implementation.base.save_distribution_blend()
    if result.get("passed") is not True:
        raise RuntimeError(f"Wide Cargo audit failed: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
