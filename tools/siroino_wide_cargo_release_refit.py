#!/usr/bin/env python3
"""Body-clearance refit for Siroino Wide Cargo.

The previous release layer compressed already-fitted geometry a second time.
That pushed the waist and leg profile into the avatar and produced renders that
looked detached or unworn despite passing topology checks. This layer keeps the
wide silhouette, restores body depth, enforces positive body clearance, and
adds a geometric wearability audit before any generated asset can be pushed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_entry_v8 as production

build = production.build
base = production.v7
_current_leg_shell = build.asymmetric_leg_shell
_current_band = build.flat_ellipse_band
_current_create_outfit = build.create_outfit


def _replace(obj: bpy.types.Object, assignments: dict[str, list[tuple[int, float]]]) -> None:
    base.replace_vertex_weights(obj, assignments)


def _single_bone(obj: bpy.types.Object, bone: str) -> None:
    _replace(obj, {bone: [(vertex.index, 1.0) for vertex in obj.data.vertices]})


def _upper_leg_gradient(obj: bpy.types.Object, side: str) -> None:
    assignments = {"Hips": [], f"UpperLeg_{side}": []}
    zs = [vertex.co.z for vertex in obj.data.vertices]
    low, high = min(zs, default=0.0), max(zs, default=1.0)
    span = max(high - low, 1e-6)
    for vertex in obj.data.vertices:
        t = base.clamp((vertex.co.z - low) / span, 0.0, 1.0)
        upper_weight = 0.94 - 0.48 * t
        assignments[f"UpperLeg_{side}"].append((vertex.index, upper_weight))
        assignments["Hips"].append((vertex.index, 1.0 - upper_weight))
    _replace(obj, assignments)


def _lower_leg_gradient(obj: bpy.types.Object, side: str) -> None:
    assignments = {f"UpperLeg_{side}": [], f"LowerLeg_{side}": []}
    zs = [vertex.co.z for vertex in obj.data.vertices]
    low, high = min(zs, default=0.0), max(zs, default=1.0)
    span = max(high - low, 1e-6)
    for vertex in obj.data.vertices:
        t = base.clamp((vertex.co.z - low) / span, 0.0, 1.0)
        upper_weight = 0.06 + 0.72 * t
        assignments[f"UpperLeg_{side}"].append((vertex.index, upper_weight))
        assignments[f"LowerLeg_{side}"].append((vertex.index, 1.0 - upper_weight))
    _replace(obj, assignments)


def _body_index(body: bpy.types.Object) -> tuple[KDTree, list[Vector], list[Vector]]:
    tree = KDTree(len(body.data.vertices))
    positions: list[Vector] = []
    normals: list[Vector] = []
    normal_matrix = body.matrix_world.to_3x3()
    for index, vertex in enumerate(body.data.vertices):
        position = body.matrix_world @ vertex.co
        normal = (normal_matrix @ vertex.normal).normalized()
        positions.append(position)
        normals.append(normal)
        tree.insert(position, index)
    tree.balance()
    return tree, positions, normals


def _ensure_body_clearance(
    obj: bpy.types.Object,
    body: bpy.types.Object,
    clearance: float,
) -> None:
    """Push vertices outside the nearest body surface instead of scaling inward."""
    tree, positions, normals = _body_index(body)
    inverse = obj.matrix_world.inverted_safe()
    changed = False
    for vertex in obj.data.vertices:
        world = obj.matrix_world @ vertex.co
        _, index, _ = tree.find(world)
        normal = normals[index]
        signed = (world - positions[index]).dot(normal)
        if signed < clearance:
            world += normal * (clearance - signed)
            vertex.co = inverse @ world
            changed = True
    if changed:
        obj.data.update(calc_edges=True)


def _signed_clearances(obj: bpy.types.Object, body: bpy.types.Object) -> list[float]:
    tree, positions, normals = _body_index(body)
    values: list[float] = []
    for vertex in obj.data.vertices:
        world = obj.matrix_world @ vertex.co
        _, index, _ = tree.find(world)
        values.append((world - positions[index]).dot(normals[index]))
    return values


def refined_leg_shell(name, side, rings, material, armature, body, segments=48):
    obj = _current_leg_shell(name, side, rings, material, armature, body, segments=segments)
    coordinates = [vertex.co.copy() for vertex in obj.data.vertices]
    center_x = sum(value.x for value in coordinates) / max(1, len(coordinates))
    side_name = "L" if side < 0 else "R"

    if "UpperLeg" in name:
        for vertex in obj.data.vertices:
            vertex.co.x = center_x + (vertex.co.x - center_x) * 1.04
            vertex.co.y *= 1.03
            if vertex.co.z < 0.50:
                vertex.co.z -= 0.015
        _upper_leg_gradient(obj, side_name)
    elif "LowerLeg" in name:
        zs = [vertex.co.z for vertex in obj.data.vertices]
        low, high = min(zs, default=0.0), max(zs, default=1.0)
        span = max(high - low, 1e-6)
        for vertex in obj.data.vertices:
            t = base.clamp((vertex.co.z - low) / span, 0.0, 1.0)
            width_scale = 1.06 + 0.06 * (1.0 - t)
            vertex.co.x = center_x + (vertex.co.x - center_x) * width_scale
            vertex.co.y *= 1.04
            if vertex.co.z > 0.34:
                vertex.co.z += 0.018
            if vertex.co.z < 0.14:
                vertex.co.z += 0.015
        _lower_leg_gradient(obj, side_name)

    obj.data.update(calc_edges=True)
    _ensure_body_clearance(obj, body, 0.0045)
    return obj


def refined_band(
    name,
    center_x,
    radius_x,
    radius_y,
    z,
    width,
    material,
    armature,
    body,
    **kwargs,
):
    obj = _current_band(
        name,
        center_x,
        radius_x,
        radius_y,
        z,
        width,
        material,
        armature,
        body,
        **kwargs,
    )
    vertices = list(obj.data.vertices)
    if name in {"Primary_Waist_Belt", "Asymmetric_Waist_Belt"}:
        for vertex in vertices:
            vertex.co.x *= 1.01
            vertex.co.y *= 1.04
            vertex.co.z -= 0.002
        _single_bone(obj, "Hips")
        _ensure_body_clearance(obj, body, 0.0055)
    elif name.startswith("Knee_Strap_"):
        side_name = "L" if "_L_" in name else "R"
        local_center = sum(vertex.co.x for vertex in vertices) / max(1, len(vertices))
        for vertex in vertices:
            vertex.co.x = local_center + (vertex.co.x - local_center) * 0.96
            vertex.co.y *= 1.04
            vertex.co.z -= 0.001
        _lower_leg_gradient(obj, side_name)
        _ensure_body_clearance(obj, body, 0.0050)
    obj.data.update(calc_edges=True)
    return obj


def _remove_object(obj: bpy.types.Object) -> None:
    if obj.name in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)


def refined_create_outfit(body, armature, fabric, strap, metal):
    objects = _current_create_outfit(body, armature, fabric, strap, metal)

    retained: list[bpy.types.Object] = []
    for obj in objects:
        if obj.name in {"Cargo_Fitted_Front_Pelvis", "Cargo_Fitted_Back_Yoke"}:
            _remove_object(obj)
        else:
            retained.append(obj)

    front = build.c.extract_surface(
        body,
        armature,
        "Cargo_Fitted_Front_Pelvis",
        lambda point: (
            0.432 <= point.z <= 0.792
            and point.y < 0.030
            and abs(point.x) <= 0.116 + max(0.0, point.z - 0.432) * 0.07
        ),
        fabric,
        0.0070,
    )
    back = build.c.extract_surface(
        body,
        armature,
        "Cargo_Fitted_Back_Yoke",
        lambda point: (
            0.430 <= point.z <= 0.792
            and point.y >= -0.030
            and abs(point.x) <= 0.120 + max(0.0, point.z - 0.430) * 0.06
        ),
        fabric,
        0.0070,
    )
    build.finish_skinned(front, body)
    build.finish_skinned(back, body)
    _ensure_body_clearance(front, body, 0.0055)
    _ensure_body_clearance(back, body, 0.0055)

    for obj in retained:
        name = obj.name
        if name.startswith("Cargo_Pocket_"):
            # Vertices are local to an object whose location already stores the
            # pocket center. Scaling around obj.location moved the mesh twice.
            for vertex in obj.data.vertices:
                vertex.co.x *= 0.82
                vertex.co.y *= 0.75
                vertex.co.z *= 0.92
            _single_bone(obj, "UpperLeg_L" if name.endswith("_L") else "UpperLeg_R")
            obj.data.update(calc_edges=True)
            _ensure_body_clearance(obj, body, 0.0065)
        elif name.startswith("Hip_Cutout_Strap_"):
            for vertex in obj.data.vertices:
                vertex.co.x *= 0.94
                vertex.co.y *= 1.02
            _single_bone(obj, "Hips")
            obj.data.update(calc_edges=True)
            _ensure_body_clearance(obj, body, 0.0060)
        elif name.startswith("Hip_Ring_"):
            obj.scale *= 0.72
            _single_bone(obj, "Hips")
        elif name.startswith("Knee_Zipper_") or name.startswith("Knee_Zip_Pull_"):
            side_name = "L" if name.endswith("_L") else "R"
            _lower_leg_gradient(obj, side_name)
            _ensure_body_clearance(obj, body, 0.0060)

    return [front, back, *retained]


def audit_wearability() -> dict[str, object]:
    body = next(
        (
            obj
            for obj in bpy.data.objects
            if obj.type == "MESH" and obj.name.startswith("SiroinoSotai_PC")
        ),
        None,
    )
    if body is None:
        raise RuntimeError("wearability audit could not find the exact Siroino body")

    required = (
        "Cargo_UpperLeg_L",
        "Cargo_UpperLeg_R",
        "Cargo_LowerLeg_L",
        "Cargo_LowerLeg_R",
        "Cargo_Fitted_Front_Pelvis",
        "Cargo_Fitted_Back_Yoke",
        "Primary_Waist_Belt",
    )
    missing = [name for name in required if name not in bpy.data.objects]
    checks: dict[str, object] = {"requiredObjectsPresent": not missing, "missing": missing}

    clearance_report: dict[str, float] = {}
    clearance_pass = True
    for name in required:
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        values = sorted(_signed_clearances(obj, body))
        percentile_index = min(len(values) - 1, max(0, int(len(values) * 0.05)))
        p05 = values[percentile_index] if values else -1.0
        clearance_report[name] = round(float(p05), 6)
        clearance_pass = clearance_pass and p05 >= -0.0015
    checks["signedClearanceP05Meters"] = clearance_report
    checks["bodyClearancePassed"] = clearance_pass

    front = bpy.data.objects.get("Cargo_Fitted_Front_Pelvis")
    back = bpy.data.objects.get("Cargo_Fitted_Back_Yoke")
    panel_pass = False
    panel_metrics: dict[str, dict[str, float]] = {}
    if front and back:
        for obj in (front, back):
            xs = [vertex.co.x for vertex in obj.data.vertices]
            zs = [vertex.co.z for vertex in obj.data.vertices]
            panel_metrics[obj.name] = {
                "width": round(max(xs, default=0.0) - min(xs, default=0.0), 6),
                "height": round(max(zs, default=0.0) - min(zs, default=0.0), 6),
                "minimumZ": round(min(zs, default=1.0), 6),
            }
        panel_pass = all(
            value["width"] >= 0.18
            and value["height"] >= 0.30
            and value["minimumZ"] <= 0.46
            for value in panel_metrics.values()
        )
    checks["pelvisPanels"] = panel_metrics
    checks["continuousPelvisCoveragePassed"] = panel_pass

    waist = bpy.data.objects.get("Primary_Waist_Belt")
    waist_pass = False
    waist_metrics: dict[str, float] = {}
    if waist:
        xs = [vertex.co.x for vertex in waist.data.vertices]
        ys = [vertex.co.y for vertex in waist.data.vertices]
        waist_metrics = {
            "width": round(max(xs, default=0.0) - min(xs, default=0.0), 6),
            "depth": round(max(ys, default=0.0) - min(ys, default=0.0), 6),
        }
        waist_pass = waist_metrics["width"] >= 0.24 and waist_metrics["depth"] >= 0.15
    checks["waistDimensions"] = waist_metrics
    checks["waistNotCollapsedPassed"] = waist_pass

    passed = not missing and clearance_pass and panel_pass and waist_pass
    return {
        "schemaVersion": 1,
        "passed": passed,
        "checks": checks,
    }


def record_wearability(report: dict[str, object]) -> None:
    _, job = build.c.load_job()
    manifest_path = build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    manifest["wearabilityAudit"] = report
    manifest["designRevision"] = "v14-body-clearance-wearable"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


build.asymmetric_leg_shell = refined_leg_shell
build.flat_ellipse_band = refined_band
build.create_outfit = refined_create_outfit

if __name__ == "__main__":
    exit_code = build.main()
    if exit_code == 0:
        report = audit_wearability()
        record_wearability(report)
        if report.get("passed") is not True:
            raise RuntimeError(f"geometric wearability audit failed: {report}")
        base.save_distribution_blend()
    raise SystemExit(exit_code)
