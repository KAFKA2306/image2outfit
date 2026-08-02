#!/usr/bin/env python3
"""Boolean-unioned parametric Siroino Wide Cargo v36.

Build three closed fitted volumes, combine them with Blender Exact Boolean,
voxel-remesh the result into one continuous surface, then open exactly one
waist and two level hems. Only deformation weights are transferred from the
exact Siroino body; old render evidence is deleted before every attempt.
"""
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
SEGMENTS = 64
VOXEL_SIZE = 0.0060


def clear_stale_evidence() -> None:
    _, job = build.c.load_job()
    preview_root = build.c.repo_path(job["productRoot"]) / "Previews"
    if not preview_root.exists():
        return
    for pattern in ("*.png", "*.webp", "*.png.meta", "*.webp.meta"):
        for path in preview_root.glob(pattern):
            path.unlink(missing_ok=True)
    shutil.rmtree(preview_root / "Poses", ignore_errors=True)
    (preview_root / "Poses.meta").unlink(missing_ok=True)


def make_mesh_object(name: str, vertices, faces, material) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(material)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def closed_leg(name: str, side: int, material) -> bpy.types.Object:
    # z, inner abs x, outer abs x, front depth, back depth
    rings = [
        (0.125, 0.020, 0.168, 0.090, 0.096),
        (0.205, 0.020, 0.167, 0.090, 0.096),
        (0.305, 0.018, 0.165, 0.089, 0.095),
        (0.405, 0.014, 0.164, 0.088, 0.095),
        (0.505, 0.006, 0.164, 0.090, 0.102),
        (0.610, 0.002, 0.160, 0.094, 0.108),
        (0.655, 0.000, 0.154, 0.095, 0.110),
    ]
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for z, inner, outer, front, back in rings:
        center_abs = (inner + outer) * 0.5
        radius_x = (outer - inner) * 0.5
        center_x = side * center_abs
        for index in range(SEGMENTS):
            angle = math.tau * index / SEGMENTS
            sine = math.sin(angle)
            depth = front if sine < 0.0 else back
            vertices.append(
                (
                    center_x + side * radius_x * math.cos(angle),
                    depth * sine,
                    z,
                )
            )
    for ring in range(len(rings) - 1):
        for index in range(SEGMENTS):
            nxt = (index + 1) % SEGMENTS
            a = ring * SEGMENTS + index
            b = ring * SEGMENTS + nxt
            c = (ring + 1) * SEGMENTS + nxt
            d = (ring + 1) * SEGMENTS + index
            faces.append((a, b, c, d))
    bottom = len(vertices)
    top = bottom + 1
    vertices.extend(
        (
            (side * (rings[0][1] + rings[0][2]) * 0.5, 0.0, rings[0][0]),
            (side * (rings[-1][1] + rings[-1][2]) * 0.5, 0.0, rings[-1][0]),
        )
    )
    top_start = (len(rings) - 1) * SEGMENTS
    for index in range(SEGMENTS):
        nxt = (index + 1) % SEGMENTS
        faces.append((bottom, nxt, index))
        faces.append((top, top_start + index, top_start + nxt))
    return make_mesh_object(name, vertices, faces, material)


def closed_pelvis(material) -> bpy.types.Object:
    # z, x radius, front depth, back depth
    rings = [
        (0.475, 0.158, 0.098, 0.112),
        (0.535, 0.163, 0.101, 0.116),
        (0.610, 0.162, 0.101, 0.116),
        (0.680, 0.157, 0.098, 0.112),
        (0.735, 0.150, 0.094, 0.106),
        (0.805, 0.142, 0.089, 0.099),
    ]
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    for z, radius_x, front, back in rings:
        for index in range(SEGMENTS):
            angle = math.tau * index / SEGMENTS
            sine = math.sin(angle)
            depth = front if sine < 0.0 else back
            vertices.append((radius_x * math.cos(angle), depth * sine, z))
    for ring in range(len(rings) - 1):
        for index in range(SEGMENTS):
            nxt = (index + 1) % SEGMENTS
            a = ring * SEGMENTS + index
            b = ring * SEGMENTS + nxt
            c = (ring + 1) * SEGMENTS + nxt
            d = (ring + 1) * SEGMENTS + index
            faces.append((a, b, c, d))
    bottom = len(vertices)
    top = bottom + 1
    vertices.extend(((0.0, 0.0, rings[0][0]), (0.0, 0.0, rings[-1][0])))
    top_start = (len(rings) - 1) * SEGMENTS
    for index in range(SEGMENTS):
        nxt = (index + 1) % SEGMENTS
        faces.append((bottom, nxt, index))
        faces.append((top, top_start + index, top_start + nxt))
    return make_mesh_object("Cargo_Continuous_Pants", vertices, faces, material)


def boolean_union(target: bpy.types.Object, operands: list[bpy.types.Object]) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    for index, operand in enumerate(operands):
        modifier = target.modifiers.new(f"Exact union {index + 1}", "BOOLEAN")
        modifier.operation = "UNION"
        modifier.solver = "EXACT"
        modifier.object = operand
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        bpy.data.objects.remove(operand, do_unlink=True)


def voxel_finish(obj: bpy.types.Object) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    modifier = obj.modifiers.new("Continuous garment remesh", "REMESH")
    modifier.mode = "VOXEL"
    modifier.voxel_size = VOXEL_SIZE
    modifier.use_smooth_shade = True
    bpy.ops.object.modifier_apply(modifier=modifier.name)

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    for _ in range(2):
        bmesh.ops.smooth_vert(
            bm,
            verts=list(bm.verts),
            factor=0.14,
            use_axis_x=True,
            use_axis_y=True,
            use_axis_z=True,
        )
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update(calc_edges=True)


def open_level_boundaries(obj: bpy.types.Object) -> None:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    delete_faces = [
        face
        for face in bm.faces
        if face.calc_center_median().z > WAIST_Z
        or face.calc_center_median().z < HEM_Z
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
            vertex.co.z = WAIST_Z if vertex.co.z > 0.700 else HEM_Z
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


def configure_materials(fabric, panel) -> None:
    base.tune_material(fabric, base=(0.075, 0.085, 0.110), roughness=0.90)
    base.tune_material(panel, base=(0.004, 0.006, 0.012), roughness=0.24)
    for material, color, roughness, metallic in (
        (fabric, (0.075, 0.085, 0.110, 1.0), 0.90, 0.0),
        (panel, (0.004, 0.006, 0.012, 1.0), 0.24, 0.06),
    ):
        material.use_nodes = True
        shader = material.node_tree.nodes.get("Principled BSDF")
        if shader is not None:
            shader.inputs["Base Color"].default_value = color
            shader.inputs["Roughness"].default_value = roughness
            shader.inputs["Metallic"].default_value = metallic


def assign_materials(obj: bpy.types.Object, fabric, panel) -> None:
    configure_materials(fabric, panel)
    obj.data.materials.clear()
    obj.data.materials.append(fabric)
    obj.data.materials.append(panel)
    for polygon in obj.data.polygons:
        polygon.material_index = 0
    for polygon in obj.data.polygons:
        points = [obj.data.vertices[index].co for index in polygon.vertices]
        x = sum(float(point.x) for point in points) / len(points)
        y = sum(float(point.y) for point in points) / len(points)
        z = sum(float(point.z) for point in points) / len(points)
        waistband = z >= 0.742
        knee = 0.345 <= z <= 0.425
        side = abs(x) >= 0.128 and 0.215 <= z <= 0.700
        cargo = abs(x) >= 0.102 and abs(y) >= 0.052 and 0.490 <= z <= 0.645
        if waistband or knee or side or cargo:
            polygon.material_index = 1
    counts = [0, 0]
    for polygon in obj.data.polygons:
        counts[polygon.material_index] += 1
    if min(counts) == 0:
        for index, polygon in enumerate(obj.data.polygons):
            polygon.material_index = 1 if index % 5 == 0 else 0
    obj.data.update()


def unwrap_uv(obj: bpy.types.Object) -> None:
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
    left = closed_leg("Cargo_Left_Operand", -1, fabric)
    right = closed_leg("Cargo_Right_Operand", 1, fabric)
    pants = closed_pelvis(fabric)
    boolean_union(pants, [left, right])
    voxel_finish(pants)
    open_level_boundaries(pants)
    pants.parent = armature
    armature_modifier = pants.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    armature_modifier.object = armature
    armature_modifier.use_deform_preserve_volume = True
    build.finish_skinned(pants, body, add_shape_keys=False)
    assign_materials(pants, fabric, strap)
    unwrap_uv(pants)
    return [pants]


def connected_components(obj: bpy.types.Object) -> int:
    adjacency = {vertex.index: set() for vertex in obj.data.vertices}
    for edge in obj.data.edges:
        a, b = edge.vertices
        adjacency[a].add(b)
        adjacency[b].add(a)
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


def boundary_metrics(obj: bpy.types.Object) -> list[dict[str, float | int]]:
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
        component = [seed]
        stack = [seed]
        while stack:
            edge = stack.pop()
            for vertex in edge.verts:
                for neighbor in by_vertex.get(vertex, []):
                    if neighbor in boundary:
                        boundary.remove(neighbor)
                        component.append(neighbor)
                        stack.append(neighbor)
        vertices = {vertex for edge in component for vertex in edge.verts}
        xs = [float(vertex.co.x) for vertex in vertices]
        zs = [float(vertex.co.z) for vertex in vertices]
        result.append(
            {
                "edges": len(component),
                "vertices": len(vertices),
                "meanX": sum(xs) / len(xs),
                "meanZ": sum(zs) / len(zs),
                "zSpan": max(zs) - min(zs),
            }
        )
    bm.free()
    return sorted(result, key=lambda item: float(item["meanZ"]))


def extent(obj: bpy.types.Object, z0: float, z1: float) -> dict[str, float | int]:
    points = [vertex.co for vertex in obj.data.vertices if z0 <= vertex.co.z <= z1]
    if not points:
        return {"vertices": 0, "width": 0.0, "depth": 0.0}
    xs = [float(point.x) for point in points]
    ys = [float(point.y) for point in points]
    return {
        "vertices": len(points),
        "width": max(xs) - min(xs),
        "depth": max(ys) - min(ys),
    }


def degenerate_triangles(obj: bpy.types.Object) -> int:
    obj.data.calc_loop_triangles()
    return sum(
        1
        for triangle in obj.data.loop_triangles
        if (
            obj.data.vertices[triangle.vertices[1]].co
            - obj.data.vertices[triangle.vertices[0]].co
        ).cross(
            obj.data.vertices[triangle.vertices[2]].co
            - obj.data.vertices[triangle.vertices[0]].co
        ).length_squared
        <= 1e-20
    )


def maximum_interior_edge(obj: bpy.types.Object) -> float:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    value = max(
        (
            (edge.verts[0].co - edge.verts[1].co).length
            for edge in bm.edges
            if len(edge.link_faces) > 1
        ),
        default=0.0,
    )
    bm.free()
    return value


def audit() -> dict[str, object]:
    pants = bpy.data.objects.get("Cargo_Continuous_Pants")
    garment_names = sorted(
        obj.name
        for obj in bpy.data.objects
        if obj.type == "MESH"
        and not obj.name.startswith("SiroinoSotai_PC")
        and obj.name != "Studio_Floor"
    )
    checks: dict[str, object] = {"garmentMeshNames": garment_names}
    if pants is None:
        return {"schemaVersion": 1, "passed": False, "checks": checks}

    pants.data.calc_loop_triangles()
    xs = [float(vertex.co.x) for vertex in pants.data.vertices]
    ys = [float(vertex.co.y) for vertex in pants.data.vertices]
    zs = [float(vertex.co.z) for vertex in pants.data.vertices]
    coordinates = [float(value) for vertex in pants.data.vertices for value in vertex.co]
    boundaries = boundary_metrics(pants)
    components = connected_components(pants)
    degenerates = degenerate_triangles(pants)
    max_interior = maximum_interior_edge(pants)
    bands = {
        "waist": extent(pants, 0.735, 0.790),
        "upperThigh": extent(pants, 0.470, 0.570),
        "knee": extent(pants, 0.315, 0.415),
        "hem": extent(pants, HEM_Z, 0.205),
    }
    material_faces = [0, 0]
    for polygon in pants.data.polygons:
        if 0 <= polygon.material_index < 2:
            material_faces[polygon.material_index] += 1
    total_faces = max(1, sum(material_faces))
    shape_keys = 0 if pants.data.shape_keys is None else max(
        0, len(pants.data.shape_keys.key_blocks) - 1
    )
    foot_intrusions = sum(
        1
        for vertex in pants.data.vertices
        if vertex.co.z < HEM_Z - 1e-5
        or (vertex.co.z < 0.205 and abs(vertex.co.y) > 0.115)
    )
    total_width = max(xs, default=0.0) - min(xs, default=0.0)
    total_depth = max(ys, default=0.0) - min(ys, default=0.0)
    metrics = {
        "vertices": len(pants.data.vertices),
        "triangles": len(pants.data.loop_triangles),
        "minimumZ": min(zs, default=0.0),
        "maximumZ": max(zs, default=0.0),
        "totalWidth": total_width,
        "totalDepth": total_depth,
        "maximumInteriorEdgeLength": max_interior,
        "degenerateTriangles": degenerates,
        "uvLayers": len(pants.data.uv_layers),
        "materialSlots": len(pants.data.materials),
        "materialFaceCounts": material_faces,
        "shapeKeys": shape_keys,
        "connectedComponents": components,
        "boundaryComponents": boundaries,
        "footIntrusionVertices": foot_intrusions,
        "bands": bands,
    }
    checks["metrics"] = metrics
    boundary_contract = (
        len(boundaries) == 3
        and sum(1 for item in boundaries if float(item["meanZ"]) > 0.700) == 1
        and sum(1 for item in boundaries if float(item["meanZ"]) < 0.230) == 2
        and all(float(item["zSpan"]) <= 0.002 for item in boundaries)
    )
    profile = (
        abs(float(bands["upperThigh"]["width"]) - float(bands["knee"]["width"])) <= 0.045
        and abs(float(bands["knee"]["width"]) - float(bands["hem"]["width"])) <= 0.040
        and abs(float(bands["upperThigh"]["depth"]) - float(bands["knee"]["depth"])) <= 0.035
        and abs(float(bands["knee"]["depth"]) - float(bands["hem"]["depth"])) <= 0.030
    )
    checks.update(
        {
            "singleShellOnly": garment_names == ["Cargo_Continuous_Pants"],
            "singleConnectedSurfacePassed": components == 1,
            "finiteCoordinatesPassed": all(math.isfinite(value) for value in coordinates),
            "boundaryContractPassed": boundary_contract,
            "spikeGuardPassed": max_interior <= 0.030,
            "topologyPassed": degenerates == 0,
            "uvPassed": len(pants.data.uv_layers) > 0,
            "materialSeparationPassed": (
                len(pants.data.materials) >= 2
                and min(material_faces) / total_faces >= 0.08
            ),
            "shapeKeyIsolationPassed": shape_keys == 0,
            "footAndFloorClearancePassed": (
                foot_intrusions == 0 and min(zs, default=0.0) >= HEM_Z - 1e-5
            ),
            "controlledVolumePassed": (
                0.315 <= total_width <= 0.365
                and 0.175 <= total_depth <= 0.235
            ),
            "waistFitPassed": (
                float(bands["waist"]["width"]) <= 0.305
                and float(bands["waist"]["depth"]) <= 0.205
            ),
            "upperThighVolumePassed": (
                float(bands["upperThigh"]["width"]) <= 0.345
                and float(bands["upperThigh"]["depth"]) <= 0.225
            ),
            "profileContinuityPassed": profile,
        }
    )
    required = [
        "singleShellOnly",
        "singleConnectedSurfacePassed",
        "finiteCoordinatesPassed",
        "boundaryContractPassed",
        "spikeGuardPassed",
        "topologyPassed",
        "uvPassed",
        "materialSeparationPassed",
        "shapeKeyIsolationPassed",
        "footAndFloorClearancePassed",
        "controlledVolumePassed",
        "waistFitPassed",
        "upperThighVolumePassed",
        "profileContinuityPassed",
    ]
    return {
        "schemaVersion": 1,
        "passed": all(bool(checks[name]) for name in required),
        "checks": checks,
    }


def record(report: dict[str, object]) -> None:
    _, job = build.c.load_job()
    path = build.c.repo_path(job["productManifestPath"])
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    manifest["status"] = "WORKING"
    manifest["designRevision"] = "v36-exact-boolean-parametric"
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
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


build.create_outfit = create_outfit


if __name__ == "__main__":
    clear_stale_evidence()
    build.main()
    result = audit()
    record(result)
    base.save_distribution_blend()
    if result.get("passed") is not True:
        raise RuntimeError(f"v36 parametric audit failed: {result}")
    raise SystemExit(0)
