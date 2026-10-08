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


def material(
    name: str, rgba: tuple[float, float, float, float], roughness: float = 0.72
):
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
        radius1=0.038,
        radius2=0.052,
        depth=0.30,
        location=(side * 0.23, 0.006, 1.018),
        rotation=(0, side * math.radians(78), 0),
    )
    o = bpy.context.object
    o.name = name
    o.data.materials.append(mat)
    return o


def hero_piece(name: str, side: float, index: int, mat, family: str):
    z = 0.61 - index * 0.045
    x = side * (0.145 + index * 0.025)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, -0.005, z))
    o = bpy.context.object
    o.name = name
    if family == "arc_latch":
        o.scale = (0.055, 0.016, 0.018)
        o.rotation_euler[1] = side * math.radians(8 + index * 5)
        o.rotation_euler[2] = side * math.radians(12 + index * 3)
    else:
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


def import_target_armature(job: dict) -> bpy.types.Object:
    """Keep the exact target skeleton for deterministic pose evaluation.

    The structural generator intentionally does not redistribute the target
    avatar mesh.  It only retains the licensed armature as the deformation
    authority for the generated garment.
    """
    source = resolve(job["targetSourcePath"])
    if not source.is_file():
        raise FileNotFoundError(f"target source not found: {source}")
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.fbx(filepath=str(source), use_anim=False)
    imported = [obj for obj in bpy.context.scene.objects if obj not in before]
    armatures = [obj for obj in imported if obj.type == "ARMATURE"]
    if len(armatures) != 1:
        raise RuntimeError(
            f"expected exactly one target armature, found {len(armatures)}"
        )
    armature = armatures[0]
    armature.name = "ArcLatchArmature"
    armature.data.name = "ArcLatchArmatureData"
    for obj in imported:
        if obj is not armature:
            bpy.data.objects.remove(obj, do_unlink=True)
    return armature


def bind_to_bone(
    objects: list[bpy.types.Object], armature: bpy.types.Object, bone: str
) -> None:
    """Bind a structural group to one canonical humanoid bone."""
    if armature.pose.bones.get(bone) is None:
        raise RuntimeError(f"target armature is missing required bone: {bone}")
    for obj in objects:
        if obj.type != "MESH":
            continue
        # Armature deformation expects garment vertices in the armature's
        # rest-space.  The procedural primitives are created with their
        # placement stored on the object transform; bake that placement before
        # adding the modifier so pose changes rotate around the target bone
        # instead of around the primitive origin.
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        modifier = obj.modifiers.new("SiroinoArmature", "ARMATURE")
        modifier.object = armature
        group = obj.vertex_groups.new(name=bone)
        group.add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")


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

    arc_latch = "arc-latch" in product
    bpy.ops.wm.read_factory_settings(use_empty=True)
    armature = import_target_armature(job)
    shell = material("MAT_Shell", (0.78, 0.73, 0.62, 1))
    inner = material("MAT_Inner", (0.28, 0.34, 0.40, 1))
    bottoms = material("MAT_Bottoms", (0.10, 0.11, 0.13, 1))
    hero = material("MAT_Hero", (0.48, 0.25, 0.14, 1), 0.62)
    hardware = material("MAT_Hardware", (0.08, 0.09, 0.10, 1), 0.38)

    upper = "bomber" if arc_latch else "jacket"
    bottom = "short" if arc_latch else "bottom"
    made = [
        cube(f"{upper}_back", (0, 0.060, 0.82), (0.125, 0.012, 0.19), shell),
        cube(f"{upper}_front_L", (-0.064, -0.108, 0.82), (0.059, 0.012, 0.19), shell),
        cube(f"{upper}_front_R", (0.064, -0.108, 0.82), (0.059, 0.012, 0.19), shell),
        sleeve("sleeve_L", -1, shell),
        sleeve("sleeve_R", 1, shell),
        cube("cuff_L", (-0.390, 0.006, 1.018), (0.028, 0.047, 0.042), shell, 0.006),
        cube("cuff_R", (0.390, 0.006, 1.018), (0.028, 0.047, 0.042), shell, 0.006),
        cube("inner_front", (0, -0.105, 0.68), (0.105, 0.012, 0.115), inner),
        cube("inner_back", (0, 0.060, 0.68), (0.105, 0.012, 0.115), inner),
        cube(f"{bottom}_front", (0, -0.090, 0.49), (0.115, 0.014, 0.13), bottoms),
        cube(f"{bottom}_back", (0, 0.055, 0.49), (0.115, 0.014, 0.13), bottoms),
        cube("waistband_outer", (0, -0.095, 0.625), (0.125, 0.010, 0.018), inner),
        cube("waistband_inner", (0, 0.060, 0.625), (0.125, 0.010, 0.018), inner),
    ]
    for side, label in [(-1, "L"), (1, "R")]:
        made.extend(
            [
                cube(
                    f"side_placket_front_{label}",
                    (side * 0.120, -0.105, 0.65),
                    (0.012, 0.010, 0.085),
                    hero,
                    0.004,
                ),
                cube(
                    f"side_placket_back_{label}",
                    (side * 0.120, 0.060, 0.65),
                    (0.012, 0.010, 0.085),
                    hero,
                    0.004,
                ),
            ]
        )
        root_name = f"arc_latch_root_{label}_A" if arc_latch else f"hinge_root_{label}"
        made.append(
            cube(
                root_name,
                (side * 0.135, -0.004, 0.65),
                (0.015, 0.018, 0.075),
                hardware,
                0.004,
            )
        )
        for i, suffix in enumerate("ABC"):
            hero_name = (
                f"arc_latch_{label}_{suffix}"
                if arc_latch
                else f"pannier_{label}_{suffix}"
            )
            made.append(
                hero_piece(
                    hero_name, side, i, hero, "arc_latch" if arc_latch else "pannier"
                )
            )
            if arc_latch and suffix != "A":
                made.append(
                    cube(
                        f"arc_latch_root_{label}_{suffix}",
                        (side * 0.135, -0.004, 0.65 - i * 0.045),
                        (0.015, 0.018, 0.022),
                        hardware,
                        0.004,
                    )
                )
    uv_all(made)

    torso = [
        obj
        for obj in made
        if obj.name.startswith(
            (
                "bomber_",
                "inner_",
                "short_",
                "waistband_",
                "side_placket_",
                "arc_latch_root_",
            )
        )
    ]
    sleeves = [obj for obj in made if obj.name in {"sleeve_L", "sleeve_R"}]
    cuffs = [obj for obj in made if obj.name in {"cuff_L", "cuff_R"}]
    heroes = [
        obj
        for obj in made
        if obj.name.startswith("arc_latch_") and "root" not in obj.name
    ]
    bind_to_bone(torso, armature, "Hips")
    bind_to_bone(heroes, armature, "Hips")
    bind_to_bone(
        [obj for obj in sleeves if obj.name == "sleeve_L"], armature, "UpperArm_L"
    )
    bind_to_bone(
        [obj for obj in sleeves if obj.name == "sleeve_R"], armature, "UpperArm_R"
    )
    bind_to_bone([obj for obj in cuffs if obj.name == "cuff_L"], armature, "LowerArm_L")
    bind_to_bone([obj for obj in cuffs if obj.name == "cuff_R"], armature, "LowerArm_R")

    blend = resolve(job["blendPath"])
    fbx = resolve(job["fbxAssetPath"])
    blend.parent.mkdir(parents=True, exist_ok=True)
    fbx.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
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
        raise RuntimeError(
            "structural garment export did not materialize expected outputs"
        )
    print(
        json.dumps(
            {
                "product": product,
                "meshObjects": len(made),
                "blend": str(blend),
                "fbx": str(fbx),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
