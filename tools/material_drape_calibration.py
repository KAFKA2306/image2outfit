#!/usr/bin/env python3
"""Calibrate Blender 4.4 cloth against a collision-supported Cusick fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

import bpy
import numpy as np
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from image2outfit.material import MaterialSpec, load_material_library  # noqa: E402
from image2outfit.material_blender import (  # noqa: E402
    BlenderCalibrationProfile,
    BlenderMaterialProjection,
    blender_collider_friction_percent,
    load_blender_calibration_profile,
    project_material_library_to_blender,
)

SPECIMEN_RADIUS_M = 0.15
SUPPORT_RADIUS_M = 0.09
SUPPORT_TOP_Z_M = 0.12
INITIAL_SPECIMEN_Z_M = 0.125
MIN_COLLISION_DISTANCE_M = 0.001
RASTER_RESOLUTION = 512
RENDER_SUBDIVISION_LEVELS = 2
CONVERGENCE_CHECKPOINTS = (100, 150, 200, 250)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--library",
        type=Path,
        default=Path("config/materials/kes-woven-fabrics-2025.v1.json"),
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path("config/materials/blender-4.4-kes-calibration.v1.json"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path(".image2outfit/material-calibration")
    )
    parser.add_argument("--frame-end", type=int, default=250)
    parser.add_argument("--grid", type=int, default=41)
    return parser.parse_args(argv)


def blender_arguments() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def clean_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in tuple(bpy.data.collections):
        if collection.name != "Collection":
            bpy.data.collections.remove(collection)
    for datablocks in (
        bpy.data.meshes,
        bpy.data.materials,
        bpy.data.curves,
        bpy.data.cameras,
        bpy.data.lights,
    ):
        for datablock in tuple(datablocks):
            if datablock.users == 0:
                datablocks.remove(datablock)


def specimen_positions() -> tuple[tuple[float, float], ...]:
    return (
        (-0.42, 0.25),
        (0.0, 0.25),
        (0.42, 0.25),
        (-0.42, -0.25),
        (0.0, -0.25),
        (0.42, -0.25),
    )


def disk_mesh(name: str, radius: float, count: int) -> bpy.types.Mesh:
    if count < 21 or count % 2 == 0:
        raise ValueError("disk grid must be an odd integer of at least 21")
    vertices: list[tuple[float, float, float]] = []
    for row in range(count):
        v = -1.0 + 2.0 * row / (count - 1)
        for column in range(count):
            u = -1.0 + 2.0 * column / (count - 1)
            x = radius * u * math.sqrt(max(0.0, 1.0 - v * v / 2.0))
            y = radius * v * math.sqrt(max(0.0, 1.0 - u * u / 2.0))
            vertices.append((x, y, 0.0))
    faces: list[tuple[int, int, int, int]] = []
    for row in range(count - 1):
        for column in range(count - 1):
            first = row * count + column
            faces.append((first, first + 1, first + count + 1, first + count))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    return mesh


def set_properties(owner: Any, values: Mapping[str, Any], label: str) -> dict[str, Any]:
    actual: dict[str, Any] = {}
    for name, value in values.items():
        if not hasattr(owner, name):
            raise RuntimeError(f"Blender 4.4 property missing: {label}.{name}")
        setattr(owner, name, value)
        stored = getattr(owner, name)
        actual[name] = (
            bool(stored)
            if isinstance(value, bool)
            else int(stored)
            if isinstance(value, int)
            else str(stored)
            if isinstance(value, str)
            else float(stored)
        )
    return actual


def dark_material(name: str) -> bpy.types.Material:
    material = bpy.data.materials.new(name)
    material.diffuse_color = (0.08, 0.09, 0.12, 1.0)
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    if principled is not None:
        principled.inputs["Base Color"].default_value = (0.08, 0.09, 0.12, 1.0)
        principled.inputs["Roughness"].default_value = 0.58
    return material


def cloth_material(name: str, index: int, total: int) -> bpy.types.Material:
    hue = index / max(total, 1)
    red = 0.35 + 0.45 * abs(math.sin(hue * math.tau))
    green = 0.35 + 0.45 * abs(math.sin((hue + 1 / 3) * math.tau))
    blue = 0.35 + 0.45 * abs(math.sin((hue + 2 / 3) * math.tau))
    material = bpy.data.materials.new(name)
    material.diffuse_color = (red, green, blue, 1.0)
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    if principled is not None:
        principled.inputs["Base Color"].default_value = (red, green, blue, 1.0)
        principled.inputs["Roughness"].default_value = 0.72
    return material


def add_collision(
    obj: bpy.types.Object, settings: Mapping[str, float]
) -> dict[str, Any]:
    obj.modifiers.new(name="Collision", type="COLLISION")
    if obj.collision is None:
        raise RuntimeError("Collision modifier did not expose Object.collision")
    return set_properties(obj.collision, settings, f"{obj.name}.collision")


def create_floor(profile: BlenderCalibrationProfile) -> dict[str, Any]:
    bpy.ops.mesh.primitive_plane_add(size=4.0, location=(0.0, 0.0, 0.0))
    floor = bpy.context.object
    floor.name = "CalibrationFloor"
    floor.data.materials.append(dark_material("FloorMaterial"))
    return add_collision(
        floor,
        {
            "cloth_friction": blender_collider_friction_percent(
                profile.contact.static_friction
            ),
            "thickness_outer": MIN_COLLISION_DISTANCE_M,
        },
    )


def create_support(
    projection: BlenderMaterialProjection,
    position: tuple[float, float],
    collection: bpy.types.Collection,
    render_material: bool,
) -> tuple[bpy.types.Object, dict[str, Any]]:
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=64,
        radius=SUPPORT_RADIUS_M,
        depth=SUPPORT_TOP_Z_M,
        location=(position[0], position[1], SUPPORT_TOP_Z_M / 2.0),
    )
    support = bpy.context.object
    support.name = f"Support__{projection.material_id}"
    for source in tuple(support.users_collection):
        source.objects.unlink(support)
    collection.objects.link(support)
    if render_material:
        support.data.materials.append(
            dark_material(f"SupportMaterial__{projection.material_id}")
        )
    return support, add_collision(
        support,
        {
            "cloth_friction": float(projection.collider_settings["cloth_friction"]),
            "thickness_outer": max(
                projection.collision_thickness_m, MIN_COLLISION_DISTANCE_M
            ),
        },
    )


def scaled_cloth_settings(
    projection: BlenderMaterialProjection, elastic_scale: float
) -> dict[str, float | int]:
    values = dict(projection.cloth_settings)
    for name in (
        "tension_stiffness",
        "compression_stiffness",
        "shear_stiffness",
        "bending_stiffness",
    ):
        values[name] = float(values[name]) * elastic_scale
    return values


def create_cloth(
    projection: BlenderMaterialProjection,
    position: tuple[float, float],
    collection: bpy.types.Collection,
    grid_count: int,
    frame_end: int,
    elastic_scale: float,
    index: int,
    total: int,
    render_material: bool,
) -> tuple[bpy.types.Object, dict[str, Any]]:
    mesh = disk_mesh(f"Mesh__{projection.material_id}", SPECIMEN_RADIUS_M, grid_count)
    cloth = bpy.data.objects.new(f"Cloth__{projection.material_id}", mesh)
    cloth.location = (position[0], position[1], INITIAL_SPECIMEN_Z_M)
    collection.objects.link(cloth)
    if render_material:
        cloth.data.materials.append(cloth_material(cloth.name, index, total))

    modifier = cloth.modifiers.new(name="Cloth", type="CLOTH")
    surface_area = math.pi * SPECIMEN_RADIUS_M**2
    cloth_values = scaled_cloth_settings(projection, elastic_scale)
    cloth_values["mass"] = projection.vertex_mass_kg(surface_area, len(mesh.vertices))
    actual_cloth = set_properties(
        modifier.settings, cloth_values, f"{cloth.name}.settings"
    )
    collision_values = dict(projection.cloth_collision_settings)
    collision_values.update(
        {
            "distance_min": max(
                projection.collision_thickness_m, MIN_COLLISION_DISTANCE_M
            ),
            "use_self_collision": False,
            "self_distance_min": max(
                projection.collision_thickness_m, MIN_COLLISION_DISTANCE_M
            ),
        }
    )
    actual_collision = set_properties(
        modifier.collision_settings,
        collision_values,
        f"{cloth.name}.collision_settings",
    )
    modifier.point_cache.frame_start = 1
    modifier.point_cache.frame_end = frame_end

    if render_material:
        subdivision = cloth.modifiers.new(name="RenderSubdivision", type="SUBSURF")
        subdivision.subdivision_type = "CATMULL_CLARK"
        subdivision.levels = RENDER_SUBDIVISION_LEVELS
        subdivision.render_levels = RENDER_SUBDIVISION_LEVELS
        solidify = cloth.modifiers.new(name="RenderThickness", type="SOLIDIFY")
        solidify.thickness = projection.render_thickness_m
        solidify.offset = 0.0

    return cloth, {
        "surfaceAreaM2": surface_area,
        "vertexCount": len(mesh.vertices),
        "pinnedVertexCount": 0,
        "pinGroup": None,
        "supportBoundaryCondition": "collision-supported-free-fall",
        "initialGapM": INITIAL_SPECIMEN_Z_M - SUPPORT_TOP_Z_M,
        "elasticScale": elastic_scale,
        "clothSettings": actual_cloth,
        "clothCollisionSettings": actual_collision,
        "renderSubdivisionLevels": (
            RENDER_SUBDIVISION_LEVELS if render_material else 0
        ),
        "selfCollisionDisabledReason": (
            "fabric-fabric friction is not measured in the source library"
        ),
    }


def triangle_mask(
    mask: np.ndarray,
    triangle: np.ndarray,
    lower: float,
    upper: float,
) -> None:
    resolution = mask.shape[0]
    scale = (resolution - 1) / (upper - lower)
    pixels = (triangle - lower) * scale
    min_x = max(0, int(math.floor(float(np.min(pixels[:, 0])))))
    max_x = min(resolution - 1, int(math.ceil(float(np.max(pixels[:, 0])))))
    min_y = max(0, int(math.floor(float(np.min(pixels[:, 1])))))
    max_y = min(resolution - 1, int(math.ceil(float(np.max(pixels[:, 1])))))
    if min_x > max_x or min_y > max_y:
        return
    x_values = np.arange(min_x, max_x + 1, dtype=np.float64) + 0.5
    y_values = np.arange(min_y, max_y + 1, dtype=np.float64) + 0.5
    grid_x, grid_y = np.meshgrid(x_values, y_values)
    first, second, third = pixels
    denominator = (second[1] - third[1]) * (first[0] - third[0]) + (
        third[0] - second[0]
    ) * (first[1] - third[1])
    if math.isclose(float(denominator), 0.0):
        return
    alpha = (
        (second[1] - third[1]) * (grid_x - third[0])
        + (third[0] - second[0]) * (grid_y - third[1])
    ) / denominator
    beta = (
        (third[1] - first[1]) * (grid_x - third[0])
        + (first[0] - third[0]) * (grid_y - third[1])
    ) / denominator
    gamma = 1.0 - alpha - beta
    mask[min_y : max_y + 1, min_x : max_x + 1] |= (
        (alpha >= -1e-9) & (beta >= -1e-9) & (gamma >= -1e-9)
    )


def silhouette_area(
    coordinates: list[Vector],
    polygons: list[tuple[int, ...]],
    location: Vector,
) -> float:
    lower = -SPECIMEN_RADIUS_M * 1.15
    upper = SPECIMEN_RADIUS_M * 1.15
    mask = np.zeros((RASTER_RESOLUTION, RASTER_RESOLUTION), dtype=bool)
    points = np.array(
        [[value.x - location.x, value.y - location.y] for value in coordinates],
        dtype=np.float64,
    )
    for polygon in polygons:
        for index in range(1, len(polygon) - 1):
            triangle_mask(
                mask,
                points[[polygon[0], polygon[index], polygon[index + 1]]],
                lower,
                upper,
            )
    pixel_size = (upper - lower) / RASTER_RESOLUTION
    return float(np.count_nonzero(mask)) * pixel_size**2


def evaluated_geometry(
    cloth: bpy.types.Object,
) -> tuple[list[Vector], list[tuple[int, ...]]]:
    render_only = [
        modifier
        for modifier in cloth.modifiers
        if modifier.name in {"RenderSubdivision", "RenderThickness"}
    ]
    visible = [(modifier, modifier.show_viewport) for modifier in render_only]
    for modifier, _ in visible:
        modifier.show_viewport = False
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = cloth.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            coordinates = [
                evaluated.matrix_world @ vertex.co for vertex in mesh.vertices
            ]
            polygons = [tuple(polygon.vertices) for polygon in mesh.polygons]
        finally:
            evaluated.to_mesh_clear()
    finally:
        for modifier, was_visible in visible:
            modifier.show_viewport = was_visible
    return coordinates, polygons


def drape_metrics(cloth: bpy.types.Object) -> dict[str, float | str]:
    coordinates, polygons = evaluated_geometry(cloth)
    z_values = [value.z for value in coordinates]
    footprint = silhouette_area(coordinates, polygons, cloth.location)
    support_area = math.pi * SUPPORT_RADIUS_M**2
    specimen_area = math.pi * SPECIMEN_RADIUS_M**2
    coefficient = (footprint - support_area) / (specimen_area - support_area)
    local_xy = [
        (value.x - cloth.location.x, value.y - cloth.location.y)
        for value in coordinates
    ]
    center_offset = math.hypot(
        statistics.fmean(value[0] for value in local_xy),
        statistics.fmean(value[1] for value in local_xy),
    )
    support_z = [
        coordinate.z
        for coordinate, (x_value, y_value) in zip(coordinates, local_xy, strict=True)
        if math.hypot(x_value, y_value) <= SUPPORT_RADIUS_M * 0.9
    ]
    expected_contact_z = SUPPORT_TOP_Z_M + 2 * MIN_COLLISION_DISTANCE_M
    contact_fraction = (
        statistics.fmean(
            1.0 if abs(value - expected_contact_z) <= 0.006 else 0.0
            for value in support_z
        )
        if support_z
        else 0.0
    )
    rounded = "\n".join(
        f"{value.x:.7f},{value.y:.7f},{value.z:.7f}" for value in coordinates
    ).encode("utf-8")
    return {
        "minimumZ": min(z_values),
        "maximumZ": max(z_values),
        "verticalRange": max(z_values) - min(z_values),
        "meanZ": statistics.fmean(z_values),
        "standardDeviationZ": statistics.pstdev(z_values),
        "footprintAreaM2": footprint,
        "cusickDrapeCoefficient": coefficient,
        "centerOffsetM": center_offset,
        "supportContactFraction": contact_fraction,
        "supportRegionMinimumZ": min(support_z) if support_z else math.nan,
        "supportRegionMaximumZ": max(support_z) if support_z else math.nan,
        "vertexSha256": hashlib.sha256(rounded).hexdigest(),
    }


def temporal_convergence_report(
    snapshots: Mapping[str, list[dict[str, Any]]],
    thresholds: Mapping[str, float],
) -> dict[str, Any]:
    required = {
        "maximumCoefficientDelta",
        "maximumSupportContactDelta",
        "maximumMaximumZDeltaM",
        "maximumMeanVertexDisplacementM",
        "maximumVertexDisplacementM",
    }
    if set(thresholds) != required:
        raise ValueError("temporalConvergence must define the exact threshold set")
    parsed = {name: float(thresholds[name]) for name in sorted(required)}
    if any(not math.isfinite(value) or value < 0 for value in parsed.values()):
        raise ValueError(
            "temporal convergence thresholds must be finite and non-negative"
        )

    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for material_id, states in snapshots.items():
        if len(states) < 2:
            raise ValueError(f"at least two checkpoints are required for {material_id}")
        previous = states[-2]
        current = states[-1]
        previous_coordinates = previous["coordinates"]
        current_coordinates = current["coordinates"]
        if len(previous_coordinates) != len(current_coordinates):
            raise RuntimeError(f"checkpoint topology changed for {material_id}")
        displacements = [
            float((right - left).length)
            for left, right in zip(
                previous_coordinates, current_coordinates, strict=True
            )
        ]
        deltas = {
            "coefficientDelta": abs(
                float(current["metrics"]["cusickDrapeCoefficient"])
                - float(previous["metrics"]["cusickDrapeCoefficient"])
            ),
            "supportContactDelta": abs(
                float(current["metrics"]["supportContactFraction"])
                - float(previous["metrics"]["supportContactFraction"])
            ),
            "maximumZDeltaM": abs(
                float(current["metrics"]["maximumZ"])
                - float(previous["metrics"]["maximumZ"])
            ),
            "meanVertexDisplacementM": statistics.fmean(displacements),
            "maximumVertexDisplacementM": max(displacements),
        }
        errors: list[str] = []
        checks = (
            (
                "coefficient-drift",
                deltas["coefficientDelta"],
                parsed["maximumCoefficientDelta"],
            ),
            (
                "support-contact-drift",
                deltas["supportContactDelta"],
                parsed["maximumSupportContactDelta"],
            ),
            (
                "maximum-z-drift",
                deltas["maximumZDeltaM"],
                parsed["maximumMaximumZDeltaM"],
            ),
            (
                "mean-geometry-drift",
                deltas["meanVertexDisplacementM"],
                parsed["maximumMeanVertexDisplacementM"],
            ),
            (
                "maximum-geometry-drift",
                deltas["maximumVertexDisplacementM"],
                parsed["maximumVertexDisplacementM"],
            ),
        )
        for name, value, limit in checks:
            if value > limit:
                errors.append(name)
        public_states = [
            {
                "frame": int(state["frame"]),
                "metrics": state["metrics"],
            }
            for state in states
        ]
        record = {
            "materialId": material_id,
            "checkpoints": public_states,
            "finalInterval": {
                "fromFrame": int(previous["frame"]),
                "toFrame": int(current["frame"]),
                **deltas,
                "errors": errors,
                "passed": not errors,
            },
        }
        records.append(record)
        if errors:
            failures.append({"materialId": material_id, "errors": errors})
    return {
        "checkpointFrames": [
            int(item["frame"]) for item in next(iter(snapshots.values()))
        ],
        "thresholds": parsed,
        "records": records,
        "failures": failures,
        "passed": not failures,
    }


def plausibility_errors(metrics: Mapping[str, float | str]) -> list[str]:
    errors: list[str] = []
    coefficient = float(metrics["cusickDrapeCoefficient"])
    if not -0.03 <= coefficient <= 1.03:
        errors.append("drape-coefficient-out-of-range")
    if float(metrics["minimumZ"]) < -0.005:
        errors.append("below-floor")
    if float(metrics["maximumZ"]) > INITIAL_SPECIMEN_Z_M + 0.05:
        errors.append("gross-upward-instability")
    if float(metrics["verticalRange"]) < 0.01:
        errors.append("no-gravity-response")
    if float(metrics["centerOffsetM"]) > 0.03:
        errors.append("excessive-horizontal-drift")
    if float(metrics["supportContactFraction"]) < 0.1:
        errors.append("no-support-contact")
    return errors


def plausibility_warnings(metrics: Mapping[str, float | str]) -> list[str]:
    warnings: list[str] = []
    if float(metrics["supportContactFraction"]) < 0.5:
        warnings.append("limited-support-contact")
    if float(metrics["centerOffsetM"]) > 0.01:
        warnings.append("minor-horizontal-drift")
    return warnings


def pearson(first: list[float], second: list[float]) -> float:
    first_mean = statistics.fmean(first)
    second_mean = statistics.fmean(second)
    numerator = sum(
        (left - first_mean) * (right - second_mean)
        for left, right in zip(first, second, strict=True)
    )
    first_scale = math.sqrt(sum((value - first_mean) ** 2 for value in first))
    second_scale = math.sqrt(sum((value - second_mean) ** 2 for value in second))
    if math.isclose(first_scale, 0.0) or math.isclose(second_scale, 0.0):
        return 0.0
    return numerator / (first_scale * second_scale)


def comparison_metrics(
    records: list[dict[str, Any]],
    targets: Mapping[str, float],
) -> dict[str, Any]:
    simulated = [float(item["metrics"]["cusickDrapeCoefficient"]) for item in records]
    published = [float(targets[item["materialId"]]) for item in records]
    real = [float(item["realDrapeCoefficient"]) for item in records]
    errors = [left - right for left, right in zip(simulated, published, strict=True)]
    failures = [
        {"materialId": item["materialId"], "errors": item["plausibilityErrors"]}
        for item in records
        if item["plausibilityErrors"]
    ]
    return {
        "rmseVsPublishedKes": math.sqrt(
            statistics.fmean(value * value for value in errors)
        ),
        "maximumAbsoluteErrorVsPublishedKes": max(abs(value) for value in errors),
        "pearsonVsPublishedKes": pearson(published, simulated),
        "pearsonVsReal": pearson(real, simulated),
        "plausibilityFailures": failures,
    }


def objective(comparison: Mapping[str, Any]) -> float:
    return (
        float(comparison["rmseVsPublishedKes"])
        + 0.5 * max(0.0, 0.7 - float(comparison["pearsonVsPublishedKes"]))
        + 0.5 * max(0.0, 0.65 - float(comparison["pearsonVsReal"]))
        + 10.0 * len(comparison["plausibilityFailures"])
    )


def simulate(
    materials: tuple[MaterialSpec, ...],
    projections: tuple[BlenderMaterialProjection, ...],
    profile: BlenderCalibrationProfile,
    *,
    elastic_scales: Mapping[str, float],
    grid_count: int,
    frame_end: int,
    render_materials: bool,
    convergence_thresholds: Mapping[str, float],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    clean_scene()
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = frame_end
    scene.render.fps = 30
    floor_settings = create_floor(profile)
    records: list[dict[str, Any]] = []
    expected_material_ids = {material.material_id for material in materials}
    if set(elastic_scales) != expected_material_ids:
        raise ValueError("elastic scales must cover every material exactly")
    for index, (material, projection, position) in enumerate(
        zip(materials, projections, specimen_positions(), strict=True)
    ):
        elastic_scale = float(elastic_scales[material.material_id])
        if not math.isfinite(elastic_scale) or elastic_scale <= 0:
            raise ValueError(
                f"invalid elastic scale for {material.material_id}: {elastic_scale}"
            )
        collection = bpy.data.collections.new(f"Test__{projection.material_id}")
        scene.collection.children.link(collection)
        support, support_settings = create_support(
            projection, position, collection, render_materials
        )
        cloth, runtime = create_cloth(
            projection,
            position,
            collection,
            grid_count,
            frame_end,
            elastic_scale,
            index,
            len(projections),
            render_materials,
        )
        records.append(
            {
                "materialId": material.material_id,
                "position": list(position),
                "realDrapeCoefficient": material.real_drape_coefficient,
                "projection": projection.to_dict(),
                "projectionSha256": projection.fingerprint(),
                "runtime": {
                    **runtime,
                    "clothObject": cloth.name,
                    "supportObject": support.name,
                    "supportCollisionSettings": support_settings,
                },
            }
        )
    checkpoint_frames = tuple(
        frame for frame in CONVERGENCE_CHECKPOINTS if frame <= frame_end
    )
    if len(checkpoint_frames) < 2 or checkpoint_frames[-1] != frame_end:
        raise ValueError(
            "frame-end must equal a convergence checkpoint and include at least two checkpoints"
        )
    snapshots: dict[str, list[dict[str, Any]]] = {
        record["materialId"]: [] for record in records
    }
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        if frame in checkpoint_frames:
            for record in records:
                cloth = bpy.data.objects[record["runtime"]["clothObject"]]
                coordinates, _ = evaluated_geometry(cloth)
                snapshots[record["materialId"]].append(
                    {
                        "frame": frame,
                        "metrics": drape_metrics(cloth),
                        "coordinates": coordinates,
                    }
                )
    scene.frame_set(scene.frame_end)
    bpy.context.view_layer.update()
    for record in records:
        metrics = snapshots[record["materialId"]][-1]["metrics"]
        record["metrics"] = metrics
        record["plausibilityErrors"] = plausibility_errors(metrics)
        record["plausibilityWarnings"] = plausibility_warnings(metrics)
    convergence = temporal_convergence_report(snapshots, convergence_thresholds)
    return records, floor_settings, convergence


def look_at(obj: bpy.types.Object, target: Vector) -> None:
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def configure_render(scene: bpy.types.Scene) -> bpy.types.Object:
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.film_transparent = False
    scene.world.color = (0.008, 0.01, 0.015)
    bpy.ops.object.camera_add(location=(0.0, -1.5, 0.8))
    camera = bpy.context.object
    camera.name = "CalibrationCamera"
    camera.data.type = "ORTHO"
    scene.camera = camera
    bpy.ops.object.light_add(type="AREA", location=(0.0, -0.3, 1.3))
    key = bpy.context.object
    key.data.energy = 80
    key.data.size = 1.8
    look_at(key, Vector((0.0, 0.0, 0.08)))
    bpy.ops.object.light_add(type="AREA", location=(0.0, 0.8, 0.7))
    fill = bpy.context.object
    fill.data.energy = 35
    fill.data.size = 1.5
    look_at(fill, Vector((0.0, 0.0, 0.08)))
    return camera


def render_image(
    scene: bpy.types.Scene,
    camera: bpy.types.Object,
    path: Path,
    *,
    location: tuple[float, float, float],
    target: tuple[float, float, float],
    ortho_scale: float,
    resolution: tuple[int, int],
) -> dict[str, str]:
    camera.location = location
    camera.data.ortho_scale = ortho_scale
    look_at(camera, Vector(target))
    scene.render.resolution_x, scene.render.resolution_y = resolution
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    return {"path": path.name, "sha256": sha256(path)}


def render_evidence(
    output: Path, records: list[dict[str, Any]]
) -> list[dict[str, str]]:
    scene = bpy.context.scene
    camera = configure_render(scene)
    images: list[dict[str, str]] = []
    top = render_image(
        scene,
        camera,
        output / "comparison-top.png",
        location=(0.0, 0.0, 2.0),
        target=(0.0, 0.0, 0.0),
        ortho_scale=1.35,
        resolution=(1440, 720),
    )
    images.append({"kind": "comparison-top", **top})
    oblique = render_image(
        scene,
        camera,
        output / "comparison-oblique.png",
        location=(0.0, -1.5, 0.75),
        target=(0.0, 0.0, 0.08),
        ortho_scale=1.35,
        resolution=(1440, 720),
    )
    images.append({"kind": "comparison-oblique", **oblique})
    test_objects = [
        obj for obj in bpy.data.objects if obj.name.startswith(("Cloth__", "Support__"))
    ]
    for record in records:
        material_id = record["materialId"]
        for obj in test_objects:
            obj.hide_render = not obj.name.endswith(material_id)
        x_value, y_value = record["position"]
        individual = render_image(
            scene,
            camera,
            output / f"{material_id}.png",
            location=(x_value, y_value - 0.55, 0.32),
            target=(x_value, y_value, 0.085),
            ortho_scale=0.42,
            resolution=(640, 640),
        )
        images.append(
            {"kind": "material-oblique", "materialId": material_id, **individual}
        )
    for obj in test_objects:
        obj.hide_render = False
    return images


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.frame_end < 60:
        raise SystemExit("frame-end must be at least 60")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    library_path = args.library.resolve()
    profile_path = args.profile.resolve()
    raw_profile = json.loads(profile_path.read_text(encoding="utf-8"))
    materials = load_material_library(library_path)
    profile = load_blender_calibration_profile(profile_path)
    projections = project_material_library_to_blender(materials, profile)
    actual_version = ".".join(str(value) for value in bpy.app.version)
    if actual_version != profile.blender_version:
        raise RuntimeError(
            f"Blender version mismatch: expected {profile.blender_version}, got {actual_version}"
        )
    targets = {
        str(key): float(value)
        for key, value in raw_profile["publishedKesSimulationDrapeCoefficients"].items()
    }
    if set(targets) != {material.material_id for material in materials}:
        raise ValueError("published KES calibration targets must cover every material")
    fixed_scales = raw_profile.get("diagnosticElasticScales")
    search: list[dict[str, Any]] = []
    material_selection: list[dict[str, Any]] = []
    if isinstance(fixed_scales, Mapping):
        selected_scales = {
            material.material_id: float(fixed_scales[material.material_id])
            for material in materials
        }
    else:
        scales = [float(value) for value in raw_profile["elasticScaleSearch"]]
        if not scales or any(
            not math.isfinite(value) or value <= 0 for value in scales
        ):
            raise ValueError("elasticScaleSearch must contain positive finite values")
        evaluations: list[tuple[float, list[dict[str, Any]]]] = []
        for scale in scales:
            common_scales = {material.material_id: scale for material in materials}
            candidate_records, _, _ = simulate(
                materials,
                projections,
                profile,
                elastic_scales=common_scales,
                grid_count=args.grid,
                frame_end=args.frame_end,
                render_materials=False,
                convergence_thresholds=raw_profile["temporalConvergence"],
            )
            candidate_comparison = comparison_metrics(candidate_records, targets)
            material_results = {
                item["materialId"]: {
                    "coefficient": item["metrics"]["cusickDrapeCoefficient"],
                    "absoluteError": abs(
                        float(item["metrics"]["cusickDrapeCoefficient"])
                        - targets[item["materialId"]]
                    ),
                    "plausibilityErrors": item["plausibilityErrors"],
                    "plausibilityWarnings": item["plausibilityWarnings"],
                }
                for item in candidate_records
            }
            search.append(
                {
                    "elasticScale": scale,
                    "comparison": candidate_comparison,
                    "materialResults": material_results,
                }
            )
            evaluations.append((scale, candidate_records))

        selected_scales: dict[str, float] = {}
        for material in materials:
            candidates: list[dict[str, Any]] = []
            for scale, candidate_records in evaluations:
                record = next(
                    item
                    for item in candidate_records
                    if item["materialId"] == material.material_id
                )
                coefficient = float(record["metrics"]["cusickDrapeCoefficient"])
                absolute_error = abs(coefficient - targets[material.material_id])
                candidates.append(
                    {
                        "elasticScale": scale,
                        "coefficient": coefficient,
                        "absoluteError": absolute_error,
                        "plausibilityErrors": record["plausibilityErrors"],
                        "score": absolute_error
                        + 10.0 * len(record["plausibilityErrors"]),
                    }
                )
            selected = min(
                candidates,
                key=lambda item: (
                    item["score"],
                    item["absoluteError"],
                    item["elasticScale"],
                ),
            )
            selected_scales[material.material_id] = float(selected["elasticScale"])
            material_selection.append(
                {
                    "materialId": material.material_id,
                    "targetCoefficient": targets[material.material_id],
                    **selected,
                }
            )

    records, floor_settings, temporal_convergence = simulate(
        materials,
        projections,
        profile,
        elastic_scales=selected_scales,
        grid_count=args.grid,
        frame_end=args.frame_end,
        render_materials=True,
        convergence_thresholds=raw_profile["temporalConvergence"],
    )
    comparison = comparison_metrics(records, targets)
    acceptance = raw_profile["acceptance"]
    passed = (
        temporal_convergence["passed"]
        and not comparison["plausibilityFailures"]
        and comparison["rmseVsPublishedKes"]
        <= float(acceptance["maximumRmseVsPublishedKes"])
        and comparison["pearsonVsPublishedKes"]
        >= float(acceptance["minimumPearsonVsPublishedKes"])
        and comparison["pearsonVsReal"] >= float(acceptance["minimumPearsonVsReal"])
        and comparison["maximumAbsoluteErrorVsPublishedKes"]
        <= float(acceptance["maximumMaterialAbsoluteError"])
    )
    images = render_evidence(output, records)
    blend_path = output / "material-drape-calibration.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)
    report = {
        "schemaVersion": 6,
        "phase": "material-drape-calibration",
        "blenderVersion": actual_version,
        "library": {
            "path": library_path.relative_to(ROOT).as_posix(),
            "sha256": sha256(library_path),
        },
        "profile": {
            "path": profile_path.relative_to(ROOT).as_posix(),
            "sha256": sha256(profile_path),
            "profileId": profile.profile_id,
        },
        "fixture": {
            "type": "cusick-drape-meter",
            "specimenRadiusM": SPECIMEN_RADIUS_M,
            "supportRadiusM": SUPPORT_RADIUS_M,
            "supportTopZM": SUPPORT_TOP_Z_M,
            "initialSpecimenZM": INITIAL_SPECIMEN_Z_M,
            "initialGapM": INITIAL_SPECIMEN_Z_M - SUPPORT_TOP_Z_M,
            "supportBoundaryCondition": "collision-supported-free-fall",
            "pinnedVertexCount": 0,
            "grid": args.grid,
            "topology": "concentric-square-to-disk-quads",
            "rasterResolution": RASTER_RESOLUTION,
            "floorCollisionSettings": floor_settings,
            "renderSubdivisionLevels": RENDER_SUBDIVISION_LEVELS,
            "metricGeometry": "simulation mesh excluding render-only modifiers",
            "sources": [
                "https://doi.org/10.3390/su17041388",
                "https://doi.org/10.3390/ma14216259",
            ],
        },
        "frameEnd": args.frame_end,
        "sameGeometryForAllMaterials": True,
        "sequentialFrameEvaluation": True,
        "calibrationSearch": search,
        "selectedDiagnosticElasticScales": selected_scales,
        "elasticScaleStatus": "diagnostic-until-temporal-convergence-passes",
        "temporalConvergence": temporal_convergence,
        "materialCalibrationSelection": material_selection,
        "records": records,
        "comparison": {**comparison, "acceptance": acceptance, "passed": passed},
        "images": images,
        "blend": {"path": blend_path.name, "sha256": sha256(blend_path)},
        "passed": passed,
        "boundary": (
            "The specimen is released above a collision support without pinned "
            "vertices. Blender scalar springs cannot represent warp and weft "
            "independently, so each material uses an explicit fixture-derived "
            "diagnostic solver correction rather than a calibrated or universal "
            "physical-unit conversion. Temporal convergence is required before "
            "coefficient-fit acceptance. "
            "Contact friction and through-thickness compression remain unmeasured."
        ),
    }
    report_path = output / "material-drape-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main(blender_arguments()))
