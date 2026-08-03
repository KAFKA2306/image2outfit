#!/usr/bin/env python3
"""Procedural heather-jersey material sources for the Siroino bodysuit."""
from __future__ import annotations

import math
from pathlib import Path

import bpy
from PIL import Image

import siroino_strappy_knit_build as base


def make_heather_maps(directory: Path) -> dict[str, Path]:
    """Create subtle, non-periodic heather maps without render-scale moire."""
    directory.mkdir(parents=True, exist_ok=True)
    size = 512
    albedo: list[tuple[int, int, int]] = []
    normal: list[tuple[int, int, int]] = []
    roughness: list[tuple[int, int, int]] = []
    for y in range(size):
        for x in range(size):
            broad = (
                math.sin((x * 0.021 + y * 0.013) * math.tau)
                + 0.55 * math.sin((x * 0.008 - y * 0.017) * math.tau + 1.7)
            )
            fiber = math.sin((x * 0.113 + y * 0.071) * math.tau + 0.4)
            fleck = math.sin(x * 0.173 + y * 0.289) * math.sin(x * 0.061 - y * 0.097)
            value = max(78, min(112, int(94 + 3.5 * broad + 2.0 * fiber + 2.2 * fleck)))
            albedo.append((value - 2, value, min(255, value + 3)))
            normal.append(
                (
                    int(128 + 3.0 * fiber + 1.4 * fleck),
                    int(128 + 2.6 * broad),
                    254,
                )
            )
            rough = max(188, min(218, int(202 + 5 * abs(fleck) + 3 * abs(broad))))
            roughness.append((rough, rough, rough))
    paths = {
        "albedo": directory / "heather_grey_albedo.png",
        "normal": directory / "heather_grey_normal.png",
        "roughness": directory / "heather_grey_roughness.png",
    }
    for key, pixels in (
        ("albedo", albedo),
        ("normal", normal),
        ("roughness", roughness),
    ):
        image = Image.new("RGB", (size, size))
        image.putdata(pixels)
        image.save(paths[key], optimize=True)
    return paths


def create_materials(
    texture_dir: Path,
) -> tuple[
    dict[str, Path],
    bpy.types.Material,
    bpy.types.Material,
    bpy.types.Material,
]:
    textures = make_heather_maps(texture_dir)
    fabric = base.textured_material(
        "MAT_Heather_Grey_Jersey",
        textures["albedo"],
        textures["normal"],
        textures["roughness"],
        normal_strength=0.075,
        sheen=0.06,
    )
    shader = next(
        node for node in fabric.node_tree.nodes if node.type == "BSDF_PRINCIPLED"
    )
    shader.inputs["IOR"].default_value = 1.46
    if "Coat Weight" in shader.inputs:
        shader.inputs["Coat Weight"].default_value = 0.008
    fabric.diffuse_color = (0.112, 0.118, 0.132, 1.0)
    trim = base.plain_material(
        "MAT_Heather_Rib_Trim",
        (0.145, 0.152, 0.170, 1.0),
        roughness=0.82,
    )
    buttons = base.plain_material(
        "MAT_Pearl_Grey_Buttons",
        (0.34, 0.36, 0.41, 1.0),
        roughness=0.40,
        metallic=0.03,
    )
    return textures, fabric, trim, buttons
