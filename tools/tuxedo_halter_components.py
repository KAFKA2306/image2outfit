#!/usr/bin/env python3
"""Reusable geometry and material components for the tuxedo halter product."""

from __future__ import annotations

import json
import math
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import bpy
from PIL import Image

import siroino_strappy_knit_build as base

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from image2outfit.pattern_projection import project_pattern_piece


def make_image_maps(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    size = 512
    outputs: dict[str, Path] = {}
    specs = {
        "wine_satin": ((82, 2, 19), 124, 9),
        "black_satin": ((8, 8, 12), 132, 8),
        "white_jacquard": ((238, 237, 233), 180, 7),
    }
    for name, (base_color, roughness, normal_amp) in specs.items():
        albedo = Image.new("RGB", (size, size))
        normal = Image.new("RGB", (size, size))
        rough = Image.new("L", (size, size))
        for y in range(size):
            for x in range(size):
                weave = math.sin(x * math.tau / 18.0) + math.sin(
                    y * math.tau / 22.0
                )
                diagonal = math.sin((x + y * 0.41) * math.tau / 44.0)
                if name == "white_jacquard":
                    motif = math.sin(x * math.tau / 64.0) * math.sin(
                        y * math.tau / 64.0
                    )
                    delta = int(3 * weave + 4 * motif)
                else:
                    delta = int(3 * weave + 5 * diagonal)
                pixel = tuple(
                    max(0, min(255, channel + delta)) for channel in base_color
                )
                albedo.putpixel((x, y), pixel)
                normal.putpixel(
                    (x, y),
                    (
                        128 + int(normal_amp * math.sin(x * math.tau / 18.0)),
                        128 + int(normal_amp * math.sin(y * math.tau / 22.0)),
                        250,
                    ),
                )
                rough.putpixel(
                    (x, y), max(0, min(255, roughness + int(7 * diagonal)))
                )
        for suffix, image in (
            ("albedo", albedo),
            ("normal", normal),
            ("roughness", rough),
        ):
            path = directory / f"{name}_{suffix}.png"
            image.save(path, optimize=True)
            outputs[f"{name}_{suffix}"] = path
    return outputs


def image_node(nodes, path: Path, *, non_color: bool = False):
    node = nodes.new("ShaderNodeTexImage")
    node.image = bpy.data.images.load(str(path), check_existing=True)
    node.interpolation = "Linear"
    if non_color:
        node.image.colorspace_settings.name = "Non-Color"
    return node


def textured_material(
    name: str,
    albedo: Path,
    normal: Path,
    roughness: Path,
    *,
    sheen: float,
    alpha: float = 1.0,
) -> bpy.types.Material:
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    color = image_node(nodes, albedo)
    rough = image_node(nodes, roughness, non_color=True)
    normal_image = image_node(nodes, normal, non_color=True)
    normal_map = nodes.new("ShaderNodeNormalMap")
    normal_map.inputs["Strength"].default_value = 0.30
    shader.inputs["Metallic"].default_value = 0.0
    shader.inputs["IOR"].default_value = 1.46
    shader.inputs["Alpha"].default_value = alpha
    if "Sheen Weight" in shader.inputs:
        shader.inputs["Sheen Weight"].default_value = sheen
        shader.inputs["Sheen Roughness"].default_value = 0.48
    links.new(color.outputs["Color"], shader.inputs["Base Color"])
    links.new(rough.outputs["Color"], shader.inputs["Roughness"])
    links.new(normal_image.outputs["Color"], normal_map.inputs["Color"])
    links.new(normal_map.outputs["Normal"], shader.inputs["Normal"])
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    if alpha < 1.0:
        material.diffuse_color = (0.02, 0.02, 0.025, alpha)
        if hasattr(material, "surface_render_method"):
            material.surface_render_method = "DITHERED"
        if hasattr(material, "use_transparency_overlap"):
            material.use_transparency_overlap = False
    return material


def finish_mesh(
    obj: bpy.types.Object,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    *,
    thickness: float = 0.0015,
    bevel: float = 0.0007,
) -> bpy.types.Object:
    obj.parent = armature
    modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
    modifier.object = armature
    modifier.use_deform_preserve_volume = True
    base.transfer_nearest_body_weights(obj, body)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if thickness > 0:
        solidify = obj.modifiers.new("Fabric thickness", "SOLIDIFY")
        solidify.thickness = thickness
        solidify.offset = 0.0
        solidify.use_even_offset = True
        bpy.ops.object.modifier_apply(modifier=solidify.name)
    if bevel > 0:
        soft = obj.modifiers.new("Soft edge", "BEVEL")
        soft.width = bevel
        soft.segments = 2
        bpy.ops.object.modifier_apply(modifier=soft.name)
    obj.select_set(False)
    return obj


def mesh_object(
    name: str,
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    material: bpy.types.Material,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    *,
    thickness: float = 0.0015,
    bevel: float = 0.0007,
) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    mesh.materials.append(material)
    uv = mesh.uv_layers.new(name="UVMap")
    x_values = [vertex[0] for vertex in vertices]
    z_values = [vertex[2] for vertex in vertices]
    x_min, x_max = min(x_values), max(x_values)
    z_min, z_max = min(z_values), max(z_values)
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            coordinate = mesh.vertices[mesh.loops[loop_index].vertex_index].co
            uv.data[loop_index].uv = (
                (coordinate.x - x_min) / max(x_max - x_min, 1e-6),
                (coordinate.z - z_min) / max(z_max - z_min, 1e-6),
            )
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return finish_mesh(obj, body, armature, thickness=thickness, bevel=bevel)


def bib_panel(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    pattern_piece: Mapping[str, Any],
    *,
    width_scale: float = 1.0,
) -> bpy.types.Object:
    projection = project_pattern_piece(
        pattern_piece,
        x_scale=0.7047619047619048,
        z_scale=0.6313253012048193,
        z_offset=0.8495421686746988,
        width_scale=width_scale,
    )
    vertices = [
        (x, base.body_front_y(body, x, z) - 0.020, z)
        for x, z in projection["pointsXZ"]
    ]
    obj = mesh_object(
        "White_Jacquard_Bib",
        vertices,
        [tuple(range(len(vertices)))],
        material,
        body,
        armature,
        thickness=0.0011,
        bevel=0.0005,
    )
    obj["patternPieceId"] = str(projection["pieceId"])
    obj["patternProjectionFingerprint"] = str(projection["fingerprint"])
    obj["patternEdgeVertexMap"] = json.dumps(
        projection["edgeVertexMap"],
        sort_keys=True,
        separators=(",", ":"),
    )
    obj["patternProjection"] = json.dumps(
        projection,
        sort_keys=True,
        separators=(",", ":"),
    )
    return obj

def waistcoat_side(
    side: str,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    sign = -1.0 if side == "L" else 1.0

    def predicate(center) -> bool:
        absolute_x = abs(center.x)
        inner = 0.020 + max(0.0, center.z - 0.720) * 0.125
        return (
            0.715 <= center.z <= 1.015
            and center.y < 0.012
            and center.x * sign > 0.0
            and inner <= absolute_x <= 0.160
        )

    return base.extract_surface(
        body,
        armature,
        f"Wine_Waistcoat_Front_{side}",
        predicate,
        material,
        0.0075,
    )


def waistcoat_back(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    return base.extract_surface(
        body,
        armature,
        "Wine_Waistcoat_Back",
        lambda center: 0.715 <= center.z <= 0.900
        and center.y >= -0.004
        and abs(center.x) <= 0.152,
        material,
        0.0070,
    )


def tail_panel(
    side: str,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    sign = -1.0 if side == "L" else 1.0
    coordinates = [
        (sign * 0.020, 0.735),
        (sign * 0.108, 0.735),
        (sign * 0.112, 0.680),
        (sign * 0.045, 0.590),
    ]
    vertices = [
        (x, base.body_front_y(body, x, z) - 0.012, z) for x, z in coordinates
    ]
    face = (0, 1, 2, 3) if side == "R" else (0, 3, 2, 1)
    return mesh_object(
        f"Wine_Waistcoat_Tail_{side}",
        vertices,
        [face],
        material,
        body,
        armature,
        thickness=0.0016,
        bevel=0.0005,
    )


def ring_skirt(
    name: str,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
    *,
    top_z: float,
    bottom_z: float,
    top_rx: float,
    top_ry: float,
    bottom_rx: float,
    bottom_ry: float,
    pleats: int,
    thickness: float,
) -> tuple[bpy.types.Object, list[int]]:
    del thickness
    segments = pleats * 8
    vertical_segments = 7
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    for row in range(vertical_segments):
        ratio = row / (vertical_segments - 1)
        z = top_z + (bottom_z - top_z) * ratio
        rx = top_rx + (bottom_rx - top_rx) * ratio
        ry = top_ry + (bottom_ry - top_ry) * ratio
        fold_amplitude = 0.004 + 0.010 * ratio
        for index in range(segments):
            angle = math.tau * index / segments
            fold = 1.0 + fold_amplitude * math.sin(angle * pleats)
            vertices.append(
                (rx * fold * math.cos(angle), ry * fold * math.sin(angle), z)
            )
    for row in range(vertical_segments - 1):
        start = row * segments
        following_row = (row + 1) * segments
        for index in range(segments):
            following = (index + 1) % segments
            faces.append(
                (
                    start + index,
                    start + following,
                    following_row + following,
                    following_row + index,
                )
            )
    obj = mesh_object(
        name,
        vertices,
        faces,
        material,
        body,
        armature,
        thickness=0.0,
        bevel=0.0,
    )
    return obj, list(range(segments))


def vertical_ruffle(
    index: int,
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> bpy.types.Object:
    center_x = (index - 1) * 0.018
    steps = 24
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    for step in range(steps):
        ratio = step / (steps - 1)
        z = 0.965 - ratio * 0.165
        wave = 0.004 * math.sin(ratio * math.tau * 4 + index * 0.8)
        center = center_x + wave
        width = 0.009 + 0.003 * math.sin(ratio * math.pi)
        for x in (center - width, center + width):
            y = base.body_front_y(body, x, z) - 0.024 - abs(wave) * 0.4
            vertices.append((x, y, z))
    for step in range(steps - 1):
        point = step * 2
        faces.append((point, point + 1, point + 3, point + 2))
    return mesh_object(
        f"White_Bib_Ruffle_{index + 1}",
        vertices,
        faces,
        material,
        body,
        armature,
        thickness=0.0008,
        bevel=0.00025,
    )


def ellipsoid(
    name: str,
    location: tuple[float, float, float],
    scale: tuple[float, float, float],
    material: bpy.types.Material,
    body: bpy.types.Object,
    armature: bpy.types.Object,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=24, ring_count=12, location=location
    )
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(material)
    return finish_mesh(obj, body, armature, thickness=0.0, bevel=0.0004)


def bow_tie(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    material: bpy.types.Material,
) -> list[bpy.types.Object]:
    y = base.body_front_y(body, 0.0, 0.990) - 0.020
    left = ellipsoid(
        "Black_Bow_Left",
        (-0.026, y, 0.985),
        (0.030, 0.010, 0.020),
        material,
        body,
        armature,
    )
    right = ellipsoid(
        "Black_Bow_Right",
        (0.026, y, 0.985),
        (0.030, 0.010, 0.020),
        material,
        body,
        armature,
    )
    knot = ellipsoid(
        "Black_Bow_Knot",
        (0.0, y - 0.003, 0.985),
        (0.011, 0.012, 0.014),
        material,
        body,
        armature,
    )
    return [left, right, knot]
