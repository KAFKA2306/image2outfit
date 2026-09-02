#!/usr/bin/env python3
"""Stable entrypoint for the reviewed Siroino Wide Cargo product."""

from __future__ import annotations

import json
import math
import shutil
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
PATTERN_SPEC_PATH = (
    ROOT / "Assets/GenWorks/siroino-wide-cargo/Source/Patterns/pattern-spec.json"
)
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import render_evidence_bootstrap  # noqa: F401,E402
import runtime_paths  # noqa: E402
import siroino_wide_cargo_current as current


def _numeric_rows(
    value: object, width: int, label: str
) -> tuple[tuple[float, ...], ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"Wide Cargo pattern data has no {label}")
    rows = []
    for row in value:
        if not isinstance(row, list) or len(row) != width:
            raise ValueError(f"Wide Cargo pattern data has invalid {label} row: {row}")
        if not all(isinstance(item, (int, float)) for item in row):
            raise ValueError(
                f"Wide Cargo pattern data has non-numeric {label} row: {row}"
            )
        rows.append(tuple(float(item) for item in row))
    return tuple(rows)


def _pattern_reference(
    value: object,
    panel_boundaries: dict[str, set[str]],
    label: str,
) -> str:
    if not isinstance(value, str) or value.count(":") != 1:
        raise ValueError(f"Wide Cargo pattern data has invalid {label}: {value}")
    panel_id, boundary = value.split(":", 1)
    if panel_id not in panel_boundaries:
        raise ValueError(f"Wide Cargo {label} references unknown panel: {value}")
    if boundary not in panel_boundaries[panel_id]:
        raise ValueError(f"Wide Cargo {label} references unknown boundary: {value}")
    return value


def _validate_pattern_connectivity(document: dict[str, object]) -> None:
    acceptance = document.get("acceptance")
    if not isinstance(acceptance, dict):
        raise ValueError("Wide Cargo pattern source has no acceptance contract")

    panels = document.get("panels")
    if not isinstance(panels, list):
        raise ValueError("Wide Cargo pattern source has no panels")
    panel_count = acceptance.get("panelCount")
    if not isinstance(panel_count, int) or len(panels) != panel_count:
        raise ValueError("Wide Cargo panel count does not match acceptance contract")

    panel_boundaries: dict[str, set[str]] = {}
    for panel in panels:
        if not isinstance(panel, dict):
            raise ValueError(f"Wide Cargo pattern data has invalid panel: {panel}")
        panel_id = panel.get("id")
        boundaries = panel.get("boundaries")
        if not isinstance(panel_id, str) or not panel_id:
            raise ValueError(
                f"Wide Cargo pattern data has invalid panel id: {panel_id}"
            )
        if panel_id in panel_boundaries:
            raise ValueError(
                f"Wide Cargo pattern data has duplicate panel id: {panel_id}"
            )
        if (
            not isinstance(boundaries, list)
            or not boundaries
            or not all(
                isinstance(boundary, str) and boundary for boundary in boundaries
            )
            or len(set(boundaries)) != len(boundaries)
        ):
            raise ValueError(f"Wide Cargo panel has invalid boundaries: {panel_id}")
        panel_boundaries[panel_id] = set(boundaries)

    seam_pairs = document.get("seamPairs")
    if not isinstance(seam_pairs, list):
        raise ValueError("Wide Cargo pattern source has no seamPairs")
    seam_pair_count = acceptance.get("seamPairCount")
    if not isinstance(seam_pair_count, int) or len(seam_pairs) != seam_pair_count:
        raise ValueError(
            "Wide Cargo seam pair count does not match acceptance contract"
        )

    seam_references: set[str] = set()
    for pair in seam_pairs:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError(f"Wide Cargo pattern data has invalid seam pair: {pair}")
        first = _pattern_reference(pair[0], panel_boundaries, "seam")
        second = _pattern_reference(pair[1], panel_boundaries, "seam")
        if first == second:
            raise ValueError(f"Wide Cargo seam cannot reference itself: {first}")
        for reference in (first, second):
            if reference in seam_references:
                raise ValueError(
                    f"Wide Cargo boundary appears in more than one seam: {reference}"
                )
            seam_references.add(reference)

    open_boundaries = document.get("openBoundaries")
    if not isinstance(open_boundaries, list):
        raise ValueError("Wide Cargo pattern source has no openBoundaries")
    open_references = {
        _pattern_reference(value, panel_boundaries, "open boundary")
        for value in open_boundaries
    }
    if len(open_references) != len(open_boundaries):
        raise ValueError("Wide Cargo pattern source has duplicate open boundaries")
    overlap = seam_references & open_references
    if overlap:
        raise ValueError(
            f"Wide Cargo boundaries cannot be both sewn and open: {sorted(overlap)}"
        )

    declared_references = {
        f"{panel_id}:{boundary}"
        for panel_id, boundaries in panel_boundaries.items()
        for boundary in boundaries
    }
    accounted_references = seam_references | open_references
    if declared_references != accounted_references:
        missing = sorted(declared_references - accounted_references)
        extra = sorted(accounted_references - declared_references)
        raise ValueError(
            "Wide Cargo pattern boundaries are not fully accounted for: "
            f"missing={missing}, extra={extra}"
        )

    if acceptance.get("allSeamReferencesMustExist") is not True:
        raise ValueError("Wide Cargo acceptance must require valid seam references")
    if acceptance.get("waistAndHemRemainOpen") is not True:
        raise ValueError("Wide Cargo acceptance must require open waist and hem")
    required_open = {
        f"{panel_id}:{boundary}"
        for panel_id, boundaries in panel_boundaries.items()
        for boundary in ("waist", "hem")
        if boundary in boundaries
    }
    if required_open != open_references:
        raise ValueError("Wide Cargo open boundaries must be exactly waist and hem")


def _load_pattern_baseline() -> dict[str, object]:
    if not PATTERN_SPEC_PATH.is_file():
        raise FileNotFoundError(
            f"Wide Cargo pattern source is missing: {PATTERN_SPEC_PATH}"
        )
    document = json.loads(PATTERN_SPEC_PATH.read_text(encoding="utf-8-sig"))
    if document.get("productId") != "siroino-wide-cargo":
        raise ValueError("Wide Cargo pattern source has the wrong productId")
    if document.get("units") != "m":
        raise ValueError("Wide Cargo pattern source must use metres")
    source = document.get("source")
    if not isinstance(source, dict) or source.get("baselineDesignRevision") != (
        "v74-centre-crotch-seam"
    ):
        raise ValueError("Wide Cargo pattern source baseline revision is not v74")
    _validate_pattern_connectivity(document)
    baseline = document.get("baselineGeometry")
    if not isinstance(baseline, dict):
        raise ValueError("Wide Cargo pattern source has no baselineGeometry")
    back_rise = _numeric_rows(baseline.get("backRise"), 2, "backRise")
    front_rise = _numeric_rows(baseline.get("frontRise"), 2, "frontRise")
    if len(back_rise) != len(front_rise):
        raise ValueError("Wide Cargo frontRise and backRise point counts differ")
    if back_rise[-1] != front_rise[0]:
        raise ValueError("Wide Cargo frontRise and backRise do not share centre point")
    outseam = _numeric_rows(baseline.get("outseam"), 2, "outseam")
    inseam = _numeric_rows(baseline.get("inseam"), 2, "inseam")
    if len(outseam) != len(inseam):
        raise ValueError("Wide Cargo outseam and inseam point counts differ")
    leg_boundary_rows = []
    for outside, inside in zip(outseam, inseam):
        outer, outer_z = outside
        inner, inner_z = inside
        if outer_z != inner_z:
            raise ValueError("Wide Cargo outseam and inseam levels differ")
        if outer <= inner:
            raise ValueError("Wide Cargo outseam must stay outside inseam")
        leg_boundary_rows.append((outer_z, outer, inner))
    return {
        "frontDepthProfile": _numeric_rows(
            baseline.get("frontDepthProfile"), 2, "frontDepthProfile"
        ),
        "rearDepthProfile": _numeric_rows(
            baseline.get("rearDepthProfile"), 2, "rearDepthProfile"
        ),
        "legBoundaryRows": tuple(leg_boundary_rows),
        "upperRows": _numeric_rows(baseline.get("upperRows"), 2, "upperRows"),
        "crotchCentre": back_rise + front_rise[1:],
    }


PATTERN_BASELINE = _load_pattern_baseline()
FRONT_DEPTH = PATTERN_BASELINE["frontDepthProfile"]
REAR_DEPTH = PATTERN_BASELINE["rearDepthProfile"]
LEG_BOUNDARY_ROWS = PATTERN_BASELINE["legBoundaryRows"]
UPPER_SPECS = PATTERN_BASELINE["upperRows"]
CROTCH_CENTRE = PATTERN_BASELINE["crotchCentre"]


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


def _smoothstep(value: float) -> float:
    return value * value * (3.0 - 2.0 * value)


def _profile_value(z: float, points: tuple[tuple[float, float], ...]) -> float:
    if z <= points[0][0]:
        return points[0][1]
    if z >= points[-1][0]:
        return points[-1][1]
    for (z0, value0), (z1, value1) in zip(points, points[1:]):
        if z <= z1:
            t = _smoothstep((z - z0) / (z1 - z0))
            return value0 + (value1 - value0) * t
    raise RuntimeError(f"Wide Cargo profile interpolation failed at z={z}")


def _circumferential_points(
    *,
    centre_x: float,
    half_width: float,
    z: float,
    count: int,
) -> list[tuple[float, float, float]]:
    front_depth = _profile_value(z, FRONT_DEPTH)
    rear_depth = _profile_value(z, REAR_DEPTH)
    points = []
    for index in range(count):
        angle = 2.0 * math.pi * index / count
        x = centre_x + half_width * math.cos(angle)
        sine = math.sin(angle)
        depth = rear_depth if sine >= 0.0 else front_depth
        y = depth * sine
        points.append((x, y, z))
    return points


def _bridge_closed_rings(mesh, lower: list[int], upper: list[int]) -> None:
    if len(lower) != len(upper):
        raise ValueError("Wide Cargo ring sizes differ")
    count = len(lower)
    for index in range(count):
        next_index = (index + 1) % count
        mesh.faces.append(
            (lower[index], lower[next_index], upper[next_index], upper[index])
        )


def _bridge_chains(mesh, first: list[int], second: list[int]) -> None:
    if len(first) != len(second):
        raise ValueError("Wide Cargo chain sizes differ")
    for index in range(len(first) - 1):
        mesh.faces.append(
            (first[index], first[index + 1], second[index + 1], second[index])
        )


def _ring_chain(ring: list[int], indices: list[int]) -> list[int]:
    return [ring[index] for index in indices]


def _triangulate_fan(mesh, ring: list[int], centre: int) -> None:
    for index in range(len(ring)):
        next_index = (index + 1) % len(ring)
        mesh.faces.append((centre, ring[index], ring[next_index]))


def add_side_pocket_panel(
    mesh,
    *,
    side: float,
    x_base: float,
    y_half: float,
    z_min: float,
    z_max: float,
    corner_radius: float,
) -> None:
    y0 = -y_half
    y1 = y_half
    z0 = z_min
    z1 = z_max
    radius = corner_radius
    yz = [
        (y0 + radius, z0),
        (y1 - radius, z0),
        (y1, z0 + radius),
        (y1, z1 - radius),
        (y1 - radius, z1),
        (y0 + radius, z1),
        (y0, z1 - radius),
        (y0, z0 + radius),
    ]
    points = []
    for y, z in yz:
        y_ratio = min(1.0, abs(y) / y_half)
        z_ratio = min(1.0, abs(z - (z0 + z1) * 0.5) / ((z1 - z0) * 0.5))
        bulge = 0.003 * (1.0 - 0.45 * y_ratio**2) * (1.0 - 0.30 * z_ratio**2)
        points.append((side * (x_base + bulge), y, z))
    panel = mesh.add_ring(points)
    centre = mesh.add_ring([(side * (x_base + 0.003), 0.0, (z0 + z1) * 0.5)])[0]
    oriented = panel if side > 0 else list(reversed(panel))
    _triangulate_fan(mesh, oriented, centre)


def reviewed_geometry(implementation: ModuleType, segments: int = 48):
    """Generate the verified baseline from canonical Wide Cargo pattern data."""
    del segments
    mesh = implementation.MeshBuilder()

    ring_count = 32
    quarter = ring_count // 4
    leg_rows: dict[float, list[list[int]]] = {-1.0: [], 1.0: []}
    for z, outer, inner in LEG_BOUNDARY_ROWS:
        centre = (outer + inner) * 0.5
        half_width = (outer - inner) * 0.5
        for side in (-1.0, 1.0):
            ring = mesh.add_ring(
                _circumferential_points(
                    centre_x=side * centre,
                    half_width=half_width,
                    z=z,
                    count=ring_count,
                )
            )
            leg_rows[side].append(ring)

    for side in (-1.0, 1.0):
        for lower, upper in zip(leg_rows[side], leg_rows[side][1:]):
            _bridge_closed_rings(mesh, lower, upper)

    upper_rows = [
        mesh.add_ring(
            _circumferential_points(
                centre_x=0.0,
                half_width=half_width,
                z=z,
                count=ring_count,
            )
        )
        for z, half_width in UPPER_SPECS
    ]
    for lower, upper in zip(upper_rows, upper_rows[1:]):
        _bridge_closed_rings(mesh, lower, upper)

    first_upper = upper_rows[0]
    right_leg = leg_rows[1.0][-1]
    left_leg = leg_rows[-1.0][-1]

    right_outer_indices = list(range(3 * quarter + 1, ring_count)) + list(
        range(0, quarter)
    )
    right_inner_indices = list(range(quarter, 3 * quarter + 1))
    left_outer_indices = list(range(quarter + 1, 3 * quarter))
    left_inner_indices = list(range(quarter, -1, -1)) + list(
        range(ring_count - 1, 3 * quarter - 1, -1)
    )

    right_outer = _ring_chain(right_leg, right_outer_indices)
    left_outer = _ring_chain(left_leg, left_outer_indices)
    upper_right = _ring_chain(first_upper, right_outer_indices)
    upper_left = _ring_chain(first_upper, left_outer_indices)
    _bridge_chains(mesh, right_outer, upper_right)
    _bridge_chains(mesh, upper_left, left_outer)

    right_inner = _ring_chain(right_leg, right_inner_indices)
    left_inner = _ring_chain(left_leg, left_inner_indices)
    if len(CROTCH_CENTRE) != len(right_inner) or len(CROTCH_CENTRE) != len(left_inner):
        raise ValueError(
            "Wide Cargo crotch pattern point count does not match inner-leg chains"
        )
    centre_crotch_points = [(0.0, y, z) for y, z in CROTCH_CENTRE]
    centre_crotch = mesh.add_ring(centre_crotch_points)
    _bridge_chains(mesh, right_inner, centre_crotch)
    _bridge_chains(mesh, centre_crotch, left_inner)

    rear_upper_right = first_upper[quarter - 1]
    rear_upper_centre = first_upper[quarter]
    rear_upper_left = first_upper[quarter + 1]
    front_upper_left = first_upper[3 * quarter - 1]
    front_upper_centre = first_upper[3 * quarter]
    front_upper_right = first_upper[3 * quarter + 1]

    mesh.faces.append(
        (rear_upper_right, right_outer[-1], right_inner[0], centre_crotch[0])
    )
    mesh.faces.append((rear_upper_right, centre_crotch[0], rear_upper_centre))
    mesh.faces.append((rear_upper_centre, centre_crotch[0], rear_upper_left))
    mesh.faces.append((rear_upper_left, centre_crotch[0], left_inner[0], left_outer[0]))

    mesh.faces.append(
        (front_upper_right, centre_crotch[-1], right_inner[-1], right_outer[0])
    )
    mesh.faces.append((front_upper_right, front_upper_centre, centre_crotch[-1]))
    mesh.faces.append((front_upper_centre, front_upper_left, centre_crotch[-1]))
    mesh.faces.append(
        (front_upper_left, left_outer[-1], left_inner[-1], centre_crotch[-1])
    )

    for side in (-1.0, 1.0):
        add_side_pocket_panel(
            mesh,
            side=side,
            x_base=0.1815,
            y_half=0.032,
            z_min=0.475,
            z_max=0.555,
            corner_radius=0.012,
        )
    return mesh


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

    armature_parent = garment.parent
    checks.update(
        {
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
    manifest["designRevision"] = "v74-centre-crotch-seam"
    manifest["wearabilityAudit"] = report
    gates = manifest.setdefault("technicalGates", {})
    gates["latestGeometryRender"] = "PASS" if report["passed"] else "FAIL"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
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
