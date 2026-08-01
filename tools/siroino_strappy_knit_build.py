#!/usr/bin/env python3
"""Build the SiroinoSotai strappy rib-knit outfit and its review renders.

The script is executed inside Blender (or the official ``bpy`` wheel) and is
intentionally tied to the exact CC0 SiroinoSotai v1.0 body surface.  Garment
panels are derived from the supplied body topology, offset along body normals,
and receive the source armature weights plus the commonly used body-size shape
keys.  Decorative straps and hardware are authored as real geometry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import bpy
import bmesh
from mathutils import Vector
from mathutils.kdtree import KDTree
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
SHAPE_KEYS = (
    "All_Slim",
    "Chest_Slim",
    "Hips_Slim",
    "UpperLeg_Slim",
    "Breasts_flat",
    "All_M",
    "Chest_M",
    "All_L",
    "Chest_L",
    "Hips_01_L",
    "UpperLeg_L",
    "Breasts_L",
    "Breasts_LL",
    "Breasts_LLL",
    "Breasts_In",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def repo_path(value: str) -> Path:
    path = (ROOT / value).resolve()
    if path != ROOT and ROOT not in path.parents:
        raise ValueError(f"path escapes repository: {value}")
    return path


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    return parser.parse_args(raw)


def load_job() -> tuple[Path, dict]:
    args = parse_args()
    path = Path(args.job).resolve()
    return path, json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def make_texture_maps(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    size = 1024
    maps: dict[str, Path] = {}

    def save_rgb(name: str, pixels: list[tuple[int, int, int]]) -> Path:
        path = directory / name
        image = Image.new("RGB", (size, size))
        image.putdata(pixels)
        image.save(path, optimize=True)
        maps[name] = path
        return path

    ivory_albedo: list[tuple[int, int, int]] = []
    ivory_normal: list[tuple[int, int, int]] = []
    ivory_rough: list[tuple[int, int, int]] = []
    black_albedo: list[tuple[int, int, int]] = []
    black_normal: list[tuple[int, int, int]] = []
    black_rough: list[tuple[int, int, int]] = []
    for y in range(size):
        yarn = math.sin(y * math.tau / 7.0) * 0.9
        for x in range(size):
            phase = x * math.tau / 24.0
            ridge = 0.5 + 0.5 * math.cos(phase)
            fine = 0.5 + 0.5 * math.sin(x * math.tau / 5.0 + y * 0.17)
            shade = int(226 + 22 * ridge + 2 * fine + yarn)
            ivory_albedo.append((min(255, shade + 3), min(255, shade + 2), shade))
            nx = int(128 + 58 * math.sin(phase))
            ivory_normal.append((max(0, min(255, nx)), 128, 246))
            rough = int(151 + 17 * (1.0 - ridge) + 5 * fine)
            ivory_rough.append((rough, rough, rough))

            micro = 0.5 + 0.5 * math.sin(x * 0.71 + y * 0.43)
            satin = int(15 + 8 * ridge + 3 * micro)
            black_albedo.append((satin, satin, satin + 2))
            black_normal.append((int(128 + 9 * math.sin(phase)), 128, 253))
            black_r = int(142 + 18 * micro)
            black_rough.append((black_r, black_r, black_r))

    save_rgb("ivory_knit_albedo.png", ivory_albedo)
    save_rgb("ivory_knit_normal.png", ivory_normal)
    save_rgb("ivory_knit_roughness.png", ivory_rough)
    save_rgb("black_satin_albedo.png", black_albedo)
    save_rgb("black_satin_normal.png", black_normal)
    save_rgb("black_satin_roughness.png", black_rough)
    return maps


def image_node(nodes, path: Path, *, non_color: bool = False):
    node = nodes.new("ShaderNodeTexImage")
    node.image = bpy.data.images.load(str(path), check_existing=True)
    if non_color:
        node.image.colorspace_settings.name = "Non-Color"
    node.interpolation = "Linear"
    return node


def textured_material(
    name: str,
    albedo: Path,
    normal: Path,
    roughness: Path,
    *,
    normal_strength: float,
    sheen: float,
) -> bpy.types.Material:
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Metallic"].default_value = 0.0
    shader.inputs["IOR"].default_value = 1.45
    if "Sheen Weight" in shader.inputs:
        shader.inputs["Sheen Weight"].default_value = sheen
        shader.inputs["Sheen Roughness"].default_value = 0.65
    color = image_node(nodes, albedo)
    rough = image_node(nodes, roughness, non_color=True)
    normal_image = image_node(nodes, normal, non_color=True)
    normal_map = nodes.new("ShaderNodeNormalMap")
    normal_map.inputs["Strength"].default_value = normal_strength
    links.new(color.outputs["Color"], shader.inputs["Base Color"])
    links.new(rough.outputs["Color"], shader.inputs["Roughness"])
    links.new(normal_image.outputs["Color"], normal_map.inputs["Color"])
    links.new(normal_map.outputs["Normal"], shader.inputs["Normal"])
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    material.diffuse_color = (
        (0.92, 0.90, 0.86, 1.0)
        if "Ivory" in name
        else (0.012, 0.013, 0.018, 1.0)
    )
    return material


def plain_material(
    name: str,
    color: tuple[float, float, float, float],
    *,
    roughness: float,
    metallic: float = 0.0,
) -> bpy.types.Material:
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.diffuse_color = color
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = color
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = metallic
    if metallic:
        shader.inputs["Coat Weight"].default_value = 0.28
        shader.inputs["Coat Roughness"].default_value = 0.12
    return material


def set_skin_material(body: bpy.types.Object) -> None:
    skin = plain_material("Preview_Skin", (0.43, 0.18, 0.11, 1.0), roughness=0.52)
    shader = skin.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Subsurface Weight"].default_value = 0.08
    body.data.materials.clear()
    body.data.materials.append(skin)


def mesh_world_vertex(body: bpy.types.Object, index: int, key=None) -> Vector:
    coordinate = key.data[index].co if key else body.data.vertices[index].co
    return body.matrix_world @ coordinate


def extract_surface(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    name: str,
    predicate: Callable[[Vector], bool],
    material: bpy.types.Material,
    offset: float,
) -> bpy.types.Object:
    # Imported FBX vertex normals are already available in Blender 4.x.  The
    # legacy ``calc_normals_split`` API was removed in Blender 4.1.
    source_uv = body.data.uv_layers.active
    selected = []
    used: dict[int, int] = {}
    vertices: list[Vector] = []
    source_indices: list[int] = []
    faces: list[list[int]] = []
    face_uvs: list[list[tuple[float, float]]] = []

    for polygon in body.data.polygons:
        center = body.matrix_world @ polygon.center
        if not predicate(center):
            continue
        selected.append(polygon.index)
        face = []
        uvs = []
        for loop_index in polygon.loop_indices:
            source_index = body.data.loops[loop_index].vertex_index
            if source_index not in used:
                source = body.data.vertices[source_index]
                normal = (body.matrix_world.to_3x3() @ source.normal).normalized()
                used[source_index] = len(vertices)
                vertices.append(mesh_world_vertex(body, source_index) + normal * offset)
                source_indices.append(source_index)
            face.append(used[source_index])
            if source_uv:
                uv = source_uv.data[loop_index].uv
                uvs.append((float(uv.x), float(uv.y)))
            else:
                co = mesh_world_vertex(body, source_index)
                uvs.append(((co.x + 0.18) / 0.36, co.z))
        faces.append(face)
        face_uvs.append(uvs)

    if not faces:
        raise RuntimeError(f"surface selection produced no faces: {name}")
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    edge_counts: Counter[tuple[int, int]] = Counter()
    for face in faces:
        for index in range(len(face)):
            edge_counts[tuple(sorted((face[index], face[(index + 1) % len(face)])))] += 1
    boundary_neighbors: dict[int, set[int]] = defaultdict(set)
    for (a, b), count in edge_counts.items():
        if count == 1:
            boundary_neighbors[a].add(b)
            boundary_neighbors[b].add(a)
    for _ in range(5):
        current = [vertex.co.copy() for vertex in mesh.vertices]
        updates = {}
        for index, neighbors in boundary_neighbors.items():
            if len(neighbors) != 2:
                continue
            average = sum((current[item] for item in neighbors), Vector()) / 2.0
            updates[index] = current[index].lerp(average, 0.34)
        for index, coordinate in updates.items():
            mesh.vertices[index].co = coordinate
    mesh.update(calc_edges=True)
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for polygon, uvs in zip(mesh.polygons, face_uvs):
        for loop_index, uv in zip(polygon.loop_indices, uvs):
            uv_layer.data[loop_index].uv = uv
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = armature
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True

    groups = {group.name: obj.vertex_groups.new(name=group.name) for group in body.vertex_groups}
    for new_index, source_index in enumerate(source_indices):
        assignments = body.data.vertices[source_index].groups
        total = sum(item.weight for item in assignments)
        if total <= 0:
            groups["Hips"].add([new_index], 1.0, "REPLACE")
            continue
        for item in assignments:
            groups[body.vertex_groups[item.group].name].add(
                [new_index], item.weight / total, "REPLACE"
            )
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    solidify = obj.modifiers.new("Fabric thickness", "SOLIDIFY")
    solidify.thickness = 0.0014
    solidify.offset = 0.0
    solidify.use_even_offset = True
    while obj.modifiers.find(solidify.name) > 0:
        bpy.ops.object.modifier_move_up(modifier=solidify.name)
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    bevel = obj.modifiers.new("Finished edges", "BEVEL")
    bevel.width = 0.00065
    bevel.segments = 2
    while obj.modifiers.find(bevel.name) > 0:
        bpy.ops.object.modifier_move_up(modifier=bevel.name)
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-7, edges=list(bm.edges))
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    zero_area = [face for face in bm.faces if face.calc_area() <= 1e-12]
    if zero_area:
        bmesh.ops.delete(bm, geom=zero_area, context="FACES")
    loose = [vertex for vertex in bm.verts if not vertex.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bm.to_mesh(mesh)
    bm.free()
    mesh.update(calc_edges=True)

    # Blender can retain zero-area loop triangles after converting a cleaned
    # bmesh back to a mesh (notably along closely clipped body-surface seams).
    # Remove the owning polygons once more using the exact loop-triangle audit
    # used by the release metrics so the exported FBX cannot inherit them.
    mesh.calc_loop_triangles()
    degenerate_polygons = {
        triangle.polygon_index
        for triangle in mesh.loop_triangles
        if (
            (mesh.vertices[triangle.vertices[1]].co - mesh.vertices[triangle.vertices[0]].co)
            .cross(mesh.vertices[triangle.vertices[2]].co - mesh.vertices[triangle.vertices[0]].co)
            .length_squared
            <= 1e-20
        )
    }
    if degenerate_polygons:
        cleanup = bmesh.new()
        cleanup.from_mesh(mesh)
        cleanup.faces.ensure_lookup_table()
        doomed = [cleanup.faces[index] for index in sorted(degenerate_polygons)]
        bmesh.ops.delete(cleanup, geom=doomed, context="FACES")
        loose = [vertex for vertex in cleanup.verts if not vertex.link_faces]
        if loose:
            bmesh.ops.delete(cleanup, geom=loose, context="VERTS")
        cleanup.to_mesh(mesh)
        cleanup.free()
        mesh.update(calc_edges=True)
    for vertex in mesh.vertices:
        assignments = list(vertex.groups)
        total = sum(item.weight for item in assignments if item.weight > 1e-8)
        if total <= 0:
            fallback = "Chest" if vertex.co.z > 0.86 else "Hips"
            obj.vertex_groups[fallback].add([vertex.index], 1.0, "REPLACE")
            continue
        for item in assignments:
            obj.vertex_groups[item.group].add(
                [vertex.index], item.weight / total, "REPLACE"
            )
    obj.select_set(False)
    return obj


def ellipse_points(
    center: tuple[float, float, float],
    radii: tuple[float, float],
    count: int = 64,
    *,
    start: float = 0.0,
    end: float = math.tau,
) -> list[tuple[float, float, float]]:
    cx, cy, cz = center
    rx, ry = radii
    return [
        (cx + rx * math.cos(start + (end - start) * index / count),
         cy + ry * math.sin(start + (end - start) * index / count), cz)
        for index in range(count)
    ]


def curve_tube(
    name: str,
    points: Iterable[tuple[float, float, float] | Vector],
    radius: float,
    material: bpy.types.Material,
    armature: bpy.types.Object,
    group: str,
    *,
    cyclic: bool = False,
    resolution: int = 3,
) -> bpy.types.Object:
    points = [Vector(point) for point in points]
    curve = bpy.data.curves.new(name=f"{name}_Curve", type="CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 2
    curve.bevel_depth = radius
    curve.bevel_resolution = resolution
    curve.fill_mode = "FULL"
    curve.use_fill_caps = True
    curve.resolution_u = 3
    curve.materials.append(material)
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for item, point in zip(spline.points, points):
        item.co = (*point, 1.0)
    spline.use_cyclic_u = cyclic
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.convert(target="MESH")
    obj = bpy.context.active_object
    obj.parent = armature
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    vertex_group = obj.vertex_groups.new(name=group)
    vertex_group.add(range(len(obj.data.vertices)), 1.0, "REPLACE")
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    obj.select_set(False)
    return obj


def collar_mesh(
    material: bpy.types.Material, armature: bpy.types.Object
) -> bpy.types.Object:
    segments = 72
    rings = (
        (0.046, 0.038, 1.032),
        (0.046, 0.038, 1.108),
        (0.041, 0.033, 1.108),
        (0.041, 0.033, 1.032),
    )
    vertices = []
    for rx, ry, z in rings:
        vertices.extend((rx * math.cos(i * math.tau / segments), ry * math.sin(i * math.tau / segments) - 0.006, z) for i in range(segments))
    faces = []
    for ring in range(len(rings)):
        next_ring = (ring + 1) % len(rings)
        for i in range(segments):
            j = (i + 1) % segments
            faces.append((ring * segments + i, ring * segments + j, next_ring * segments + j, next_ring * segments + i))
    mesh = bpy.data.meshes.new("Ribbed_Collar_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    uv = mesh.uv_layers.new(name="UVMap")
    for poly in mesh.polygons:
        for loop_index in poly.loop_indices:
            vertex = mesh.vertices[mesh.loops[loop_index].vertex_index].co
            angle = (math.atan2(vertex.y + 0.006, vertex.x) / math.tau) % 1.0
            uv.data[loop_index].uv = (angle, (vertex.z - 1.032) / 0.076)
    mesh.materials.append(material)
    obj = bpy.data.objects.new("Ribbed_High_Collar", mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = armature
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    group = obj.vertex_groups.new(name="Neck")
    group.add(range(len(mesh.vertices)), 1.0, "REPLACE")
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    return obj


def rigid_mesh_weight(obj: bpy.types.Object, armature: bpy.types.Object, group: str) -> None:
    obj.parent = armature
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    vertex_group = obj.vertex_groups.new(name=group)
    vertex_group.add(range(len(obj.data.vertices)), 1.0, "REPLACE")


def torus(
    name: str,
    location: tuple[float, float, float],
    major_radius: float,
    minor_radius: float,
    material: bpy.types.Material,
    armature: bpy.types.Object,
    group: str,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_torus_add(
        align="WORLD",
        major_segments=40,
        minor_segments=10,
        location=location,
        rotation=(math.pi / 2, 0.0, 0.0),
        major_radius=major_radius,
        minor_radius=minor_radius,
    )
    obj = bpy.context.active_object
    obj.name = name
    obj.data.materials.append(material)
    rigid_mesh_weight(obj, armature, group)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    return obj


def heart_curve(
    name: str,
    center: tuple[float, float, float],
    scale: float,
    material: bpy.types.Material,
    armature: bpy.types.Object,
    group: str,
) -> bpy.types.Object:
    cx, cy, cz = center
    points = []
    for index in range(65):
        t = math.tau * index / 64
        x = 16 * math.sin(t) ** 3
        z = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        points.append((cx + scale * x, cy, cz + scale * z))
    return curve_tube(name, points, scale * 1.35, material, armature, group, cyclic=True, resolution=3)


def cube_pendant(
    material: bpy.types.Material, armature: bpy.types.Object
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(location=(0.0, -0.111, 0.900), scale=(0.006, 0.0022, 0.024))
    obj = bpy.context.active_object
    obj.name = "Silver_Pendant"
    obj.data.materials.append(material)
    bevel = obj.modifiers.new("Soft edges", "BEVEL")
    bevel.width = 0.002
    bevel.segments = 4
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    rigid_mesh_weight(obj, armature, "Chest")
    return obj


def join_objects(name: str, objects: list[bpy.types.Object]) -> bpy.types.Object:
    if not objects:
        raise ValueError(f"no objects to join: {name}")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    result = bpy.context.active_object
    result.name = name
    result.select_set(False)
    return result


def add_nearest_shape_keys(obj: bpy.types.Object, body: bpy.types.Object) -> int:
    if obj.type != "MESH" or not body.data.shape_keys:
        return 0
    tree = KDTree(len(body.data.vertices))
    for vertex in body.data.vertices:
        tree.insert(body.matrix_world @ vertex.co, vertex.index)
    tree.balance()
    obj.shape_key_add(name="Basis")
    added = 0
    for name in SHAPE_KEYS:
        source_key = body.data.shape_keys.key_blocks.get(name)
        if source_key is None:
            continue
        target = obj.shape_key_add(name=name)
        for vertex in obj.data.vertices:
            world = obj.matrix_world @ vertex.co
            _, index, _ = tree.find(world)
            delta = body.matrix_world.to_3x3() @ (
                source_key.data[index].co - body.data.vertices[index].co
            )
            target.data[vertex.index].co = vertex.co + obj.matrix_world.to_3x3().inverted() @ delta
        added += 1
    return added


def body_front_y(body: bpy.types.Object, x: float, z: float) -> float:
    candidates = sorted(
        body.data.vertices,
        key=lambda vertex: (mesh_world_vertex(body, vertex.index).x - x) ** 2
        + (mesh_world_vertex(body, vertex.index).z - z) ** 2,
    )[:32]
    return min(mesh_world_vertex(body, vertex.index).y for vertex in candidates)


def body_back_y(body: bpy.types.Object, x: float, z: float) -> float:
    candidates = sorted(
        body.data.vertices,
        key=lambda vertex: (mesh_world_vertex(body, vertex.index).x - x) ** 2
        + (mesh_world_vertex(body, vertex.index).z - z) ** 2,
    )[:32]
    return max(mesh_world_vertex(body, vertex.index).y for vertex in candidates)


def surface_cross_section_loop(
    body: bpy.types.Object,
    z: float,
    x_min: float,
    x_max: float,
    offset: float,
    count: int = 32,
) -> list[tuple[float, float, float]]:
    """Return a closed front/back loop sampled from the real avatar surface."""
    xs = [x_min + (x_max - x_min) * index / count for index in range(count + 1)]
    front = [(x, body_front_y(body, x, z) - offset, z) for x in xs]
    back = [(x, body_back_y(body, x, z) + offset, z) for x in reversed(xs)]
    return front + back


def transfer_nearest_body_weights(obj: bpy.types.Object, body: bpy.types.Object) -> None:
    """Copy the nearest exact avatar weights onto authored trim and hardware."""
    tree = KDTree(len(body.data.vertices))
    for vertex in body.data.vertices:
        tree.insert(body.matrix_world @ vertex.co, vertex.index)
    tree.balance()
    obj.vertex_groups.clear()
    groups = {group.name: obj.vertex_groups.new(name=group.name) for group in body.vertex_groups}
    for vertex in obj.data.vertices:
        _, source_index, _ = tree.find(obj.matrix_world @ vertex.co)
        assignments = sorted(
            body.data.vertices[source_index].groups,
            key=lambda item: item.weight,
            reverse=True,
        )[:4]
        total = sum(item.weight for item in assignments if item.weight > 1e-8)
        if total <= 1e-8:
            fallback = "Chest" if vertex.co.z > 0.86 else "Hips"
            groups[fallback].add([vertex.index], 1.0, "REPLACE")
            continue
        for item in assignments:
            name = body.vertex_groups[item.group].name
            groups[name].add([vertex.index], item.weight / total, "REPLACE")


def create_outfit(body, armature, materials):
    ivory, black, strap, silver = materials
    garments: list[bpy.types.Object] = []

    top_front = extract_surface(
        body,
        armature,
        "Ivory_Ribbed_Front",
        lambda c: 0.873 <= c.z <= 1.034
        and c.y < -0.002
        and abs(c.x) <= (0.128 if c.z < 0.985 else 0.104 - max(0.0, c.z - 0.985) * 0.78),
        ivory,
        0.0055,
    )
    garments.append(top_front)
    back_band = extract_surface(
        body,
        armature,
        "Ivory_Ribbed_Back_Band",
        lambda c: 0.872 <= c.z <= 0.914 and c.y >= -0.01 and abs(c.x) <= 0.125,
        ivory,
        0.0055,
    )
    garments.append(back_band)
    collar = collar_mesh(ivory, armature)
    garments.append(collar)

    bottom_front = extract_surface(
        body,
        armature,
        "Black_Highcut_Front",
        lambda c: 0.660 <= c.z <= 0.782
        and c.y < 0.0
        and abs(c.x) <= 0.031 + max(0.0, c.z - 0.660) * 0.62,
        black,
        0.0045,
    )
    garments.append(bottom_front)
    bottom_back = extract_surface(
        body,
        armature,
        "Black_Highcut_Back",
        lambda c: 0.650 <= c.z <= 0.782
        and c.y >= -0.006
        and abs(c.x) <= 0.058 + max(0.0, c.z - 0.650) * 0.45,
        black,
        0.0045,
    )
    garments.append(bottom_back)
    waist_band = extract_surface(
        body,
        armature,
        "Black_Waist_Band",
        lambda c: 0.767 <= c.z <= 0.785 and abs(c.x) <= 0.126,
        black,
        0.005,
    )
    garments.append(waist_band)

    ivory_trim: list[bpy.types.Object] = []
    front_hem = []
    for index in range(13):
        x = -0.108 + 0.216 * index / 12
        front_hem.append((x, body_front_y(body, x, 0.876) - 0.008, 0.876))
    ivory_trim.append(curve_tube("Knit_Front_Hem", front_hem, 0.00165, ivory, armature, "Chest"))
    for label, z in (("Top", 0.912), ("Hem", 0.874)):
        back_edge = []
        for index in range(13):
            x = -0.104 + 0.208 * index / 12
            back_edge.append((x, body_back_y(body, x, z) + 0.008, z))
        ivory_trim.append(curve_tube(f"Knit_Back_Band_{label}", back_edge, 0.00145, ivory, armature, "Chest"))
    joined_ivory_trim = join_objects("Ivory_Knit_Edge_Binding", ivory_trim)
    transfer_nearest_body_weights(joined_ivory_trim, body)
    garments.append(joined_ivory_trim)

    strap_objects: list[bpy.types.Object] = []
    hardware: list[bpy.types.Object] = []
    harness_points = {
        "tl": (-0.088, body_front_y(body, -0.088, 0.884) - 0.008, 0.884),
        "tr": (0.088, body_front_y(body, 0.088, 0.884) - 0.008, 0.884),
        "ml": (-0.054, body_front_y(body, -0.054, 0.792) - 0.009, 0.792),
        "mr": (0.054, body_front_y(body, 0.054, 0.792) - 0.009, 0.792),
        "lc": (0.0, body_front_y(body, 0.0, 0.704) - 0.010, 0.704),
        "sl": (-0.105, body_front_y(body, -0.105, 0.762) - 0.008, 0.762),
        "sr": (0.105, body_front_y(body, 0.105, 0.762) - 0.008, 0.762),
    }
    links = (
        ("tl", "ml"), ("tr", "mr"), ("tl", "mr"), ("tr", "ml"),
        ("ml", "lc"), ("mr", "lc"), ("sl", "ml"), ("sr", "mr"),
    )
    for index, (start, end) in enumerate(links):
        midpoint = (Vector(harness_points[start]) + Vector(harness_points[end])) * 0.5
        midpoint.y -= 0.002
        strap_objects.append(curve_tube(
            f"Harness_{index:02d}",
            [harness_points[start], midpoint, harness_points[end]],
            0.00255,
            strap,
            armature,
            "Spine" if index >= 4 else "Chest",
        ))
    for label, group in (("tl", "Chest"), ("tr", "Chest"), ("ml", "Spine"), ("mr", "Spine"), ("lc", "Hips")):
        hardware.append(torus(f"Harness_Ring_{label.upper()}", harness_points[label], 0.0092, 0.0017, silver, armature, group))

    for label, sign in (("L", -1.0), ("R", 1.0)):
        front_opening = []
        back_opening = []
        for x, z in ((0.101, 0.770), (0.089, 0.738), (0.071, 0.704), (0.050, 0.676), (0.031, 0.660)):
            px = sign * x
            front_opening.append((px, body_front_y(body, px, z) - 0.007, z))
            back_opening.append((px, body_back_y(body, px, z) + 0.007, z))
        opening_loop = front_opening + list(reversed(back_opening))
        strap_objects.append(curve_tube(
            f"Bottom_Opening_{label}", opening_loop, 0.00175, strap, armature, "Hips", cyclic=True
        ))

    back_z = 0.792
    back_center_y = body_back_y(body, 0.0, back_z) + 0.009
    waist = surface_cross_section_loop(body, back_z, -0.098, 0.098, 0.005, 48)
    strap_objects.append(curve_tube("Back_Tie_Waist", waist, 0.0018, strap, armature, "Hips", cyclic=True))
    left_loop = [
        (-0.006 + 0.030 * math.sin(t), back_center_y + 0.012 * math.sin(t) ** 2, back_z + 0.017 * math.sin(2 * t))
        for t in [math.tau * i / 48 for i in range(49)]
    ]
    right_loop = [(-x, y, z) for x, y, z in left_loop]
    strap_objects.append(curve_tube("Back_Bow_Left", left_loop, 0.0018, strap, armature, "Hips", cyclic=True))
    strap_objects.append(curve_tube("Back_Bow_Right", right_loop, 0.0018, strap, armature, "Hips", cyclic=True))
    strap_objects.append(curve_tube("Back_Bow_Tail_L", [(-0.004, back_center_y, back_z), (-0.018, back_center_y + 0.005, back_z - 0.032), (-0.010, back_center_y + 0.003, back_z - 0.060)], 0.0017, strap, armature, "Hips"))
    strap_objects.append(curve_tube("Back_Bow_Tail_R", [(0.004, back_center_y, back_z), (0.020, back_center_y + 0.005, back_z - 0.030), (0.014, back_center_y + 0.003, back_z - 0.055)], 0.0017, strap, armature, "Hips"))

    for side, x in (("L", 0.057), ("R", -0.057)):
        leg_points = surface_cross_section_loop(body, 0.535, x - 0.033, x + 0.033, 0.004, 32)
        strap_objects.append(curve_tube(f"Thigh_Strap_{side}", leg_points, 0.0020, strap, armature, f"UpperLeg_{side}", cyclic=True))
        front = body_front_y(body, x, 0.535) - 0.010
        hardware.append(heart_curve(f"Thigh_Heart_{side}", (x, front, 0.535), 0.00072, silver, armature, f"UpperLeg_{side}"))

    chain_y = body_front_y(body, 0.0, 0.950) - 0.011
    strap_objects.append(curve_tube(
        "Necklace_Chain_Left",
        [(-0.038, body_front_y(body, -0.038, 1.041) - 0.009, 1.041), (-0.024, chain_y, 0.974), (0.0, chain_y - 0.002, 0.925)],
        0.00075,
        silver,
        armature,
        "Chest",
        resolution=2,
    ))
    strap_objects.append(curve_tube(
        "Necklace_Chain_Right",
        [(0.038, body_front_y(body, 0.038, 1.041) - 0.009, 1.041), (0.024, chain_y, 0.974), (0.0, chain_y - 0.002, 0.925)],
        0.00075,
        silver,
        armature,
        "Chest",
        resolution=2,
    ))
    hardware.append(cube_pendant(silver, armature))

    joined_straps = join_objects("Black_Geometric_Straps", strap_objects)
    joined_hardware = join_objects("Silver_Hardware", hardware)
    transfer_nearest_body_weights(joined_straps, body)
    transfer_nearest_body_weights(joined_hardware, body)
    garments.extend((joined_straps, joined_hardware))
    for obj in garments:
        add_nearest_shape_keys(obj, body)
    return garments


def studio_setup() -> tuple[bpy.types.Object, bpy.types.Object]:
    world = bpy.context.scene.world or bpy.data.worlds.new("Studio World")
    bpy.context.scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.035, 0.040, 0.055, 1.0)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.25

    backdrop = plain_material("Backdrop", (0.68, 0.72, 0.82, 1.0), roughness=0.72)
    bpy.ops.mesh.primitive_plane_add(size=8, location=(0, 0, 0.0))
    floor = bpy.context.active_object
    floor.name = "Studio_Floor"
    floor.data.materials.append(backdrop)

    def area(name, location, energy, color, size):
        data = bpy.data.lights.new(name, type="AREA")
        data.energy = energy
        data.color = color
        data.shape = "DISK"
        data.size = size
        obj = bpy.data.objects.new(name, data)
        bpy.context.collection.objects.link(obj)
        obj.location = location
        direction = Vector((0, 0, 0.78)) - obj.location
        obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        return obj

    area("Key", (-1.1, -1.5, 1.8), 72, (1.0, 0.84, 0.76), 1.5)
    area("Fill", (1.5, -0.6, 1.15), 44, (0.72, 0.83, 1.0), 1.8)
    area("Rim", (0.8, 1.4, 1.65), 92, (0.82, 0.88, 1.0), 1.2)
    area("Front Soft", (0.0, -1.8, 0.70), 24, (1.0, 0.96, 0.91), 1.0)

    camera_data = bpy.data.cameras.new("Product_Camera")
    camera = bpy.data.objects.new("Product_Camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = 0.72
    camera_data.lens = 70
    bpy.context.scene.camera = camera
    return floor, camera


def point_camera(camera, location, target=(0.0, -0.006, 0.805)) -> None:
    camera.location = location
    camera.rotation_euler = (Vector(target) - camera.location).to_track_quat("-Z", "Y").to_euler()


def preview_pose(armature: bpy.types.Object) -> None:
    for bone in armature.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0.0, 0.0, 0.0)
        bone.location = (0.0, 0.0, 0.0)
        bone.scale = (1.0, 1.0, 1.0)
    armature.pose.bones["UpperArm_L"].rotation_euler.x = math.radians(-64)
    armature.pose.bones["UpperArm_R"].rotation_euler.x = math.radians(-64)
    bpy.context.view_layer.update()


def reset_pose(armature: bpy.types.Object) -> None:
    for bone in armature.pose.bones:
        bone.rotation_euler = (0.0, 0.0, 0.0)
        bone.location = (0.0, 0.0, 0.0)
        bone.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()


def render_views(camera: bpy.types.Object, paths: dict[str, Path]) -> None:
    scene = bpy.context.scene
    # Cycles CPU rendering works headlessly without an EGL/OpenGL context and
    # preserves the same authored mesh/material scene used for the FBX export.
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 48
    scene.cycles.use_denoising = True
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = 0.035
    scene.render.resolution_x = 1400
    scene.render.resolution_y = 1400
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.render.image_settings.color_depth = "8"
    scene.view_settings.look = "AgX - Medium High Contrast"
    views = {
        "front": (0.0, -2.4, 0.83),
        "back": (0.0, 2.4, 0.83),
        "left": (2.4, 0.0, 0.83),
        "right": (-2.4, 0.0, 0.83),
        "three-quarter": (1.55, -1.85, 0.85),
    }
    for name, location in views.items():
        output = paths[name]
        output.parent.mkdir(parents=True, exist_ok=True)
        point_camera(camera, location)
        scene.render.filepath = str(output)
        bpy.ops.render.render(write_still=True)


def contact_sheet(previews: dict[str, Path], path: Path) -> None:
    names = ("front", "three-quarter", "left", "right", "back")
    tiles = [Image.open(previews[name]).convert("RGB") for name in names]
    thumb = 700
    canvas = Image.new("RGB", (thumb * 3, thumb * 2), (30, 34, 46))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 34)
    except OSError:
        font = ImageFont.load_default()
    positions = ((0, 0), (thumb, 0), (thumb * 2, 0), (350, thumb), (1050, thumb))
    for name, image, (x, y) in zip(names, tiles, positions):
        image.thumbnail((thumb, thumb), Image.Resampling.LANCZOS)
        canvas.paste(image, (x + (thumb - image.width) // 2, y))
        draw.rounded_rectangle((x + 18, y + 18, x + 250, y + 66), 16, fill=(20, 23, 33))
        draw.text((x + 34, y + 25), name.upper(), fill=(244, 244, 247), font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, "WEBP", quality=94, method=6)


def export_fbx(path: Path, armature: bpy.types.Object, garments: list[bpy.types.Object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    armature.hide_render = True
    armature.hide_set(False)
    armature.select_set(True)
    for obj in garments:
        obj.hide_render = False
        obj.hide_set(False)
        obj.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.export_scene.fbx(
        filepath=str(path),
        use_selection=True,
        object_types={"ARMATURE", "MESH"},
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_ALL",
        use_space_transform=True,
        bake_space_transform=False,
        mesh_smooth_type="FACE",
        use_subsurf=False,
        use_mesh_modifiers=True,
        use_mesh_edges=False,
        use_tspace=True,
        use_armature_deform_only=True,
        add_leaf_bones=False,
        primary_bone_axis="Y",
        secondary_bone_axis="X",
        armature_nodetype="NULL",
        bake_anim=False,
        path_mode="RELATIVE",
        embed_textures=False,
    )


def write_unity_sidecars(fbx: Path, prefab: Path, product_name: str) -> list[Path]:
    guid = uuid.uuid4().hex
    prefab_guid = uuid.uuid4().hex
    fbx_meta = fbx.with_suffix(fbx.suffix + ".meta")
    fbx_meta.write_text(
        f"""fileFormatVersion: 2
guid: {guid}
ModelImporter:
  serializedVersion: 22200
  internalIDToNameTable: []
  externalObjects: {{}}
  materials:
    materialImportMode: 1
    materialName: 0
    materialSearch: 1
    materialLocation: 1
  animations:
    legacyGenerateAnimations: 4
    bakeSimulation: 0
    resampleCurves: 1
    optimizeGameObjects: 0
    removeConstantScaleCurves: 0
  meshes:
    globalScale: 1
    meshCompression: 0
    addColliders: 0
    useSRGBMaterialColor: 1
    sortHierarchyByName: 1
    importVisibility: 1
    importBlendShapes: 1
    importCameras: 0
    importLights: 0
    fileIdsGeneration: 2
    swapUVChannels: 0
    generateSecondaryUV: 0
    useFileUnits: 1
    keepQuads: 0
    weldVertices: 1
    bakeAxisConversion: 0
    preserveHierarchy: 1
    skinWeightsMode: 0
    maxBonesPerVertex: 4
    minBoneWeight: 0.001
  tangentSpace:
    normalSmoothAngle: 60
    normalImportMode: 0
    tangentImportMode: 3
    normalCalculationMode: 4
    blendShapeNormalImportMode: 1
  importAnimation: 0
  animationType: 2
  userData: image2outfit SiroinoSotai v1.0 strappy rib knit
  assetBundleName:
  assetBundleVariant:
""",
        encoding="utf-8",
    )
    prefab.parent.mkdir(parents=True, exist_ok=True)
    prefab.write_text(
        f"""%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1001 &1001000000000000
PrefabInstance:
  m_ObjectHideFlags: 0
  serializedVersion: 2
  m_Modification:
    serializedVersion: 3
    m_TransformParent: {{fileID: 0}}
    m_Modifications:
    - target: {{fileID: 100000, guid: {guid}, type: 3}}
      propertyPath: m_Name
      value: {product_name}
      objectReference: {{fileID: 0}}
    m_RemovedComponents: []
    m_RemovedGameObjects: []
    m_AddedGameObjects: []
    m_AddedComponents: []
  m_SourcePrefab: {{fileID: 100100000, guid: {guid}, type: 3}}
""",
        encoding="utf-8",
    )
    prefab_meta = prefab.with_suffix(prefab.suffix + ".meta")
    prefab_meta.write_text(
        f"""fileFormatVersion: 2
guid: {prefab_guid}
PrefabImporter:
  externalObjects: {{}}
  userData:
  assetBundleName:
  assetBundleVariant:
""",
        encoding="utf-8",
    )
    return [fbx_meta, prefab, prefab_meta]


def boundary_count(obj: bpy.types.Object) -> int:
    counter: Counter[tuple[int, int]] = Counter()
    for polygon in obj.data.polygons:
        vertices = list(polygon.vertices)
        for index in range(len(vertices)):
            edge = tuple(sorted((vertices[index], vertices[(index + 1) % len(vertices)])))
            counter[edge] += 1
    return sum(value == 1 for value in counter.values())


def metrics(garments: list[bpy.types.Object]) -> dict:
    result = {
        "meshObjects": 0,
        "vertices": 0,
        "triangles": 0,
        "materialSlots": 0,
        "shapeKeys": 0,
        "maxBoneInfluences": 0,
        "unweightedVertices": 0,
        "weightSumErrors": 0,
        "degenerateTriangles": 0,
        "boundaryEdges": 0,
    }
    for obj in garments:
        mesh = obj.data
        mesh.calc_loop_triangles()
        result["meshObjects"] += 1
        result["vertices"] += len(mesh.vertices)
        result["triangles"] += len(mesh.loop_triangles)
        result["materialSlots"] += len(mesh.materials)
        result["shapeKeys"] += max(0, len(mesh.shape_keys.key_blocks) - 1) if mesh.shape_keys else 0
        result["boundaryEdges"] += boundary_count(obj)
        for vertex in mesh.vertices:
            weights = [item.weight for item in vertex.groups if item.weight > 1e-8]
            result["maxBoneInfluences"] = max(result["maxBoneInfluences"], len(weights))
            if not weights:
                result["unweightedVertices"] += 1
            elif abs(sum(weights) - 1.0) > 1e-4:
                result["weightSumErrors"] += 1
        for triangle in mesh.loop_triangles:
            a, b, c = (mesh.vertices[index].co for index in triangle.vertices)
            if (b - a).cross(c - a).length_squared <= 1e-20:
                result["degenerateTriangles"] += 1
    return result


def write_readme(path: Path, product_name: str, measured: dict) -> None:
    path.write_text(
        f"""# {product_name}

Target: SiroinoSotai v1.0 PC body (CC0), exact skeleton and body topology included in the official package.

Contents:

- ivory ribbed sleeveless high-neck crop top with open back band
- black high-cut bottom
- geometric torso harness with silver rings
- rear waist cord and modeled bow
- paired thigh straps with silver heart hardware
- silver chain and bar pendant
- SiroinoSotai size blend shapes: {len(SHAPE_KEYS)} authored names
- five 1400 x 1400 renders of the actual generated mesh

Measured static mesh:

- mesh objects: {measured['meshObjects']}
- vertices: {measured['vertices']}
- triangles: {measured['triangles']}
- material slots: {measured['materialSlots']}
- exported blend shapes: {measured['shapeKeys']}
- maximum bone influences: {measured['maxBoneInfluences']}

Import the entire generated folder into a Unity 2022.3.22f1 VRChat avatar project. Keep `.meta` files with the FBX and Prefab. The committed official SiroinoSotai Prefab is the validation target; the avatar body itself is not part of this garment delivery folder.

This generated candidate still requires Unity ModelImporter save/reload, the integrated-avatar Prefab gate, pose penetration review, VRChat SDK Build & Test, and an in-client human review before a customer `GO` release.
""",
        encoding="utf-8",
    )


def main() -> int:
    job_path, job = load_job()
    clean_scene()
    source = repo_path(job["targetSourcePath"])
    blend_path = repo_path(job["blendPath"])
    fbx_path = repo_path(job["fbxAssetPath"])
    prefab_path = repo_path(job["prefabAssetPath"])
    artifact_dir = repo_path(job["artifactDir"])
    generated_dir = fbx_path.parent
    texture_dir = generated_dir / "Textures"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    generated_dir.mkdir(parents=True, exist_ok=True)

    bpy.ops.import_scene.fbx(filepath=str(source), use_anim=False)
    body = next(obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.name.startswith("SiroinoSotai_PC"))
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    armature.name = "SiroinoSotai_Armature"
    set_skin_material(body)

    textures = make_texture_maps(texture_dir)
    ivory = textured_material(
        "MAT_Ivory_Ribbed_Knit",
        textures["ivory_knit_albedo.png"],
        textures["ivory_knit_normal.png"],
        textures["ivory_knit_roughness.png"],
        normal_strength=0.72,
        sheen=0.24,
    )
    black = textured_material(
        "MAT_Black_Satin",
        textures["black_satin_albedo.png"],
        textures["black_satin_normal.png"],
        textures["black_satin_roughness.png"],
        normal_strength=0.22,
        sheen=0.12,
    )
    strap = plain_material("MAT_Black_Straps", (0.009, 0.010, 0.014, 1.0), roughness=0.28)
    silver = plain_material("MAT_Brushed_Silver", (0.64, 0.70, 0.78, 1.0), roughness=0.18, metallic=0.93)
    garments = create_outfit(body, armature, (ivory, black, strap, silver))

    blend_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)

    _, camera = studio_setup()
    preview_pose(armature)
    previews = {name: repo_path(value) for name, value in job["previewPaths"].items()}
    render_views(camera, previews)
    contact = generated_dir / f"{job['id']}_actual-mesh-multiview.webp"
    contact_sheet(previews, contact)

    reset_pose(armature)
    body.hide_render = True
    export_fbx(fbx_path, armature, garments)
    sidecars = write_unity_sidecars(fbx_path, prefab_path, job["productName"])
    measured = metrics(garments)
    report = {
        "passed": measured["meshObjects"] >= 6
        and measured["vertices"] > 1000
        and measured["triangles"] > 1500
        and measured["unweightedVertices"] == 0
        and measured["weightSumErrors"] == 0
        and measured["degenerateTriangles"] == 0
        and measured["maxBoneInfluences"] <= 4,
        "checkedAt": utc_now(),
        "blenderVersion": bpy.app.version_string,
        "targetSource": str(source.relative_to(ROOT)).replace("\\", "/"),
        "targetSourceSha256": sha256(source),
        "metrics": measured,
        "views": {
            name: {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256(path),
                "width": Image.open(path).width,
                "height": Image.open(path).height,
            }
            for name, path in previews.items()
        },
        "shapeKeyNames": list(SHAPE_KEYS),
        "notes": [
            "Garment panels are derived from the exact SiroinoSotai PC body surface.",
            "Preview images are Blender Cycles renders of the actual generated mesh, not image-generation output.",
            "Unity import, animated pose penetration, and VRChat runtime review remain separate release gates.",
        ],
    }
    (artifact_dir / "build-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_readme(generated_dir / "README.md", job["productName"], measured)
    manifest_files = [blend_path, fbx_path, contact, generated_dir / "README.md", *sidecars, *textures.values(), *previews.values()]
    (generated_dir / "SOURCE_HASHES.txt").write_text(
        "\n".join(f"{sha256(path)}  {path.name}" for path in manifest_files if path.is_file()) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
