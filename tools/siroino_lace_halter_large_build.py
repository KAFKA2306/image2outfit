#!/usr/bin/env python3
"""Load the tracked product-specific Siroino lace builder source.

The encoded product source was authored against the former shared
``front_strip_mesh`` helper. Keep the compatibility adapter scoped to this
product instead of silently changing every generator in the repository.
"""
from __future__ import annotations

import base64
import sys
import zlib
from pathlib import Path

import bpy
from mathutils.kdtree import KDTree

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_strappy_knit_build as _base


def _body_front(body: bpy.types.Object, x: float, z: float) -> float:
    vertices = sorted(
        body.data.vertices,
        key=lambda vertex: (_base.mesh_world_vertex(body, vertex.index).x - x) ** 2
        + (_base.mesh_world_vertex(body, vertex.index).z - z) ** 2,
    )[:32]
    return min(_base.mesh_world_vertex(body, vertex.index).y for vertex in vertices)


def _transfer_weights(obj: bpy.types.Object, body: bpy.types.Object) -> None:
    tree = KDTree(len(body.data.vertices))
    for vertex in body.data.vertices:
        tree.insert(body.matrix_world @ vertex.co, vertex.index)
    tree.balance()
    obj.vertex_groups.clear()
    groups = {
        group.name: obj.vertex_groups.new(name=group.name)
        for group in body.vertex_groups
    }
    for vertex in obj.data.vertices:
        _, body_index, _ = tree.find(obj.matrix_world @ vertex.co)
        assignments = sorted(
            body.data.vertices[body_index].groups,
            key=lambda item: item.weight,
            reverse=True,
        )[:4]
        total = sum(item.weight for item in assignments)
        for item in assignments:
            if total:
                name = body.vertex_groups[item.group].name
                groups[name].add([vertex.index], item.weight / total, "REPLACE")


def _front_strip_mesh(
    name: str,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    rows,
    *,
    thickness: float = 0.0012,
) -> bpy.types.Object:
    """Build fitted mirrored strips from ``(z, inner, outer)`` row tuples."""
    vertices = []
    faces = []
    row_count = len(rows)
    for sign in (-1.0, 1.0):
        side_start = len(vertices)
        for z, inner_width, outer_width in rows:
            for x in (sign * inner_width, sign * outer_width):
                vertices.append((x, _body_front(body, x, z) - 0.0065, z))
        for row in range(row_count - 1):
            index = side_start + row * 2
            if sign < 0:
                faces.append((index, index + 2, index + 3, index + 1))
            else:
                faces.append((index, index + 1, index + 3, index + 2))

    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    mesh.materials.append(material)
    uv = mesh.uv_layers.new(name="UVMap")
    z_min = min(row[0] for row in rows)
    z_max = max(row[0] for row in rows)
    max_width = max(row[2] for row in rows)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
        for loop_index in polygon.loop_indices:
            coordinate = mesh.vertices[mesh.loops[loop_index].vertex_index].co
            uv.data[loop_index].uv = (
                (coordinate.x + max_width) / (2.0 * max_width),
                (coordinate.z - z_min) / max(z_max - z_min, 1e-6),
            )

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = armature
    modifier = obj.modifiers.new("Siroino Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True
    _transfer_weights(obj, body)
    solidify = obj.modifiers.new("Strip thickness", "SOLIDIFY")
    solidify.thickness = thickness
    solidify.offset = 0.0
    solidify.use_even_offset = True
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=solidify.name)
    obj.select_set(False)
    return obj


if not hasattr(_base, "front_strip_mesh"):
    _base.front_strip_mesh = _front_strip_mesh

source_root = Path(__file__).with_name("product_sources") / "siroino_lace_halter_large"
parts = sorted(source_root.glob("part-*.b85"))
if not parts:
    raise FileNotFoundError(f"missing product builder source: {source_root}")
payload = "".join(path.read_text(encoding="ascii").strip() for path in parts)
source = zlib.decompress(base64.b85decode(payload.encode("ascii"))).decode("utf-8")

# The legacy payload pre-dates the repository lifecycle policy and incorrectly
# self-certified human review before Unity import/reload and runtime evidence.
# Preserve its geometry source while making generated state strictly truthful.
replacements = {
    '"status": "HUMAN_REVIEW_PENDING"': '"status": "WORKING"',
    '"humanVisualReview": "PASS"': '"humanVisualReview": "PENDING"',
    '"humanPoseReview": "PASS"': '"humanPoseReview": "PENDING"',
    '"finalDecision": "TECHNICAL_PASS_VISUAL_PASS_RUNTIME_REVIEW_REQUIRED"': (
        '"finalDecision": "BLENDER_PASS_HUMAN_AND_UNITY_REVIEW_REQUIRED"'
    ),
    'Siroino _Large shape-key profile baked from private source': (
        'Siroino _Large shape-key profile baked from tracked source'
    ),
    'The exact private target is resolved generically by the self-hosted pipeline;': (
        'The exact tracked target is resolved deterministically by the product pipeline;'
    ),
    'The five-view and six-pose renders are regenerated from the tracked Blender source.': (
        'The five-view and seven-pose review renders are regenerated from the tracked Blender source.'
    ),
}
for old, new in replacements.items():
    if old not in source:
        raise RuntimeError(f"expected product-source contract missing: {old}")
    source = source.replace(old, new)

exec(compile(source, __file__, "exec"), globals(), globals())
