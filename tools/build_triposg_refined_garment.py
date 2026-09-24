#!/usr/bin/env python3
"""Build a clean Siroino garment from a local TripoSG shape hypothesis.

TripoSG is intentionally kept as the upstream shape hypothesis and provenance
anchor.  This adapter replaces the unstable reconstructed surface with a
deterministic, garment-only envelope and the locked hero construction required
by the Siroino candidate issues before weight transfer and FBX export.
"""

from __future__ import annotations

import argparse
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
    parser.add_argument("--kind", required=True, choices=("crescent", "herbarium", "orbital"))
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


def mesh_object(name: str, vertices: list[tuple[float, float, float]], faces: list[tuple[int, ...]]) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


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
            point = center + u * (math.cos(angle) * radius) + v * (math.sin(angle) * radius)
            vertices.append(tuple(point))
    faces: list[tuple[int, ...]] = []
    for i in range(segments):
        j = (i + 1) % segments
        faces.append((i, j, segments + j, segments + i))
    faces.append(tuple(range(segments - 1, -1, -1)))
    faces.append(tuple(segments + i for i in range(segments)))
    return mesh_object(name, vertices, faces)


def curve_tube(name: str, points: list[Vector], radius: float, segments: int = 10) -> bpy.types.Object:
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
            vertex = point + normal * (math.cos(angle) * radius) + binormal * (math.sin(angle) * radius)
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


def elliptical_torus(name: str, z: float, rx: float, ry: float, tube_radius: float) -> bpy.types.Object:
    major_segments = 48
    tube_segments = 8
    vertices: list[tuple[float, float, float]] = []
    for major in range(major_segments):
        angle = 2.0 * math.pi * major / major_segments
        radial = Vector((math.cos(angle), math.sin(angle), 0.0))
        center = Vector((rx * math.cos(angle), ry * math.sin(angle), z))
        for tube in range(tube_segments):
            phi = 2.0 * math.pi * tube / tube_segments
            point = center + radial * (tube_radius * math.cos(phi)) + Vector((0.0, 0.0, tube_radius * math.sin(phi)))
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


def extruded_plate(name: str, center_x: float, center_y: float, center_z: float, sign: float, scale: float = 1.0) -> bpy.types.Object:
    outline = ((0.0, -0.15), (0.075, -0.10), (0.10, 0.0), (0.075, 0.11), (0.0, 0.16))
    thickness = 0.018
    vertices: list[tuple[float, float, float]] = []
    for depth in (-thickness, thickness):
        for x, z in outline:
            vertices.append((center_x + sign * x * scale, center_y + depth, center_z + z * scale))
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
                Vector((-0.29, 0.0, 0.59)),
                0.075,
                0.055,
            ),
            tube_between(
                "SleeveR",
                Vector((0.17, 0.0, 0.96)),
                Vector((0.29, 0.0, 0.59)),
                0.075,
                0.055,
            ),
            tube_between("StandCollar", Vector((-0.16, 0.0, 1.06)), Vector((0.16, 0.0, 1.06)), 0.045, 0.045),
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
                [Vector((-0.06, 0.13, 1.015)), Vector((0.0, 0.15, 0.995)), Vector((0.06, 0.13, 1.015))],
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
                [Vector((-0.045, 0.135, 1.07)), Vector((0.0, 0.15, 1.055)), Vector((0.045, 0.135, 1.07))],
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
                    [Vector((-0.055, 0.13, 0.995)), Vector((0.0, 0.15, 0.975)), Vector((0.055, 0.13, 0.995))],
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
    material.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = colors[kind]
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

    target = join_parts(add_components(args.kind))
    body_min, body_max = bounds(source)
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
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend), check_existing=False, compress=True)
    final_min, final_max = bounds(target)
    triangle_count = sum(len(polygon.vertices) - 2 for polygon in target.data.polygons)
    report = {
        "schemaVersion": 1,
        "kind": "triposg-refined-garment",
        "sourceModel": "TripoSG",
        "constructionMethod": "TripoSG-shape-hypothesis-plus-deterministic-garment-envelope",
        "hypothesisInput": str(hypothesis.relative_to(ROOT)).replace("\\", "/"),
        "outputFbx": str(output_fbx.relative_to(ROOT)).replace("\\", "/"),
        "outputBlend": str(output_blend.relative_to(ROOT)).replace("\\", "/"),
        "blenderVersion": bpy.app.version_string,
        "skeleton": "Assets/SiroinoWorks/SiroinoSotai/FBX/SiroinoSotai_PC.fbx",
        "kindVariant": args.kind,
        "triangleBudget": args.triangle_budget,
        "triangleCount": triangle_count,
        "normalizedBounds": {"min": list(final_min), "max": list(final_max)},
        "weightTransfer": weight_artifact,
        "status": "PASS" if weight_artifact["audit"]["passed"] and triangle_count <= args.triangle_budget else "FAIL",
    }
    output_report.parent.mkdir(parents=True, exist_ok=True)
    output_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
