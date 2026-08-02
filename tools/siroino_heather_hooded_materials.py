#!/usr/bin/env python3
"""Procedural material sources for the Siroino heather bodysuit."""
from __future__ import annotations

import math
from pathlib import Path

import bpy
from PIL import Image

import siroino_strappy_knit_build as base


def make_heather_maps(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    size = 512
    albedo: list[tuple[int, int, int]] = []
    normal: list[tuple[int, int, int]] = []
    roughness: list[tuple[int, int, int]] = []
    for y in range(size):
        for x in range(size):
            yarn = math.sin((x + y * 0.31) * math.tau / 7.0)
            cross = math.sin((y - x * 0.17) * math.tau / 11.0)
            fleck = math.sin(x * 0.73 + y * 1.17) * math.sin(x * 0.19 - y * 0.41)
            value = max(130, min(215, int(174 + 8 * yarn + 5 * cross + 4 * fleck)))
            albedo.append((value - 4, value, min(255, value + 8)))
            normal.append((int(128 + 20 * yarn), int(128 + 12 * cross), 251))
            rough = int(180 + 16 * abs(fleck) + 7 * (1.0 - abs(yarn)))
            roughness.append((rough, rough, rough))
    paths = {
        "albedo": directory / "heather_grey_albedo.png",
        "normal": directory / "heather_grey_normal.png",
        "roughness": directory / "heather_grey_roughness.png",
    }
    for key, pixels in (("albedo", albedo), ("normal", normal), ("roughness", roughness)):
        image = Image.new("RGB", (size, size))
        image.putdata(pixels)
        image.save(paths[key], optimize=True)
    return paths


def create_materials(texture_dir: Path) -> tuple[dict[str, Path], bpy.types.Material, bpy.types.Material, bpy.types.Material]:
    textures = make_heather_maps(texture_dir)
    fabric = base.textured_material(
        "MAT_Heather_Grey_Jersey",
        textures["albedo"],
        textures["normal"],
        textures["roughness"],
        normal_strength=0.34,
        sheen=0.18,
    )
    shader = next(node for node in fabric.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    shader.inputs["IOR"].default_value = 1.46
    if "Coat Weight" in shader.inputs:
        shader.inputs["Coat Weight"].default_value = 0.035
    trim = base.plain_material(
        "MAT_Heather_Rib_Trim", (0.43, 0.47, 0.54, 1.0), roughness=0.72
    )
    buttons = base.plain_material(
        "MAT_Pearl_Grey_Buttons", (0.59, 0.62, 0.68, 1.0), roughness=0.30, metallic=0.08
    )
    return textures, fabric, trim, buttons
