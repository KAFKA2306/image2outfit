#!/usr/bin/env python3
"""Build the Issue #677 Quiet Arc Panel Dress structural candidate."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import generic_structural_garment_product as structural  # noqa: E402


PRODUCT_ID = "siroino-quiet-arc-panel-dress"


def args():
    return structural.args()


def sleeve(name: str, side: float, mat):
    bpy.ops.mesh.primitive_cone_add(
        vertices=24,
        radius1=0.045,
        radius2=0.064,
        depth=0.25,
        location=(side * 0.225, 0.005, 0.96),
        rotation=(0.0, side * math.radians(72.0), 0.0),
    )
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    return obj


def arch_rail(name: str, side: float, inner: bool, mat):
    x = side * (0.200 if inner else 0.255)
    obj = structural.cube(
        name, (x, -0.158, 0.655), (0.016, 0.023, 0.155), mat, bevel=0.008
    )
    obj.rotation_euler[1] = side * math.radians(10.0 if inner else -8.0)
    return obj


def arch_root(name: str, side: float, z: float, mat):
    return structural.cube(
        name,
        (side * 0.225, -0.158, z),
        (0.060, 0.023, 0.016),
        mat,
        bevel=0.006,
    )


def build(job: dict):
    if job["id"] != PRODUCT_ID:
        raise ValueError(f"unexpected product: {job['id']}")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    armature = structural.import_target_armature(job)
    armature.name = "QuietArcArmature"
    armature.data.name = "QuietArcArmatureData"

    shell = structural.material("MAT_ArcShell", (0.78, 0.73, 0.64, 1), 0.80)
    inner = structural.material("MAT_ArcInner", (0.12, 0.14, 0.16, 1), 0.70)
    facing = structural.material("MAT_ArcFacing", (0.25, 0.33, 0.38, 1), 0.65)
    trim = structural.material("MAT_ArcTrim", (0.08, 0.09, 0.10, 1), 0.55)
    hardware = structural.material("MAT_Hardware", (0.24, 0.25, 0.25, 1), 0.45)

    made = [
        # A continuous closed dress shell from stand collar to the knee line.
        structural.cube(
            "arc_front_L",
            (-0.090, -0.130, 0.705),
            (0.130, 0.023, 0.540),
            shell,
            bevel=0.012,
        ),
        structural.cube(
            "arc_front_R",
            (0.090, -0.130, 0.705),
            (0.130, 0.023, 0.540),
            shell,
            bevel=0.012,
        ),
        structural.cube(
            "arc_center_front",
            (0.0, -0.178, 0.705),
            (0.050, 0.020, 0.520),
            shell,
            bevel=0.009,
        ),
        structural.cube(
            "arc_back", (0.0, 0.075, 0.705), (0.185, 0.024, 0.540), shell, bevel=0.012
        ),
        structural.cube(
            "shoulder_L",
            (-0.145, -0.040, 0.925),
            (0.050, 0.035, 0.050),
            shell,
            bevel=0.009,
        ),
        structural.cube(
            "shoulder_R",
            (0.145, -0.040, 0.925),
            (0.050, 0.035, 0.050),
            shell,
            bevel=0.009,
        ),
        structural.cube(
            "stand_collar",
            (0.0, -0.030, 0.905),
            (0.105, 0.030, 0.025),
            shell,
            bevel=0.008,
        ),
        structural.cube(
            "front_facing_L",
            (-0.030, -0.109, 0.825),
            (0.018, 0.012, 0.105),
            facing,
            bevel=0.004,
        ),
        structural.cube(
            "front_facing_R",
            (0.030, -0.109, 0.825),
            (0.018, 0.012, 0.105),
            facing,
            bevel=0.004,
        ),
        structural.cube(
            "center_vent_L",
            (-0.035, 0.074, 0.435),
            (0.030, 0.012, 0.018),
            facing,
            bevel=0.004,
        ),
        structural.cube(
            "center_vent_R",
            (0.035, 0.074, 0.435),
            (0.030, 0.012, 0.018),
            facing,
            bevel=0.004,
        ),
        structural.cube(
            "inner_front",
            (0.0, -0.205, 0.820),
            (0.060, 0.014, 0.140),
            inner,
            bevel=0.006,
        ),
        structural.cube(
            "inner_back", (0.0, 0.065, 0.820), (0.145, 0.014, 0.120), inner, bevel=0.006
        ),
        # Siroino's UpperArm_L is the positive-X arm in the imported rig.
        sleeve("sleeve_L", 1.0, shell),
        sleeve("sleeve_R", -1.0, shell),
        structural.cube(
            "cuff_L", (0.385, 0.006, 0.957), (0.030, 0.050, 0.035), facing, bevel=0.006
        ),
        structural.cube(
            "cuff_R", (-0.385, 0.006, 0.957), (0.030, 0.050, 0.035), facing, bevel=0.006
        ),
        # Explicitly separate the two side frames and their facing strips. The
        # gap between each inner and outer rail is a real negative-space window.
        arch_root("crescent_root_L", 1.0, 0.805, facing),
        arch_root("crescent_root_R", -1.0, 0.805, facing),
        arch_root("crescent_base_L", 1.0, 0.490, facing),
        arch_root("crescent_base_R", -1.0, 0.490, facing),
        arch_rail("crescent_outer_L", 1.0, False, shell),
        arch_rail("crescent_outer_R", -1.0, False, shell),
        arch_rail("crescent_inner_L", 1.0, True, facing),
        arch_rail("crescent_inner_R", -1.0, True, facing),
        structural.cube(
            "crescent_facing_L",
            (0.255, -0.188, 0.655),
            (0.008, 0.010, 0.130),
            hardware,
            bevel=0.003,
        ),
        structural.cube(
            "crescent_facing_R",
            (-0.255, -0.188, 0.655),
            (0.008, 0.010, 0.130),
            hardware,
            bevel=0.003,
        ),
        structural.cube(
            "placket_hardware",
            (0.0, -0.125, 0.835),
            (0.008, 0.008, 0.095),
            trim,
            bevel=0.002,
        ),
    ]

    structural.uv_all(made)
    sleeves = [obj for obj in made if obj.name in {"sleeve_L", "sleeve_R"}]
    cuffs = [obj for obj in made if obj.name in {"cuff_L", "cuff_R"}]
    torso = [obj for obj in made if obj not in sleeves and obj not in cuffs]

    structural.bind_to_bone(torso, armature, "Hips")
    structural.bind_to_bone([sleeves[0]], armature, "UpperArm_L")
    structural.bind_to_bone([sleeves[1]], armature, "UpperArm_R")
    structural.bind_to_bone([cuffs[0]], armature, "LowerArm_L")
    structural.bind_to_bone([cuffs[1]], armature, "LowerArm_R")

    blend = structural.resolve(job["blendPath"])
    fbx = structural.resolve(job["fbxAssetPath"])
    blend.parent.mkdir(parents=True, exist_ok=True)
    fbx.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    for obj in made:
        obj.select_set(True)
    bpy.ops.export_scene.fbx(
        filepath=str(fbx),
        use_selection=True,
        add_leaf_bones=False,
        bake_anim=False,
        axis_forward="-Z",
        axis_up="Y",
    )
    if not blend.is_file() or not fbx.is_file():
        raise RuntimeError("Quiet Arc structural outputs were not created")
    return {
        "product": PRODUCT_ID,
        "meshObjects": len(made),
        "blend": str(blend),
        "fbx": str(fbx),
    }


def main() -> int:
    options = args()
    job_path = Path(options.job).resolve()
    job = json.loads(job_path.read_text(encoding="utf-8-sig"))
    print(json.dumps(build(job), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
