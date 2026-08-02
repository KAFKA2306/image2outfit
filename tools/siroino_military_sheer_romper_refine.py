#!/usr/bin/env python3
"""Refine the smooth military romper into a continuous short-wrap silhouette."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_military_sheer_romper_entry as entry  # noqa: E402

base = entry.base
smooth = entry.smooth
ORIGINAL_BUILD_GARMENT = smooth.build_garment
ORIGINAL_CONFIGURE_SCENE = smooth.configure_scene
ORIGINAL_SHEER_MATERIAL = base.sheer_material


def remove_object(obj: bpy.types.Object) -> None:
    if obj and obj.name in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)


def lower_wrap_shell(fabric, armature):
    """Create continuous opaque lower coverage with a short tailored hem."""
    segments = 64
    sections = [
        (0.785, 0.192, 0.142),
        (0.700, 0.212, 0.150),
        (0.565, 0.225, 0.158),
        (0.455, 0.210, 0.150),
    ]
    vertices = []
    for z, rx, ry in sections:
        for index in range(segments):
            angle = math.tau * index / segments
            y = ry * math.sin(angle)
            # Keep the front tailored while adding reliable opaque back coverage.
            y *= 0.96 if y < 0 else 1.12
            vertices.append((rx * math.cos(angle), y, z))
    faces = []
    for ring in range(len(sections) - 1):
        for index in range(segments):
            nxt = (index + 1) % segments
            faces.append(
                (
                    ring * segments + index,
                    ring * segments + nxt,
                    (ring + 1) * segments + nxt,
                    (ring + 1) * segments + index,
                )
            )
    return smooth.mesh_object(
        "Continuous_Romper_Lower",
        vertices,
        faces,
        [fabric],
        armature,
        "Hips.1",
        thickness=0.0035,
        bevel=0.003,
    )


def build_garment(armature, fabric, sheer, gold):
    objects = ORIGINAL_BUILD_GARMENT(armature, fabric, sheer, gold)
    retained = []
    for obj in objects:
        if obj.name.startswith("Romper_Short_") or obj.name == "Standing_Collar":
            remove_object(obj)
        else:
            retained.append(obj)

    retained.append(lower_wrap_shell(fabric, armature))
    retained.append(
        smooth.elliptical_band(
            "Standing_Collar",
            1.235,
            1.335,
            0.094,
            0.074,
            fabric,
            armature,
            "Neck.1",
            gap=0.055,
        )
    )
    return retained


def sheer_material(path: Path):
    material = ORIGINAL_SHEER_MATERIAL(path)
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    shader = next((node for node in nodes if node.type == "BSDF_PRINCIPLED"), None)
    if shader is not None:
        alpha_input = shader.inputs.get("Alpha")
        if alpha_input is not None:
            for link in list(alpha_input.links):
                links.remove(link)
            alpha_input.default_value = 0.48
        shader.inputs["Roughness"].default_value = 0.52
    material.diffuse_color = (0.010, 0.012, 0.016, 0.48)
    return material


def configure_scene():
    camera = ORIGINAL_CONFIGURE_SCENE()
    for obj in bpy.data.objects:
        if obj.type == "LIGHT":
            obj.data.energy *= 0.62
    return camera


base.REVISION = "smooth-tailored-v6"
base.build_garment = build_garment
base.sheer_material = sheer_material
base.configure_scene = configure_scene


if __name__ == "__main__":
    raise SystemExit(base.main())
