#!/usr/bin/env python3
"""Minimal runtime bridge for the current Wide Cargo implementation.

This module intentionally contains no product geometry or historical refit logic.
It preserves the small build/material/save API imported by the current v36
implementation while keeping the active product entrypoint stable.
"""
from __future__ import annotations

import sys

import bpy

import siroino_wide_cargo_build as build


def tune_material(
    material: bpy.types.Material,
    *,
    base: tuple[float, float, float],
    roughness: float,
    metallic: float = 0.0,
) -> None:
    material.diffuse_color = (*base, 1.0)
    material.use_nodes = True
    shader = (
        material.node_tree.nodes.get("Principled BSDF")
        if material.node_tree is not None
        else None
    )
    if shader is None:
        return
    if "Base Color" in shader.inputs:
        shader.inputs["Base Color"].default_value = (*base, 1.0)
    if "Roughness" in shader.inputs:
        shader.inputs["Roughness"].default_value = roughness
    if "Metallic" in shader.inputs:
        shader.inputs["Metallic"].default_value = metallic


def save_distribution_blend() -> None:
    _, job = build.c.load_job()
    blend_path = build.c.repo_path(job["blendPath"])
    for obj in list(bpy.data.objects):
        preview_only = (
            obj.name.startswith("SiroinoSotai_PC")
            or obj.name == "Studio_Floor"
            or obj.name == "Product_Camera"
            or obj.type in {"LIGHT", "CAMERA"}
        )
        if preview_only:
            bpy.data.objects.remove(obj, do_unlink=True)
    for collection in (bpy.data.meshes, bpy.data.materials, bpy.data.images):
        for datablock in list(collection):
            if datablock.users == 0:
                collection.remove(datablock)
    blend_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)


base = sys.modules[__name__]
