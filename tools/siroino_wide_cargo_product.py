#!/usr/bin/env python3
"""Stable entrypoint for the reviewed Siroino Wide Cargo product."""

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

import render_evidence_bootstrap  # noqa: F401,E402
import runtime_paths  # noqa: E402
import siroino_wide_cargo_current as current
from siroino_wide_cargo_panel_layout import (  # noqa: E402
    build_wide_cargo_panels,
    load_pattern_baseline,
)

PATTERN_BASELINE = load_pattern_baseline()
LEG_BOUNDARY_ROWS = PATTERN_BASELINE["legBoundaryRows"]


def install_runtime_path_compat(implementation: ModuleType) -> None:
    original_load_job = implementation.build.c.load_job

    def load_job_with_runtime_paths():
        path, job = original_load_job()
        runtime = runtime_paths.for_job(ROOT, job)
        resolved = dict(job)
        resolved["artifactDir"] = runtime_paths.relative(ROOT, runtime.reports)
        return path, resolved

    implementation.build.c.load_job = load_job_with_runtime_paths


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


def reviewed_geometry(implementation: ModuleType, segments: int = 48):
    """Generate the four sewn trouser panels from the canonical pattern source."""
    del segments
    return build_wide_cargo_panels(implementation.MeshBuilder(), PATTERN_BASELINE)


def reviewed_create_outfit(
    implementation: ModuleType,
    body,
    armature,
    fabric,
    strap,
    metal,
):
    garments = implementation.create_outfit(body, armature, fabric, strap, metal)
    for garment in garments:
        world_matrix = garment.matrix_world.copy()
        garment.parent = armature
        garment.matrix_world = world_matrix
        if garment.type == "MESH":
            for polygon in garment.data.polygons:
                polygon.use_smooth = True
    return garments


def _mean(values: list[float], label: str) -> float:
    if not values:
        raise RuntimeError(f"Wide Cargo audit has no samples for {label}")
    return sum(values) / len(values)


def _row_extent(vertices, level: float) -> dict[str, float]:
    row = [vertex for vertex in vertices if abs(float(vertex.co.z) - level) <= 0.001]
    if not row:
        raise RuntimeError(f"Wide Cargo audit has no silhouette samples at z={level}")
    xs = [float(vertex.co.x) for vertex in row]
    ys = [float(vertex.co.y) for vertex in row]
    return {"width": max(xs) - min(xs), "depth": max(ys) - min(ys)}


def reviewed_audit(implementation: ModuleType, baseline_audit) -> dict[str, object]:
    report = baseline_audit()
    garment = implementation.bpy.data.objects.get("Cargo_Continuous_Pants")
    if garment is None:
        return report

    checks = report["checks"]
    metrics = checks["metrics"]
    vertices = list(garment.data.vertices)
    zs = [vertex.co.z for vertex in vertices]
    seat = implementation.band(garment, 0.620, 0.800)
    thigh = implementation.band(garment, 0.500, 0.570)
    knee = implementation.band(garment, 0.300, 0.405)
    hem = implementation.band(garment, 0.100, 0.190)

    front_centre = sum(
        1
        for vertex in vertices
        if 0.560 <= vertex.co.z <= 0.820
        and abs(vertex.co.x) <= 0.012
        and vertex.co.y <= -0.090
    )
    rear_centre = sum(
        1
        for vertex in vertices
        if 0.560 <= vertex.co.z <= 0.820
        and abs(vertex.co.x) <= 0.012
        and vertex.co.y >= 0.098
    )
    centre_levels = {
        round(vertex.co.z, 3)
        for vertex in vertices
        if 0.560 <= vertex.co.z <= 0.820 and abs(vertex.co.x) <= 0.012
    }
    crotch_panel_vertices = sum(
        1
        for vertex in vertices
        if 0.573 <= vertex.co.z <= 0.601
        and abs(vertex.co.x) <= 0.091
        and abs(vertex.co.y) <= 0.120
    )

    front_centre_depth = _mean(
        [
            -float(vertex.co.y)
            for vertex in vertices
            if 0.640 <= vertex.co.z <= 0.760
            and abs(vertex.co.x) <= 0.035
            and vertex.co.y <= -0.065
        ],
        "front centre curvature",
    )
    front_side_depth = _mean(
        [
            -float(vertex.co.y)
            for vertex in vertices
            if 0.640 <= vertex.co.z <= 0.760
            and abs(vertex.co.x) >= 0.120
            and vertex.co.y <= -0.065
        ],
        "front side curvature",
    )
    rear_centre_depth = _mean(
        [
            float(vertex.co.y)
            for vertex in vertices
            if 0.640 <= vertex.co.z <= 0.760
            and abs(vertex.co.x) <= 0.035
            and vertex.co.y >= 0.065
        ],
        "rear centre curvature",
    )
    rear_side_depth = _mean(
        [
            float(vertex.co.y)
            for vertex in vertices
            if 0.640 <= vertex.co.z <= 0.760
            and abs(vertex.co.x) >= 0.120
            and vertex.co.y >= 0.065
        ],
        "rear side curvature",
    )
    front_curvature = front_centre_depth - front_side_depth
    rear_curvature = rear_centre_depth - rear_side_depth

    if len(LEG_BOUNDARY_ROWS) < 4:
        raise RuntimeError("Wide Cargo audit needs at least four leg boundary levels")
    upper_inner_thigh_gaps: dict[str, float] = {}
    for level, _, _ in LEG_BOUNDARY_ROWS[-4:]:
        row = [
            vertex for vertex in vertices if abs(float(vertex.co.z) - level) <= 0.001
        ]
        positive_x = [float(vertex.co.x) for vertex in row if vertex.co.x > 0.0]
        negative_x = [float(vertex.co.x) for vertex in row if vertex.co.x < 0.0]
        if not positive_x or not negative_x:
            raise RuntimeError(
                f"Wide Cargo audit has no inner-thigh samples at z={level}"
            )
        upper_inner_thigh_gaps[f"{level:.3f}"] = min(positive_x) - max(negative_x)
    maximum_upper_inner_thigh_gap = max(upper_inner_thigh_gaps.values())

    hip_extent = _row_extent(vertices, 0.700)
    waist_extent = _row_extent(vertices, 0.840)
    upper_thigh_extent = _row_extent(vertices, 0.520)
    hem_extent = _row_extent(vertices, 0.105)

    metrics["bands"] = {
        "seat": seat,
        "thigh": thigh,
        "knee": knee,
        "hem": hem,
    }
    metrics["frontCentreCoverageVertices"] = front_centre
    metrics["rearCentreCoverageVertices"] = rear_centre
    metrics["centreCoverageLevels"] = sorted(centre_levels)
    metrics["crotchPanelVertices"] = crotch_panel_vertices
    metrics["crossSectionCurvature"] = {
        "frontDepthDifference": front_curvature,
        "rearDepthDifference": rear_curvature,
    }
    metrics["upperInnerThighGapByLevel"] = upper_inner_thigh_gaps
    metrics["maximumUpperInnerThighGap"] = maximum_upper_inner_thigh_gap
    metrics["silhouetteByLevel"] = {
        "hip": hip_extent,
        "waist": waist_extent,
        "upperThigh": upper_thigh_extent,
        "hem": hem_extent,
    }

    _, job = implementation.build.c.load_job()
    unity_ready = job.get("unityReady")
    if not isinstance(unity_ready, dict):
        raise RuntimeError("Wide Cargo job is missing unityReady material contract")
    declared_roles = unity_ready.get("materialRoles")
    minimum_materials = unity_ready.get("minimumDistinctMaterials")
    if (
        not isinstance(declared_roles, list)
        or not isinstance(minimum_materials, int)
        or minimum_materials < 2
    ):
        raise RuntimeError("Wide Cargo unityReady material contract is invalid")
    declared_materials = {
        item.get("material")
        for item in declared_roles
        if isinstance(item, dict) and isinstance(item.get("material"), str)
    }
    material_names = [
        material.name for material in garment.data.materials if material is not None
    ]
    metrics["materialNames"] = material_names

    armature_parent = garment.parent
    checks.update(
        {
            "unityReadyMaterialContractPassed": (
                len(material_names) >= minimum_materials
                and len(material_names) == len(set(material_names))
                and set(material_names) == declared_materials
            ),
            "sourceFaceIndependencePassed": min(zs) >= 0.10 and max(zs) <= 0.85,
            "spikeGuardPassed": (
                float(metrics["maximumEdgeLength"]) <= 0.155
                and float(metrics["maximumEdgeZSpan"]) <= 0.070
            ),
            "controlledVolumePassed": (
                float(metrics["totalWidth"]) <= 0.370
                and float(metrics["totalDepth"]) <= 0.275
            ),
            "fittedSeatPassed": (
                float(seat["width"]) <= 0.370 and 0.110 <= float(seat["rear"]) <= 0.138
            ),
            "straightWideProfilePassed": (
                abs(float(thigh["width"]) - float(knee["width"])) <= 0.045
                and abs(float(knee["width"]) - float(hem["width"])) <= 0.035
                and abs(float(thigh["depth"]) - float(knee["depth"])) <= 0.050
            ),
            "crossSectionCurvaturePassed": (
                front_curvature >= 0.008 and rear_curvature >= 0.008
            ),
            "upperInnerThighClearancePassed": maximum_upper_inner_thigh_gap <= 0.020,
            "waistTaperPassed": (
                hip_extent["width"] - waist_extent["width"] >= 0.050
                and hip_extent["depth"] - waist_extent["depth"] >= 0.035
            ),
            "legTaperPassed": (
                upper_thigh_extent["width"] - hem_extent["width"] >= 0.018
                and upper_thigh_extent["depth"] - hem_extent["depth"] >= 0.015
            ),
            "waistCoveragePassed": max(zs) >= 0.83,
            "frontCentreCoveragePassed": front_centre >= 5,
            "rearCentreCoveragePassed": rear_centre >= 5,
            "continuousCentreLevelsPassed": len(centre_levels) >= 5,
            "crotchPanelCoveragePassed": crotch_panel_vertices >= 24,
            "panelFreeTransitionPassed": (
                float(seat["depth"]) >= 0.220 and float(thigh["depth"]) <= 0.205
            ),
            "armatureObjectParentPassed": (
                armature_parent is not None
                and armature_parent.type == "ARMATURE"
                and any(
                    modifier.type == "ARMATURE" and modifier.object is armature_parent
                    for modifier in garment.modifiers
                )
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
        "unityReadyMaterialContractPassed",
        "shapeKeyIsolationPassed",
        "weightingPassed",
        "footAndFloorClearancePassed",
        "controlledVolumePassed",
        "fittedSeatPassed",
        "innerThighCoveragePassed",
        "straightWideProfilePassed",
        "crossSectionCurvaturePassed",
        "upperInnerThighClearancePassed",
        "waistTaperPassed",
        "legTaperPassed",
        "waistCoveragePassed",
        "frontCentreCoveragePassed",
        "rearCentreCoveragePassed",
        "continuousCentreLevelsPassed",
        "crotchPanelCoveragePassed",
        "panelFreeTransitionPassed",
        "armatureObjectParentPassed",
    ]
    report["passed"] = all(bool(checks[name]) for name in required)
    return report


def record(implementation: ModuleType, report: dict[str, object]) -> None:
    _, job = implementation.build.c.load_job()
    path = implementation.build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    manifest["status"] = "WORKING"
    manifest["designRevision"] = "v75-panel-sewn-rise"
    manifest["wearabilityAudit"] = report
    gates = manifest.setdefault("technicalGates", {})
    gates["latestGeometryRender"] = "PASS" if report["passed"] else "FAIL"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    artifact_dir = implementation.build.c.repo_path(job["artifactDir"])
    build_report_path = artifact_dir / "blender-product.json"
    build_report = (
        json.loads(build_report_path.read_text(encoding="utf-8-sig"))
        if build_report_path.is_file()
        else {}
    )
    build_report["passed"] = bool(report["passed"])
    build_report["finalAudit"] = {
        "passed": bool(report["passed"]),
        "unityReadyMaterialContractPassed": bool(
            report.get("checks", {}).get("unityReadyMaterialContractPassed")
        ),
        "materialNames": report.get("checks", {})
        .get("metrics", {})
        .get("materialNames", []),
    }
    build_report_path.parent.mkdir(parents=True, exist_ok=True)
    build_report_path.write_text(
        json.dumps(build_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    implementation = current
    install_runtime_path_compat(implementation)
    clear_stale_evidence(implementation)
    baseline_audit = implementation.audit
    implementation.build_geometry = lambda segments=48: reviewed_geometry(
        implementation,
        segments,
    )
    implementation.build.create_outfit = lambda body, armature, fabric, strap, metal: (
        reviewed_create_outfit(
            implementation,
            body,
            armature,
            fabric,
            strap,
            metal,
        )
    )
    implementation.build.main()
    result = reviewed_audit(implementation, baseline_audit)
    record(implementation, result)
    implementation.base.save_distribution_blend()
    if result.get("passed") is not True:
        raise RuntimeError(f"Wide Cargo audit failed: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
