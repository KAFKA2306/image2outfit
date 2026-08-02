#!/usr/bin/env python3
"""Continuous wearable refit for Siroino Wide Cargo.

The rendered v14 candidate still read as separate armor panels rather than
pants: the inner calves were exposed, the pelvis was assembled from disconnected
front/back/hip pieces, and several belts and straps floated away from the body.

This revision deliberately simplifies the product into a stable wearable base:

* one continuous body-derived shell from waist through the upper legs,
* lower-leg shells widened inward until they cover the inner calves,
* a single close-fitting waistband,
* no floating hip diagonals, rings, duplicate waist belt, or knee hoops,
* no post-solidify clearance operation on body-derived cloth surfaces.

Decorative complexity can be reintroduced only after the continuous garment
passes actual rendered front/back/side and pose review.
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


def _lower_leg_gradient(obj: bpy.types.Object, side: str) -> None:
    assignments = {f"UpperLeg_{side}": [], f"LowerLeg_{side}": []}
    zs = [vertex.co.z for vertex in obj.data.vertices]
    low, high = min(zs, default=0.0), max(zs, default=1.0)
    span = max(high - low, 1e-6)
    for vertex in obj.data.vertices:
        t = base.clamp((vertex.co.z - low) / span, 0.0, 1.0)
        upper_weight = 0.08 + 0.74 * t
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
    """Move rigid/decorative geometry outside the body.

    Do not use this on body-derived cloth after solidify: moving both thickness
    surfaces to the same signed distance collapses side walls and creates
    degenerate triangles.
    """
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


def refined_leg_shell(name, side, rings, material, armature, body, segments=48):
    obj = _current_leg_shell(name, side, rings, material, armature, body, segments=segments)
    if "LowerLeg" not in name:
        return obj

    coordinates = [vertex.co.copy() for vertex in obj.data.vertices]
    center_x = sum(value.x for value in coordinates) / max(1, len(coordinates))
    side_name = "L" if side < 0 else "R"
    zs = [vertex.co.z for vertex in obj.data.vertices]
    low, high = min(zs, default=0.0), max(zs, default=1.0)
    span = max(high - low, 1e-6)

    # The prior shell spanned roughly |x| >= 0.027, leaving a conspicuous strip
    # of bare inner calf. Increase the radius around each leg centre so the
    # inner boundary approaches the body centreline while retaining wide hems.
    for vertex in obj.data.vertices:
        t = base.clamp((vertex.co.z - low) / span, 0.0, 1.0)
        radial_scale = 1.22 + 0.08 * t
        vertex.co.x = center_x + (vertex.co.x - center_x) * radial_scale
        vertex.co.y *= 1.08
        if vertex.co.z > high - 0.07:
            vertex.co.z += 0.020
        if vertex.co.z < low + 0.08:
            vertex.co.z += 0.012
    obj.data.update(calc_edges=True)
    _lower_leg_gradient(obj, side_name)
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
    if name == "Primary_Waist_Belt":
        # The prior band floated several centimetres beyond the waist.
        for vertex in obj.data.vertices:
            vertex.co.x *= 0.84
            vertex.co.y *= 0.86
            vertex.co.z -= 0.004
        _single_bone(obj, "Hips")
        _ensure_body_clearance(obj, body, 0.0035)
        obj.data.update(calc_edges=True)
    return obj


def _remove_object(obj: bpy.types.Object) -> None:
    if obj.name in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)


def _is_removed_decoration(name: str) -> bool:
    return (
        name in {
            "Cargo_Fitted_Front_Pelvis",
            "Cargo_Fitted_Back_Yoke",
            "Cargo_Fitted_Hip_L",
            "Cargo_Fitted_Hip_R",
            "Cargo_UpperLeg_L",
            "Cargo_UpperLeg_R",
            "Asymmetric_Waist_Belt",
            "Side_Belt_Buckle",
        }
        or name.startswith("Hip_Cutout_Strap_")
        or name.startswith("Hip_Ring_")
        or name.startswith("Knee_Strap_")
        or name.startswith("Knee_Zipper_")
        or name.startswith("Knee_Zip_Pull_")
    )


def refined_create_outfit(body, armature, fabric, strap, metal):
    generated = _current_create_outfit(body, armature, fabric, strap, metal)
    retained: list[bpy.types.Object] = []
    for obj in generated:
        if _is_removed_decoration(obj.name):
            _remove_object(obj)
        else:
            retained.append(obj)

    # One circumferential shell replaces the disconnected front/back/hip and
    # left/right upper-leg pieces. Selecting the complete source-body surface
    # in this height band guarantees actual inner-thigh and crotch coverage.
    upper = build.c.extract_surface(
        body,
        armature,
        "Cargo_Continuous_Upper",
        lambda point: 0.355 <= point.z <= 0.795,
        fabric,
        0.0080,
    )
    for vertex in upper.data.vertices:
        t = base.clamp((vertex.co.z - 0.355) / 0.440, 0.0, 1.0)
        vertex.co.x *= 1.035 - 0.010 * t
        vertex.co.y *= 1.045 - 0.010 * t
    upper.data.update(calc_edges=True)
    build.c.add_nearest_shape_keys(upper, body)

    for obj in retained:
        name = obj.name
        if name.startswith("Cargo_Pocket_Flap_"):
            for vertex in obj.data.vertices:
                vertex.co.x *= 0.76
                vertex.co.y *= 0.58
                vertex.co.z *= 0.82
            obj.location.y += 0.006
            obj.data.update(calc_edges=True)
            _single_bone(obj, "UpperLeg_L" if name.endswith("_L") else "UpperLeg_R")
            _ensure_body_clearance(obj, body, 0.0045)
        elif name.startswith("Cargo_Pocket_"):
            for vertex in obj.data.vertices:
                vertex.co.x *= 0.80
                vertex.co.y *= 0.62
                vertex.co.z *= 0.84
            obj.location.y += 0.006
            obj.data.update(calc_edges=True)
            _single_bone(obj, "UpperLeg_L" if name.endswith("_L") else "UpperLeg_R")
            _ensure_body_clearance(obj, body, 0.0045)
        elif name in {"Front_Belt_Buckle", "Long_Center_Zipper", "Center_Zip_Pull"}:
            _ensure_body_clearance(obj, body, 0.0040)

    return [upper, *retained]


def _mesh_degenerate_triangles(obj: bpy.types.Object) -> int:
    mesh = obj.data
    mesh.calc_loop_triangles()
    count = 0
    for triangle in mesh.loop_triangles:
        a, b, c = (mesh.vertices[index].co for index in triangle.vertices)
        if (b - a).cross(c - a).length_squared <= 1e-20:
            count += 1
    return count


def audit_wearability() -> dict[str, object]:
    required = (
        "Cargo_Continuous_Upper",
        "Cargo_LowerLeg_L",
        "Cargo_LowerLeg_R",
        "Primary_Waist_Belt",
    )
    missing = [name for name in required if name not in bpy.data.objects]
    checks: dict[str, object] = {"requiredObjectsPresent": not missing, "missing": missing}

    upper = bpy.data.objects.get("Cargo_Continuous_Upper")
    upper_metrics: dict[str, float | int] = {}
    upper_pass = False
    if upper:
        xs = [vertex.co.x for vertex in upper.data.vertices]
        zs = [vertex.co.z for vertex in upper.data.vertices]
        inner_vertices = sum(
            1
            for vertex in upper.data.vertices
            if 0.38 <= vertex.co.z <= 0.62 and abs(vertex.co.x) <= 0.085
        )
        upper_metrics = {
            "width": round(max(xs, default=0.0) - min(xs, default=0.0), 6),
            "minimumZ": round(min(zs, default=1.0), 6),
            "maximumZ": round(max(zs, default=0.0), 6),
            "innerThighVertices": inner_vertices,
            "degenerateTriangles": _mesh_degenerate_triangles(upper),
        }
        upper_pass = (
            upper_metrics["width"] >= 0.24
            and upper_metrics["minimumZ"] <= 0.38
            and upper_metrics["maximumZ"] >= 0.78
            and inner_vertices >= 80
            and upper_metrics["degenerateTriangles"] == 0
        )
    checks["continuousUpper"] = upper_metrics
    checks["continuousUpperPassed"] = upper_pass

    lower_report: dict[str, dict[str, float | int]] = {}
    lower_pass = True
    for name in ("Cargo_LowerLeg_L", "Cargo_LowerLeg_R"):
        obj = bpy.data.objects.get(name)
        if obj is None:
            lower_pass = False
            continue
        inner_edge = min((abs(vertex.co.x) for vertex in obj.data.vertices), default=1.0)
        degenerates = _mesh_degenerate_triangles(obj)
        lower_report[name] = {
            "innerEdgeAbsX": round(inner_edge, 6),
            "degenerateTriangles": degenerates,
        }
        lower_pass = lower_pass and inner_edge <= 0.012 and degenerates == 0
    checks["lowerLegCoverage"] = lower_report
    checks["innerCalfCoveragePassed"] = lower_pass

    waist = bpy.data.objects.get("Primary_Waist_Belt")
    waist_metrics: dict[str, float] = {}
    waist_pass = False
    if waist:
        xs = [vertex.co.x for vertex in waist.data.vertices]
        ys = [vertex.co.y for vertex in waist.data.vertices]
        waist_metrics = {
            "width": round(max(xs, default=0.0) - min(xs, default=0.0), 6),
            "depth": round(max(ys, default=0.0) - min(ys, default=0.0), 6),
        }
        waist_pass = 0.18 <= waist_metrics["width"] <= 0.25 and 0.11 <= waist_metrics["depth"] <= 0.18
    checks["waistDimensions"] = waist_metrics
    checks["waistAttachedPassed"] = waist_pass

    removed_present = sorted(
        name
        for name in bpy.data.objects.keys()
        if _is_removed_decoration(name)
    )
    checks["removedFloatingObjectsPresent"] = removed_present
    decoration_pass = not removed_present
    checks["floatingDecorationRemovalPassed"] = decoration_pass

    passed = not missing and upper_pass and lower_pass and waist_pass and decoration_pass
    return {"schemaVersion": 1, "passed": passed, "checks": checks}


def record_wearability(report: dict[str, object]) -> None:
    _, job = build.c.load_job()
    manifest_path = build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    manifest["wearabilityAudit"] = report
    manifest["designRevision"] = "v15-continuous-pants"
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
