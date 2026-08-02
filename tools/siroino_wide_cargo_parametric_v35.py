#!/usr/bin/env python3
"""Clean parametric Siroino Wide Cargo v35."""
from __future__ import annotations

import json
import math
import shutil
import sys
from collections import deque
from pathlib import Path

import bmesh
import bpy

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_wide_cargo_release_refit_v23 as v23

build = v23.build
base = v23.base
HEM_Z = 0.145
WAIST_Z = 0.785
VOXEL_SIZE = 0.0065
SEGMENTS = 64


def clear_stale_render_evidence() -> None:
    _, job = build.c.load_job()
    preview_root = build.c.repo_path(job["productRoot"]) / "Previews"
    if not preview_root.exists():
        return
    for pattern in ("*.png", "*.webp", "*.png.meta", "*.webp.meta"):
        for path in preview_root.glob(pattern):
            path.unlink(missing_ok=True)
    shutil.rmtree(preview_root / "Poses", ignore_errors=True)
    (preview_root / "Poses.meta").unlink(missing_ok=True)


def append_leg_volume(vertices, faces, *, side: int, rings, segments: int = SEGMENTS) -> None:
    offset = len(vertices)
    for z, inner, outer, front, back in rings:
        center_abs = (inner + outer) * 0.5
        radius_x = (outer - inner) * 0.5
        center_x = side * center_abs
        for index in range(segments):
            angle = math.tau * index / segments
            sine = math.sin(angle)
            depth = front if sine < 0.0 else back
            vertices.append((center_x + side * radius_x * math.cos(angle), depth * sine, z))
    for ring in range(len(rings) - 1):
        for index in range(segments):
            nxt = (index + 1) % segments
            a = offset + ring * segments + index
            b = offset + ring * segments + nxt
            c = offset + (ring + 1) * segments + nxt
            d = offset + (ring + 1) * segments + index
            faces.append((a, b, c, d))
    bottom = len(vertices)
    top = bottom + 1
    vertices.extend((
        (side * (rings[0][1] + rings[0][2]) * 0.5, 0.0, rings[0][0]),
        (side * (rings[-1][1] + rings[-1][2]) * 0.5, 0.0, rings[-1][0]),
    ))
    top_start = offset + (len(rings) - 1) * segments
    for index in range(segments):
        nxt = (index + 1) % segments
        faces.append((bottom, offset + nxt, offset + index))
        faces.append((top, top_start + index, top_start + nxt))


def append_pelvis_volume(vertices, faces, rings, segments: int = SEGMENTS) -> None:
    offset = len(vertices)
    for z, radius_x, front, back in rings:
        for index in range(segments):
            angle = math.tau * index / segments
            sine = math.sin(angle)
            depth = front if sine < 0.0 else back
            vertices.append((radius_x * math.cos(angle), depth * sine, z))
    for ring in range(len(rings) - 1):
        for index in range(segments):
            nxt = (index + 1) % segments
            a = offset + ring * segments + index
            b = offset + ring * segments + nxt
            c = offset + (ring + 1) * segments + nxt
            d = offset + (ring + 1) * segments + index
            faces.append((a, b, c, d))
    bottom = len(vertices)
    top = bottom + 1
    vertices.extend(((0.0, 0.0, rings[0][0]), (0.0, 0.0, rings[-1][0])))
    top_start = offset + (len(rings) - 1) * segments
    for index in range(segments):
        nxt = (index + 1) % segments
        faces.append((bottom, offset + nxt, offset + index))
        faces.append((top, top_start + index, top_start + nxt))


def open_and_level_boundaries(obj: bpy.types.Object) -> None:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    delete_faces = [
        face for face in bm.faces
        if face.calc_center_median().z > WAIST_Z or face.calc_center_median().z < HEM_Z
    ]
    if delete_faces:
        bmesh.ops.delete(bm, geom=delete_faces, context="FACES")
    loose = [vertex for vertex in bm.verts if not vertex.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    for edge in bm.edges:
        if len(edge.link_faces) != 1:
            continue
        for vertex in edge.verts:
            if vertex.co.z > 0.700:
                vertex.co.z = WAIST_Z
            elif vertex.co.z < 0.230:
                vertex.co.z = HEM_Z
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=0.00005)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-8, edges=list(bm.edges))
    zero = [face for face in bm.faces if face.calc_area() <= 1e-12]
    if zero:
        bmesh.ops.delete(bm, geom=zero, context="FACES")
    if bm.faces:
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update(calc_edges=True)


def create_union_surface(armature, body, fabric) -> bpy.types.Object:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    leg_rings = [
        (0.130, 0.031, 0.168, 0.091, 0.097),
        (0.205, 0.032, 0.166, 0.090, 0.096),
        (0.305, 0.031, 0.164, 0.089, 0.095),
        (0.405, 0.027, 0.163, 0.088, 0.095),
        (0.505, 0.017, 0.166, 0.090, 0.101),
        (0.610, 0.014, 0.160, 0.094, 0.106),
    ]
    for side in (-1, 1):
        append_leg_volume(vertices, faces, side=side, rings=leg_rings)
    append_pelvis_volume(
        vertices,
        faces,
        [
            (0.490, 0.160, 0.098, 0.112),
            (0.565, 0.162, 0.100, 0.115),
            (0.650, 0.158, 0.098, 0.112),
            (0.725, 0.151, 0.094, 0.105),
            (0.800, 0.143, 0.089, 0.098),
        ],
    )
    mesh = bpy.data.meshes.new("Cargo_Continuous_Pants_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    mesh.materials.append(fabric)
    obj = bpy.data.objects.new("Cargo_Continuous_Pants", mesh)
    bpy.context.collection.objects.link(obj)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    remesh = obj.modifiers.new("Deterministic volume union", "REMESH")
    remesh.mode = "VOXEL"
    remesh.voxel_size = VOXEL_SIZE
    remesh.use_smooth_shade = True
    bpy.ops.object.modifier_apply(modifier=remesh.name)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    for _ in range(2):
        bmesh.ops.smooth_vert(
            bm, verts=list(bm.verts), factor=0.16,
            use_axis_x=True, use_axis_y=True, use_axis_z=True,
        )
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update(calc_edges=True)
    open_and_level_boundaries(obj)
    obj.parent = armature
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True
    build.finish_skinned(obj, body, add_shape_keys=False)
    return obj


def configure_materials(fabric, panel) -> None:
    base.tune_material(fabric, base=(0.055, 0.064, 0.082), roughness=0.88)
    base.tune_material(panel, base=(0.004, 0.006, 0.012), roughness=0.26)
    for material, color, roughness, metallic in (
        (fabric, (0.055, 0.064, 0.082, 1.0), 0.88, 0.0),
        (panel, (0.004, 0.006, 0.012, 1.0), 0.26, 0.06),
    ):
        material.use_nodes = True
        shader = material.node_tree.nodes.get("Principled BSDF")
        if shader is not None:
            shader.inputs["Base Color"].default_value = color
            shader.inputs["Roughness"].default_value = roughness
            shader.inputs["Metallic"].default_value = metallic


def assign_material_regions(pants, fabric, panel) -> None:
    configure_materials(fabric, panel)
    pants.data.materials.clear()
    pants.data.materials.append(fabric)
    pants.data.materials.append(panel)
    for polygon in pants.data.polygons:
        points = [pants.data.vertices[index].co for index in polygon.vertices]
        mean_x = sum(float(point.x) for point in points) / len(points)
        mean_y = sum(float(point.y) for point in points) / len(points)
        mean_z = sum(float(point.z) for point in points) / len(points)
        waistband = mean_z >= 0.742
        knee_panel = 0.345 <= mean_z <= 0.425
        side_panel = abs(mean_x) >= 0.128 and 0.215 <= mean_z <= 0.700
        cargo_panel = abs(mean_x) >= 0.105 and abs(mean_y) >= 0.050 and 0.500 <= mean_z <= 0.645
        polygon.material_index = 1 if waistband or knee_panel or side_panel or cargo_panel else 0
    pants.data.update()


def unwrap_uv(obj) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=1.15192, island_margin=0.025)
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.data.update()


def create_outfit(body, armature, fabric, strap, metal):
    del metal
    pants = create_union_surface(armature, body, fabric)
    assign_material_regions(pants, fabric, strap)
    unwrap_uv(pants)
    return [pants]


def connected_components(obj) -> int:
    adjacency = {vertex.index: set() for vertex in obj.data.vertices}
    for edge in obj.data.edges:
        first, second = edge.vertices
        adjacency[first].add(second)
        adjacency[second].add(first)
    unseen = set(adjacency)
    count = 0
    while unseen:
        count += 1
        queue = deque([unseen.pop()])
        while queue:
            current = queue.popleft()
            for neighbor in adjacency[current]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    queue.append(neighbor)
    return count


def boundary_metrics(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    boundary = {edge for edge in bm.edges if len(edge.link_faces) == 1}
    by_vertex = {}
    for edge in boundary:
        for vertex in edge.verts:
            by_vertex.setdefault(vertex, []).append(edge)
    result = []
    while boundary:
        seed = boundary.pop()
        edges = [seed]
        stack = [seed]
        while stack:
            edge = stack.pop()
            for vertex in edge.verts:
                for neighbor in by_vertex.get(vertex, []):
                    if neighbor in boundary:
                        boundary.remove(neighbor)
                        edges.append(neighbor)
                        stack.append(neighbor)
        verts = {vertex for edge in edges for vertex in edge.verts}
        xs = [float(vertex.co.x) for vertex in verts]
        zs = [float(vertex.co.z) for vertex in verts]
        result.append({
            "edges": len(edges), "vertices": len(verts),
            "meanX": sum(xs) / len(xs), "meanZ": sum(zs) / len(zs),
            "zSpan": max(zs) - min(zs),
        })
    bm.free()
    return sorted(result, key=lambda item: float(item["meanZ"]))


def extent(obj, z0, z1):
    points = [vertex.co for vertex in obj.data.vertices if z0 <= vertex.co.z <= z1]
    if not points:
        return {"vertices": 0, "width": 0.0, "depth": 0.0}
    xs = [float(point.x) for point in points]
    ys = [float(point.y) for point in points]
    return {"vertices": len(points), "width": max(xs) - min(xs), "depth": max(ys) - min(ys)}


def degenerate_triangles(obj) -> int:
    obj.data.calc_loop_triangles()
    return sum(
        1 for triangle in obj.data.loop_triangles
        if (
            obj.data.vertices[triangle.vertices[1]].co - obj.data.vertices[triangle.vertices[0]].co
        ).cross(
            obj.data.vertices[triangle.vertices[2]].co - obj.data.vertices[triangle.vertices[0]].co
        ).length_squared <= 1e-20
    )


def maximum_edge(obj) -> float:
    return max(
        (obj.data.vertices[edge.vertices[0]].co - obj.data.vertices[edge.vertices[1]].co).length
        for edge in obj.data.edges
    )


def audit() -> dict[str, object]:
    pants = bpy.data.objects.get("Cargo_Continuous_Pants")
    garment_names = sorted(
        obj.name for obj in bpy.data.objects
        if obj.type == "MESH" and not obj.name.startswith("SiroinoSotai_PC") and obj.name != "Studio_Floor"
    )
    checks = {"garmentMeshNames": garment_names}
    if pants is None:
        return {"schemaVersion": 1, "passed": False, "checks": checks}
    pants.data.calc_loop_triangles()
    xs = [float(vertex.co.x) for vertex in pants.data.vertices]
    ys = [float(vertex.co.y) for vertex in pants.data.vertices]
    zs = [float(vertex.co.z) for vertex in pants.data.vertices]
    coordinates = [value for vertex in pants.data.vertices for value in vertex.co]
    boundaries = boundary_metrics(pants)
    bands = {
        "waist": extent(pants, 0.735, 0.790),
        "upperThigh": extent(pants, 0.470, 0.570),
        "knee": extent(pants, 0.315, 0.415),
        "hem": extent(pants, HEM_Z, 0.205),
    }
    degenerates = degenerate_triangles(pants)
    max_edge = maximum_edge(pants)
    material_faces = [0, 0]
    for polygon in pants.data.polygons:
        if polygon.material_index < 2:
            material_faces[polygon.material_index] += 1
    total_faces = max(1, sum(material_faces))
    shape_keys = 0 if pants.data.shape_keys is None else max(0, len(pants.data.shape_keys.key_blocks) - 1)
    foot_intrusions = sum(
        1 for vertex in pants.data.vertices
        if vertex.co.z < HEM_Z - 1e-5 or (vertex.co.z < 0.205 and abs(vertex.co.y) > 0.115)
    )
    metrics = {
        "vertices": len(pants.data.vertices), "triangles": len(pants.data.loop_triangles),
        "minimumZ": min(zs, default=0.0), "maximumZ": max(zs, default=0.0),
        "totalWidth": max(xs, default=0.0) - min(xs, default=0.0),
        "totalDepth": max(ys, default=0.0) - min(ys, default=0.0),
        "maximumEdgeLength": max_edge, "degenerateTriangles": degenerates,
        "uvLayers": len(pants.data.uv_layers), "materialSlots": len(pants.data.materials),
        "materialFaceCounts": material_faces, "shapeKeys": shape_keys,
        "connectedComponents": connected_components(pants), "boundaryComponents": boundaries,
        "footIntrusionVertices": foot_intrusions, "bands": bands,
    }
    checks["metrics"] = metrics
    expected_boundaries = (
        len(boundaries) == 3
        and sum(1 for item in boundaries if float(item["meanZ"]) > 0.700) == 1
        and sum(1 for item in boundaries if float(item["meanZ"]) < 0.230) == 2
        and all(float(item["zSpan"]) <= 0.002 for item in boundaries)
    )
    profile_pass = (
        abs(float(bands["upperThigh"]["width"]) - float(bands["knee"]["width"])) <= 0.040
        and abs(float(bands["knee"]["width"]) - float(bands["hem"]["width"])) <= 0.035
        and abs(float(bands["upperThigh"]["depth"]) - float(bands["knee"]["depth"])) <= 0.030
        and abs(float(bands["knee"]["depth"]) - float(bands["hem"]["depth"])) <= 0.025
    )
    checks.update({
        "singleShellOnly": garment_names == ["Cargo_Continuous_Pants"],
        "singleConnectedSurfacePassed": connected_components(pants) == 1,
        "finiteCoordinatesPassed": all(math.isfinite(float(value)) for value in coordinates),
        "boundaryContractPassed": expected_boundaries,
        "spikeGuardPassed": max_edge <= 0.030,
        "topologyPassed": degenerates == 0,
        "uvPassed": len(pants.data.uv_layers) > 0,
        "materialSeparationPassed": len(pants.data.materials) >= 2 and min(material_faces) / total_faces >= 0.08,
        "shapeKeyIsolationPassed": shape_keys == 0,
        "footAndFloorClearancePassed": foot_intrusions == 0 and min(zs, default=0.0) >= HEM_Z - 1e-5,
        "controlledVolumePassed": 0.315 <= metrics["totalWidth"] <= 0.365 and 0.175 <= metrics["totalDepth"] <= 0.235,
        "waistFitPassed": float(bands["waist"]["width"]) <= 0.305 and float(bands["waist"]["depth"]) <= 0.205,
        "upperThighVolumePassed": float(bands["upperThigh"]["width"]) <= 0.345 and float(bands["upperThigh"]["depth"]) <= 0.220,
        "profileContinuityPassed": profile_pass,
    })
    required = [
        "singleShellOnly", "singleConnectedSurfacePassed", "finiteCoordinatesPassed",
        "boundaryContractPassed", "spikeGuardPassed", "topologyPassed", "uvPassed",
        "materialSeparationPassed", "shapeKeyIsolationPassed", "footAndFloorClearancePassed",
        "controlledVolumePassed", "waistFitPassed", "upperThighVolumePassed", "profileContinuityPassed",
    ]
    return {"schemaVersion": 1, "passed": all(bool(checks[name]) for name in required), "checks": checks}


def record(report) -> None:
    _, job = build.c.load_job()
    path = build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    manifest["status"] = "WORKING"
    manifest["designRevision"] = "v35-parametric-voxel-union"
    manifest["wearabilityAudit"] = report
    gates = manifest.setdefault("technicalGates", {})
    result = "PASS" if report.get("passed") is True else "FAIL"
    gates["blender"] = result
    gates["fbx"] = result
    gates["uvMapping"] = result
    gates["latestGeometryRender"] = result
    gates["exactBodyPoseRenders"] = "PENDING"
    gates["humanVisualReview"] = "PENDING"
    gates["humanPoseReview"] = "PENDING"
    gates["humanRuntimeReview"] = "PENDING"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


build.create_outfit = create_outfit

if __name__ == "__main__":
    clear_stale_render_evidence()
    build.main()
    result = audit()
    record(result)
    base.save_distribution_blend()
    if result.get("passed") is not True:
        raise RuntimeError(f"v35 parametric geometry audit failed: {result}")
    raise SystemExit(0)
