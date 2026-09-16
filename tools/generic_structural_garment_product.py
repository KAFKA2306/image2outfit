#!/usr/bin/env python3
"""Shared schema-v2 builder for panel-sewn structural garments."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]


def args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    p = argparse.ArgumentParser()
    p.add_argument("--job", required=True)
    return p.parse_args(raw)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def resolve(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (ROOT / p).resolve()


def material(name: str, rgba: tuple[float, float, float, float], roughness: float = 0.72):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = rgba
    bsdf.inputs["Roughness"].default_value = roughness
    return m


def cube(name: str, loc, scale, mat, bevel=0.008):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.object
    o.name = name
    o.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    b = o.modifiers.new("GarmentEdge", "BEVEL")
    b.width = bevel
    b.segments = 2
    o.data.materials.append(mat)
    return o


def sleeve(name: str, side: float, mat):
    bpy.ops.mesh.primitive_cone_add(
        vertices=20,
        radius1=0.052,
        radius2=0.072,
        depth=0.34,
        location=(side * 0.19, 0, 0.91),
        rotation=(0, math.radians(78), 0),
    )
    o = bpy.context.object
    o.name = name
    o.data.materials.append(mat)
    return o


def pannier(name: str, side: float, index: int, mat):
    z = 0.61 - index * 0.045
    x = side * (0.145 + index * 0.025)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, -0.005, z))
    o = bpy.context.object
    o.name = name
    o.scale = (0.072, 0.014, 0.12)
    o.rotation_euler[1] = side * math.radians(10 + index * 8)
    o.rotation_euler[2] = side * math.radians(5 + index * 4)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    b = o.modifiers.new("BoundedThickness", "BEVEL")
    b.width = 0.008
    b.segments = 3
    o.data.materials.append(mat)
    return o


def uv_all(objects):
    for o in objects:
        if o.type != "MESH":
            continue
        bpy.context.view_layer.objects.active = o
        o.select_set(True)
        for other in bpy.context.selected_objects:
            if other != o:
                other.select_set(False)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(island_margin=0.03)
        bpy.ops.object.mode_set(mode="OBJECT")


def main() -> int:
    job_path = Path(args().job).resolve()
    job = load(job_path)
    if job.get("schemaVersion") != 2:
        raise ValueError("generic structural garment builder requires schemaVersion 2")
    product = job["id"]
    contract_dir = job_path.parent
    construction = load(contract_dir / "construction.json")
    decomposition = load(contract_dir / "pattern-draft.json")
    if construction.get("profile") != "panel-sewn":
        raise ValueError("builder only accepts profile=panel-sewn")
    if decomposition.get("productId") != product:
        raise ValueError("pattern draft productId mismatch")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    shell = material("MAT_Shell", (0.78, 0.73, 0.62, 1))
    inner = material("MAT_Inner", (0.28, 0.34, 0.40, 1))
    bottoms = material("MAT_Bottoms", (0.10, 0.11, 0.13, 1))
    hero = material("MAT_Hero", (0.48, 0.25, 0.14, 1), 0.62)
    hardware = material("MAT_Hardware", (0.08, 0.09, 0.10, 1), 0.38)

    # Conservative Siroino-scale envelope. The prior dimensions were visibly oversized
    # in pose evidence, so keep the shell close to the body while preserving the pannier hero detail.
    made = [
        cube("jacket_back", (0, 0.035, 0.82), (0.125, 0.018, 0.19), shell),
        cube("jacket_front_L", (-0.064, -0.038, 0.82), (0.059, 0.018, 0.19), shell),
        cube("jacket_front_R", (0.064, -0.038, 0.82), (0.059, 0.018, 0.19), shell),
        sleeve("sleeve_L", -1, shell),
        sleeve("sleeve_R", 1, shell),
        cube("inner_front", (0, -0.045, 0.68), (0.105, 0.012, 0.115), inner),
        cube("bottom_front", (0, -0.018, 0.49), (0.115, 0.026, 0.13), bottoms),
        cube("bottom_back", (0, 0.025, 0.49), (0.115, 0.026, 0.13), bottoms),
        cube("waistband_outer", (0, -0.05, 0.625), (0.125, 0.012, 0.018), inner),
    ]
    for side, label in [(-1, "L"), (1, "R")]:
        made.append(cube(f"hinge_root_{label}", (side * 0.135, -0.004, 0.65), (0.015, 0.018, 0.075), hardware, 0.004))
        for i, suffix in enumerate("ABC"):
            made.append(pannier(f"pannier_{label}_{suffix}", side, i, hero))
    uv_all(made)

    blend = resolve(job["blendPath"])
    fbx = resolve(job["fbxAssetPath"])
    blend.parent.mkdir(parents=True, exist_ok=True)
    fbx.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.object.select_all(action="DESELECT")
    for o in made:
        o.select_set(True)
    bpy.ops.export_scene.fbx(
        filepath=str(fbx),
        use_selection=True,
        add_leaf_bones=False,
        bake_anim=False,
        axis_forward="-Z",
        axis_up="Y",
    )
    if not blend.is_file() or not fbx.is_file():
        raise RuntimeError("structural garment export did not materialize expected outputs")
    print(json.dumps({"product": product, "meshObjects": len(made), "blend": str(blend), "fbx": str(fbx)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
