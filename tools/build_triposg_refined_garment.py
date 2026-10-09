#!/usr/bin/env python3
"""Build a clean Siroino garment from a local TripoSG shape hypothesis.

The unstable reconstructed surface is not used directly.  Instead, the GLB is
actually imported and measured, then those measurements drive the garment-only
envelope and the locked hero construction required by the Siroino candidate
issues before weight transfer and FBX export.  This keeps the cleanup
deterministic while making the result depend on the TripoSG hypothesis.
"""

from __future__ import annotations

import argparse
import bmesh
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from build_oss_character_meshes import (  # noqa: E402
    BODY_FBX,
    bounds,
    export_fbx,
    transfer_weights,
)


def parse_args() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--kind", required=True, choices=("crescent", "herbarium", "orbital")
    )
    parser.add_argument("--hypothesis-input", required=True, type=Path)
    parser.add_argument("--output-fbx", required=True, type=Path)
    parser.add_argument("--output-blend", required=True, type=Path)
    parser.add_argument("--output-report", required=True, type=Path)
    parser.add_argument("--triangle-budget", required=True, type=int)
    return parser.parse_args(values)


def repo_path(path: Path) -> Path:
    resolved = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise ValueError(f"path escapes repository: {path}")
    return resolved


def mesh_object(
    name: str, vertices: list[tuple[float, float, float]], faces: list[tuple[int, ...]]
) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def aggregate_bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    points = [
        obj.matrix_world @ vertex.co for obj in objects for vertex in obj.data.vertices
    ]
    if not points:
        raise RuntimeError("TripoSG hypothesis contains no mesh vertices")
    return (
        Vector(min(point[index] for point in points) for index in range(3)),
        Vector(max(point[index] for point in points) for index in range(3)),
    )


def topology_diagnostics(objects: list[bpy.types.Object]) -> dict[str, int]:
    boundary_edges = 0
    non_manifold_edges = 0
    degenerate_faces = 0
    for obj in objects:
        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)
            boundary_edges += sum(1 for edge in bm.edges if len(edge.link_faces) == 1)
            non_manifold_edges += sum(
                1 for edge in bm.edges if len(edge.link_faces) > 2
            )
            degenerate_faces += sum(1 for face in bm.faces if face.calc_area() <= 1e-12)
        finally:
            bm.free()
    return {
        "boundaryEdgeCount": boundary_edges,
        "nonManifoldEdgeCount": non_manifold_edges,
        "degenerateFaceCount": degenerate_faces,
    }


def import_hypothesis(path: Path) -> dict[str, object]:
    """Import the GLB, record its geometry envelope, then remove it.

    The raw surface remains an upstream hypothesis and evidence artifact.  It
    is not joined into the garment because the local TripoSG reconstructions
    have shown visible holes and self-overlap in Unity.
    """

    existing = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    imported_meshes = [
        obj
        for obj in bpy.data.objects
        if obj not in existing and obj.type == "MESH" and len(obj.data.vertices) > 0
    ]
    if not imported_meshes:
        raise RuntimeError(f"TripoSG hypothesis imported without mesh geometry: {path}")
    minimum, maximum = aggregate_bounds(imported_meshes)
    dimensions = maximum - minimum
    vertex_count = sum(len(obj.data.vertices) for obj in imported_meshes)
    mesh_object_count = len(imported_meshes)
    topology = topology_diagnostics(imported_meshes)
    for obj in list(bpy.data.objects):
        if obj not in existing:
            bpy.data.objects.remove(obj, do_unlink=True)
    return {
        "vertexCount": vertex_count,
        "meshObjectCount": mesh_object_count,
        "topology": topology,
        "bounds": {"min": list(minimum), "max": list(maximum)},
        "dimensions": list(dimensions),
    }


def hypothesis_scales(
    hypothesis: dict[str, object], body_min: Vector, body_max: Vector
) -> dict[str, float]:
    dimensions = Vector(hypothesis["dimensions"])
    body_dimensions = body_max - body_min
    if dimensions.z <= 1e-8:
        return {"widthScale": 1.0, "depthScale": 1.0, "heightScale": 1.0}

    # TripoSG and the Siroino FBX use different absolute units.  Compare the
    # hypothesis silhouette as width/height and depth/height ratios instead of
    # clamping raw dimensions against the avatar's very shallow depth.
    width_aspect = dimensions.x / dimensions.z
    depth_aspect = dimensions.y / dimensions.z
    width_scale = 1.0 + 0.45 * ((width_aspect / 0.44) - 1.0)
    depth_scale = 1.0 + 0.55 * ((depth_aspect / 0.21) - 1.0)
    height_scale = dimensions.z / body_dimensions.z if body_dimensions.z > 1e-8 else 1.0
    return {
        "widthScale": max(0.82, min(1.18, width_scale)),
        "depthScale": max(0.82, min(1.18, depth_scale)),
        "heightScale": max(0.94, min(1.06, height_scale)),
    }


def shell(name: str) -> bpy.types.Object:
    profile = (
        (0.06, 0.235, 0.118),
        (0.18, 0.23, 0.116),
        (0.38, 0.215, 0.112),
        (0.62, 0.175, 0.105),
        (0.78, 0.155, 0.098),
        (0.94, 0.185, 0.105),
        (1.06, 0.205, 0.108),
    )
    segments = 40
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for z, rx, ry in profile:
        for i in range(segments):
            angle = 2.0 * math.pi * i / segments
            vertices.append((rx * math.cos(angle), ry * math.sin(angle), z))
    for row in range(len(profile) - 1):
        for i in range(segments):
            a = row * segments + i
            b = row * segments + (i + 1) % segments
            c = (row + 1) * segments + (i + 1) % segments
            d = (row + 1) * segments + i
            faces.append((a, b, c, d))
    faces.append(tuple(range(segments - 1, -1, -1)))
    top = (len(profile) - 1) * segments
    faces.append(tuple(top + i for i in range(segments)))
    return mesh_object(name, vertices, faces)


def tube_between(
    name: str,
    start: Vector,
    end: Vector,
    start_radius: float,
    end_radius: float,
    segments: int = 14,
) -> bpy.types.Object:
    axis = (end - start).normalized()
    helper = Vector((0.0, 0.0, 1.0))
    if abs(axis.dot(helper)) > 0.9:
        helper = Vector((0.0, 1.0, 0.0))
    u = axis.cross(helper).normalized()
    v = axis.cross(u).normalized()
    vertices: list[tuple[float, float, float]] = []
    for center, radius in ((start, start_radius), (end, end_radius)):
        for i in range(segments):
            angle = 2.0 * math.pi * i / segments
            point = (
                center + u * (math.cos(angle) * radius) + v * (math.sin(angle) * radius)
            )
            vertices.append(tuple(point))
    faces: list[tuple[int, ...]] = []
    for i in range(segments):
        j = (i + 1) % segments
        faces.append((i, j, segments + j, segments + i))
    faces.append(tuple(range(segments - 1, -1, -1)))
    faces.append(tuple(segments + i for i in range(segments)))
    return mesh_object(name, vertices, faces)


def curve_tube(
    name: str, points: list[Vector], radius: float, segments: int = 10
) -> bpy.types.Object:
    vertices: list[tuple[float, float, float]] = []
    for index, point in enumerate(points):
        previous = points[max(0, index - 1)]
        following = points[min(len(points) - 1, index + 1)]
        tangent = (following - previous).normalized()
        helper = Vector((0.0, 0.0, 1.0))
        if abs(tangent.dot(helper)) > 0.9:
            helper = Vector((0.0, 1.0, 0.0))
        normal = tangent.cross(helper).normalized()
        binormal = tangent.cross(normal).normalized()
        for ring in range(segments):
            angle = 2.0 * math.pi * ring / segments
            vertex = (
                point
                + normal * (math.cos(angle) * radius)
                + binormal * (math.sin(angle) * radius)
            )
            vertices.append(tuple(vertex))
    faces: list[tuple[int, ...]] = []
    for row in range(len(points) - 1):
        for ring in range(segments):
            next_ring = (ring + 1) % segments
            a = row * segments + ring
            b = row * segments + next_ring
            c = (row + 1) * segments + next_ring
            d = (row + 1) * segments + ring
            faces.append((a, b, c, d))
    faces.append(tuple(range(segments - 1, -1, -1)))
    last = (len(points) - 1) * segments
    faces.append(tuple(last + i for i in range(segments)))
    return mesh_object(name, vertices, faces)


def elliptical_torus(
    name: str, z: float, rx: float, ry: float, tube_radius: float
) -> bpy.types.Object:
    major_segments = 48
    tube_segments = 8
    vertices: list[tuple[float, float, float]] = []
    for major in range(major_segments):
        angle = 2.0 * math.pi * major / major_segments
        radial = Vector((math.cos(angle), math.sin(angle), 0.0))
        center = Vector((rx * math.cos(angle), ry * math.sin(angle), z))
        for tube in range(tube_segments):
            phi = 2.0 * math.pi * tube / tube_segments
            point = (
                center
                + radial * (tube_radius * math.cos(phi))
                + Vector((0.0, 0.0, tube_radius * math.sin(phi)))
            )
            vertices.append(tuple(point))
    faces: list[tuple[int, ...]] = []
    for major in range(major_segments):
        next_major = (major + 1) % major_segments
        for tube in range(tube_segments):
            next_tube = (tube + 1) % tube_segments
            a = major * tube_segments + tube
            b = next_major * tube_segments + tube
            c = next_major * tube_segments + next_tube
            d = major * tube_segments + next_tube
            faces.append((a, b, c, d))
    return mesh_object(name, vertices, faces)


def extruded_plate(
    name: str,
    center_x: float,
    center_y: float,
    center_z: float,
    sign: float,
    scale: float = 1.0,
) -> bpy.types.Object:
    outline = ((0.0, -0.15), (0.075, -0.10), (0.10, 0.0), (0.075, 0.11), (0.0, 0.16))
    thickness = 0.018
    vertices: list[tuple[float, float, float]] = []
    for depth in (-thickness, thickness):
        for x, z in outline:
            vertices.append(
                (center_x + sign * x * scale, center_y + depth, center_z + z * scale)
            )
    count = len(outline)
    faces = [tuple(range(count - 1, -1, -1)), tuple(count + i for i in range(count))]
    for i in range(count):
        j = (i + 1) % count
        faces.append((i, j, count + j, count + i))
    return mesh_object(name, vertices, faces)


def add_components(kind: str) -> list[bpy.types.Object]:
    parts = [shell("TripoSGRefinedGarmentShell")]
    parts.extend(
        [
            tube_between(
                "SleeveL",
                Vector((-0.17, 0.0, 0.96)),
                Vector((-0.55, 0.0, 0.96)),
                0.075,
                0.055,
            ),
            tube_between(
                "SleeveR",
                Vector((0.17, 0.0, 0.96)),
                Vector((0.55, 0.0, 0.96)),
                0.075,
                0.055,
            ),
            tube_between(
                "StandCollar",
                Vector((-0.16, 0.0, 1.06)),
                Vector((0.16, 0.0, 1.06)),
                0.045,
                0.045,
            ),
        ]
    )
    if kind == "crescent":
        for sign in (-1.0, 1.0):
            parts.append(
                curve_tube(
                    "CrescentPleat",
                    [
                        Vector((sign * 0.10, 0.125, 0.79)),
                        Vector((sign * 0.145, 0.14, 0.72)),
                        Vector((sign * 0.18, 0.13, 0.64)),
                        Vector((sign * 0.215, 0.115, 0.57)),
                    ],
                    0.018,
                )
            )
        parts.append(
            curve_tube(
                "CrescentThroatLatch",
                [
                    Vector((-0.06, 0.13, 1.015)),
                    Vector((0.0, 0.15, 0.995)),
                    Vector((0.06, 0.13, 1.015)),
                ],
                0.014,
            )
        )
    elif kind == "herbarium":
        for sign in (-1.0, 1.0):
            for layer, scale in enumerate((1.0, 0.84, 0.68)):
                parts.append(
                    extruded_plate(
                        f"HerbariumShutter_{layer}",
                        sign * 0.205,
                        0.085 + layer * 0.012,
                        0.53,
                        sign,
                        scale,
                    )
                )
        parts.append(
            curve_tube(
                "CollarRootSampleClasp",
                [
                    Vector((-0.045, 0.135, 1.07)),
                    Vector((0.0, 0.15, 1.055)),
                    Vector((0.045, 0.135, 1.07)),
                ],
                0.013,
            )
        )
    else:
        parts.extend(
            [
                elliptical_torus("OrbitalHemRailLower", 0.20, 0.255, 0.13, 0.019),
                elliptical_torus("OrbitalHemRailUpper", 0.34, 0.265, 0.135, 0.019),
                curve_tube(
                    "CrescentSternumLock",
                    [
                        Vector((-0.055, 0.13, 0.995)),
                        Vector((0.0, 0.15, 0.975)),
                        Vector((0.055, 0.13, 0.995)),
                    ],
                    0.014,
                ),
            ]
        )
    return parts


def join_parts(parts: list[bpy.types.Object]) -> bpy.types.Object:
    bpy.ops.object.select_all(action="DESELECT")
    for part in parts:
        part.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    parts[0].name = "TripoSGRefinedGarmentMesh"
    return parts[0]


def apply_garment_material(obj: bpy.types.Object, kind: str) -> None:
    colors = {
        "crescent": (0.82, 0.78, 0.69, 1.0),
        "herbarium": (0.72, 0.70, 0.57, 1.0),
        "orbital": (0.43, 0.54, 0.68, 1.0),
    }
    material = bpy.data.materials.new("TripoSG Refined Garment")
    material.use_nodes = True
    material.diffuse_color = colors[kind]
    material.node_tree.nodes.get("Principled BSDF").inputs[
        "Base Color"
    ].default_value = colors[kind]
    obj.data.materials.clear()
    obj.data.materials.append(material)


def main() -> int:
    args = parse_args()
    hypothesis = repo_path(args.hypothesis_input)
    output_fbx = repo_path(args.output_fbx)
    output_blend = repo_path(args.output_blend)
    output_report = repo_path(args.output_report)
    if not hypothesis.is_file() or not BODY_FBX.is_file():
        raise FileNotFoundError("TripoSG hypothesis or Siroino skeleton is missing")
    if args.triangle_budget < 3:
        raise ValueError("triangle budget must be at least 3")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(BODY_FBX))
    source = bpy.data.objects.get("SiroinoSotai_PC")
    armature = bpy.data.objects.get("Armature")
    if source is None or armature is None:
        raise RuntimeError("Siroino base mesh or Armature was not imported")

    body_min, body_max = bounds(source)
    hypothesis_metrics = import_hypothesis(hypothesis)
    shape_scales = hypothesis_scales(hypothesis_metrics, body_min, body_max)
    target = join_parts(add_components(args.kind))
    target.scale.x *= shape_scales["widthScale"]
    target.scale.y *= shape_scales["depthScale"]
    target.scale.z *= shape_scales["heightScale"]
    target_min, target_max = bounds(target)
    target.scale *= (body_max.z - body_min.z) / (target_max.z - target_min.z)
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    target_min, target_max = bounds(target)
    target.location += Vector(
        (
            (body_min.x + body_max.x) * 0.5 - (target_min.x + target_max.x) * 0.5,
            (body_min.y + body_max.y) * 0.5 - (target_min.y + target_max.y) * 0.5,
            body_min.z - target_min.z,
        )
    )
    bpy.context.view_layer.update()
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)

    apply_garment_material(target, args.kind)
    weight_artifact = transfer_weights(source, target, armature)
    export_fbx(output_fbx, armature, target)
    bpy.ops.wm.save_as_mainfile(
        filepath=str(output_blend), check_existing=False, compress=True
    )
    final_min, final_max = bounds(target)
    triangle_count = sum(len(polygon.vertices) - 2 for polygon in target.data.polygons)
    report = {
        "schemaVersion": 1,
        "kind": "triposg-refined-garment",
        "sourceModel": "TripoSG",
        "constructionMethod": "TripoSG-imported-shape-metrics-plus-deterministic-garment-envelope",
        "hypothesisInput": str(hypothesis.relative_to(ROOT)).replace("\\", "/"),
        "outputFbx": str(output_fbx.relative_to(ROOT)).replace("\\", "/"),
        "outputBlend": str(output_blend.relative_to(ROOT)).replace("\\", "/"),
        "blenderVersion": bpy.app.version_string,
        "skeleton": "Assets/SiroinoWorks/SiroinoSotai/FBX/SiroinoSotai_PC.fbx",
        "kindVariant": args.kind,
        "hypothesisMetrics": hypothesis_metrics,
        "bodyDimensions": list(body_max - body_min),
        "hypothesisAspectRatios": {
            "widthToHeight": hypothesis_metrics["dimensions"][0]
            / hypothesis_metrics["dimensions"][2],
            "depthToHeight": hypothesis_metrics["dimensions"][1]
            / hypothesis_metrics["dimensions"][2],
        },
        "inputDependentScales": shape_scales,
        "triangleBudget": args.triangle_budget,
        "triangleCount": triangle_count,
        "normalizedBounds": {"min": list(final_min), "max": list(final_max)},
        "weightTransfer": weight_artifact,
        "status": "PASS"
        if weight_artifact["audit"]["passed"] and triangle_count <= args.triangle_budget
        else "FAIL",
    }
    output_report.parent.mkdir(parents=True, exist_ok=True)
    output_report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
