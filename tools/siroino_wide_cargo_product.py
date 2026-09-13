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
        "frontRise": front_rise,
        "backRise": back_rise,
        "crotchCentre": back_rise + front_rise[1:],
    }


PATTERN_BASELINE = _load_pattern_baseline()
FRONT_DEPTH = PATTERN_BASELINE["frontDepthProfile"]
REAR_DEPTH = PATTERN_BASELINE["rearDepthProfile"]
LEG_BOUNDARY_ROWS = PATTERN_BASELINE["legBoundaryRows"]
UPPER_SPECS = PATTERN_BASELINE["upperRows"]
FRONT_RISE = PATTERN_BASELINE["frontRise"]
BACK_RISE = PATTERN_BASELINE["backRise"]
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
    value = max(0.0, min(1.0, value))
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


def _rise_value(z: float, points: tuple[tuple[float, float], ...]) -> float:
    by_height = tuple(sorted((height, y) for y, height in points))
    return _profile_value(z, by_height)


def _append_face(mesh, vertices: tuple[int, ...], *, reverse: bool = False) -> None:
    face = tuple(reversed(vertices)) if reverse else vertices
    if len(set(face)) >= 3:
        mesh.faces.append(face)


def _bridge_panel_rows(
    mesh,
    lower: list[int],
    upper: list[int],
    *,
    reverse: bool = False,
) -> None:
    if len(lower) != len(upper):
        raise ValueError("Wide Cargo panel row sizes differ")
    for index in range(len(lower) - 1):
        _append_face(
            mesh,
            (lower[index], lower[index + 1], upper[index + 1], upper[index]),
            reverse=reverse,
        )


def _cross_row(mesh, first: int, second: int, *, segments: int = 4) -> list[int]:
    if first == second:
        return [first]
    if segments < 2:
        raise ValueError("Wide Cargo seam strip needs at least two segments")
    a = mesh.vertices[first]
    b = mesh.vertices[second]
    row = [first]
    for step in range(1, segments):
        t = step / segments
        point = tuple(a[axis] + (b[axis] - a[axis]) * t for axis in range(3))
        row.append(mesh.add_ring([point])[0])
    row.append(second)
    return row


def _bridge_cross_rows(
    mesh,
    lower: list[int],
    upper: list[int],
    *,
    reverse: bool = False,
) -> None:
    if len(lower) == 1 and len(upper) == 1:
        return
    if len(lower) == 1:
        tip = lower[0]
        for index in range(len(upper) - 1):
            _append_face(mesh, (tip, upper[index], upper[index + 1]), reverse=reverse)
        return
    if len(upper) == 1:
        tip = upper[0]
        for index in range(len(lower) - 1):
            _append_face(mesh, (lower[index], lower[index + 1], tip), reverse=reverse)
        return
    _bridge_panel_rows(mesh, lower, upper, reverse=reverse)


def _bridge_seam_strip(
    mesh,
    first: list[int],
    second: list[int],
    *,
    reverse: bool = False,
    segments: int = 4,
) -> None:
    if len(first) != len(second):
        raise ValueError("Wide Cargo seam chain sizes differ")
    rows = [
        _cross_row(mesh, first_index, second_index, segments=segments)
        for first_index, second_index in zip(first, second)
    ]
    for lower, upper in zip(rows, rows[1:]):
        _bridge_cross_rows(mesh, lower, upper, reverse=reverse)


def _inner_seam_factor(z: float, top_z: float) -> float:
    start = 0.440
    if z <= start:
        return 1.0
    if z >= top_z:
        return 0.0
    return 1.0 - _smoothstep((z - start) / (top_z - start))


def _row_specs() -> list[dict[str, float | str]]:
    if not LEG_BOUNDARY_ROWS:
        raise RuntimeError("Wide Cargo pattern has no leg boundary rows")
    specs: list[dict[str, float | str]] = [
        {"phase": "leg", "z": z, "outer": outer, "inner": inner}
        for z, outer, inner in LEG_BOUNDARY_ROWS
    ]
    top_z, top_outer, top_inner = LEG_BOUNDARY_ROWS[-1]
    rise_end = max(max(z for _, z in FRONT_RISE), max(z for _, z in BACK_RISE))
    transition_heights = sorted(
        {
            z
            for _, z in FRONT_RISE + BACK_RISE
            if top_z < z <= rise_end + 1e-9
        }
    )
    target_outer = _profile_value(rise_end, UPPER_SPECS)
    for z in transition_heights:
        t = _smoothstep((z - top_z) / (rise_end - top_z))
        specs.append(
            {
                "phase": "transition",
                "z": z,
                "outer": top_outer + (target_outer - top_outer) * t,
                "inner": top_inner * (1.0 - t),
            }
        )
    for z, half_width in UPPER_SPECS:
        if z > rise_end + 1e-9:
            specs.append(
                {"phase": "upper", "z": z, "outer": half_width, "inner": 0.0}
            )
    specs.sort(key=lambda row: float(row["z"]))
    return specs


def _panel_y(
    *,
    face: str,
    phase: str,
    z: float,
    x: float,
    outer: float,
    t: float,
    top_z: float,
) -> float:
    front = face == "front"
    profile = FRONT_DEPTH if front else REAR_DEPTH
    sign = -1.0 if front else 1.0
    depth = _profile_value(z, profile)
    x_ratio = min(1.0, abs(x) / max(outer, 1e-9))
    curved_depth = depth * (0.88 + 0.12 * (1.0 - x_ratio**2))
    if phase == "leg":
        inner_factor = _inner_seam_factor(z, top_z)
        local_t = _smoothstep(min(1.0, t / 0.25))
        seam_factor = inner_factor + (1.0 - inner_factor) * local_t
        return sign * curved_depth * seam_factor
    if phase == "transition":
        rise = FRONT_RISE if front else BACK_RISE
        centre_y = _rise_value(z, rise)
        outer_y = sign * depth * 0.88
        return centre_y + (outer_y - centre_y) * _smoothstep(t)
    return sign * curved_depth


def _panel_grid(
    mesh,
    specs: list[dict[str, float | str]],
    *,
    face: str,
    side: float,
    columns: int,
    shared: dict[tuple[object, ...], int],
) -> list[list[int]]:
    top_z = float(LEG_BOUNDARY_ROWS[-1][0])
    rows: list[list[int]] = []
    for spec in specs:
        phase = str(spec["phase"])
        z = float(spec["z"])
        outer = float(spec["outer"])
        inner = float(spec["inner"])
        row: list[int] = []
        for column in range(columns):
            t = column / (columns - 1)
            x_abs = inner + (outer - inner) * t
            x = side * x_abs
            y = _panel_y(
                face=face,
                phase=phase,
                z=z,
                x=x,
                outer=outer,
                t=t,
                top_z=top_z,
            )
            key: tuple[object, ...] | None = None
            if column == 0 and inner <= 1e-9:
                key = ("centre", face, round(z, 6))
            elif column == 0 and phase == "leg" and abs(z - top_z) <= 1e-9:
                key = ("crotch-tip", side, round(z, 6))
            if key is not None and key in shared:
                index = shared[key]
            else:
                index = mesh.add_ring([(x, y, z)])[0]
                if key is not None:
                    shared[key] = index
            row.append(index)
        rows.append(row)
    return rows


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
    """Build four sewn pattern surfaces instead of legacy closed-ring transitions."""
    del segments
    mesh = implementation.MeshBuilder()
    specs = _row_specs()
    columns = 6
    shared: dict[tuple[object, ...], int] = {}
    grids: dict[tuple[str, float], list[list[int]]] = {}

    for face in ("front", "back"):
        for side in (-1.0, 1.0):
            grid = _panel_grid(
                mesh,
                specs,
                face=face,
                side=side,
                columns=columns,
                shared=shared,
            )
            grids[(face, side)] = grid
            reverse = (face == "front" and side < 0.0) or (
                face == "back" and side > 0.0
            )
            for lower, upper in zip(grid, grid[1:]):
                _bridge_panel_rows(mesh, lower, upper, reverse=reverse)

    for side in (-1.0, 1.0):
        front_outer = [row[-1] for row in grids[("front", side)]]
        back_outer = [row[-1] for row in grids[("back", side)]]
        _bridge_seam_strip(
            mesh,
            front_outer,
            back_outer,
            reverse=side < 0.0,
            segments=4,
        )

        crotch_end = max(
            index
            for index, spec in enumerate(specs)
            if float(spec["z"]) <= 0.6000001
        )
        front_inner = [row[0] for row in grids[("front", side)][: crotch_end + 1]]
        back_inner = [row[0] for row in grids[("back", side)][: crotch_end + 1]]
        _bridge_seam_strip(
            mesh,
            front_inner,
            back_inner,
            reverse=side > 0.0,
            segments=4,
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
    manifest["designRevision"] = "v75-pattern-panel-surface"
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
