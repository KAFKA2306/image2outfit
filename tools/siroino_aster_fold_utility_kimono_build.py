#!/usr/bin/env python3
"""Build the Issue #596 Aster Fold Utility Kimono structural candidate."""

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


PRODUCT_ID = "siroino-aster-fold-utility-kimono-set"


def args():
    return structural.args()


def sleeve(name: str, side: float, mat):
    bpy.ops.mesh.primitive_cone_add(
        vertices=24,
        radius1=0.050,
        radius2=0.074,
        depth=0.28,
        location=(side * 0.245, 0.005, 0.96),
        rotation=(0.0, side * math.radians(76.0), 0.0),
    )
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    return obj


def folded_plate(name: str, loc, rotation_z: float, mat, width: float = 0.064):
    obj = structural.cube(name, loc, (width, 0.014, 0.028), mat, bevel=0.006)
    obj.rotation_euler[2] = math.radians(rotation_z)
    return obj


def build(job: dict):
    if job["id"] != PRODUCT_ID:
        raise ValueError(f"unexpected product: {job['id']}")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    armature = structural.import_target_armature(job)
    armature.name = "AsterArmature"
    armature.data.name = "AsterArmatureData"

    kimono = structural.material("MAT_Kimono", (0.82, 0.79, 0.69, 1), 0.78)
    inner = structural.material("MAT_Inner", (0.075, 0.085, 0.10, 1), 0.72)
    skort_obi = structural.material("MAT_SkortObi", (0.12, 0.13, 0.15, 1), 0.70)
    hero = structural.material("MAT_Hero", (0.55, 0.19, 0.12, 1), 0.62)
    hardware = structural.material("MAT_Hardware", (0.09, 0.10, 0.11, 1), 0.40)

    made = [
        # Overlap the torso panels at the center and side seams so the narrow
        # target torso is covered in the neutral pose.
        structural.cube(
            "kimono_back", (0.0, 0.045, 0.86), (0.165, 0.020, 0.205), kimono
        ),
        structural.cube(
            "kimono_front_L", (-0.074, -0.082, 0.86), (0.094, 0.020, 0.205), kimono
        ),
        structural.cube(
            "kimono_front_R", (0.074, -0.082, 0.85), (0.094, 0.020, 0.205), kimono
        ),
        structural.cube(
            "shoulder_L", (-0.118, 0.006, 0.977), (0.052, 0.040, 0.070), kimono
        ),
        structural.cube(
            "shoulder_R", (0.118, 0.006, 0.977), (0.052, 0.040, 0.070), kimono
        ),
        # Siroino's UpperArm_L is the positive-X arm in the imported rig.
        sleeve("sleeve_L", 1.0, kimono),
        sleeve("sleeve_R", -1.0, kimono),
        structural.cube(
            "sleeve_facing_L",
            (0.384, 0.006, 0.958),
            (0.030, 0.050, 0.035),
            hero,
            0.005,
        ),
        structural.cube(
            "sleeve_facing_R",
            (-0.384, 0.006, 0.958),
            (0.030, 0.050, 0.035),
            hero,
            0.005,
        ),
        structural.cube(
            "inner_front", (0.0, -0.125, 0.805), (0.078, 0.018, 0.185), inner
        ),
        structural.cube(
            "inner_back", (0.0, 0.045, 0.805), (0.145, 0.018, 0.185), inner
        ),
        structural.cube(
            "skort_front_L", (-0.068, -0.078, 0.585), (0.078, 0.020, 0.135), skort_obi
        ),
        structural.cube(
            "skort_front_R", (0.068, -0.080, 0.575), (0.078, 0.020, 0.135), skort_obi
        ),
        structural.cube(
            "skort_back", (0.0, 0.045, 0.585), (0.145, 0.020, 0.135), skort_obi
        ),
        structural.cube(
            "waistband_outer", (0.0, -0.102, 0.625), (0.155, 0.018, 0.025), skort_obi
        ),
        structural.cube(
            "waistband_inner", (0.0, 0.045, 0.625), (0.155, 0.018, 0.025), skort_obi
        ),
        structural.cube(
            "obi_base_front", (0.0, -0.125, 0.635), (0.150, 0.016, 0.034), skort_obi
        ),
        structural.cube(
            "obi_base_back", (0.0, 0.068, 0.635), (0.150, 0.016, 0.034), skort_obi
        ),
    ]

    made.extend(
        [
            folded_plate("aster_fold_outer", (-0.018, -0.145, 0.642), -12.0, hero),
            folded_plate("aster_fold_inner", (0.026, -0.151, 0.626), 13.0, hero, 0.058),
            folded_plate(
                "aster_fold_facing_outer",
                (-0.018, -0.163, 0.642),
                -12.0,
                hardware,
                0.050,
            ),
            folded_plate(
                "aster_fold_facing_inner", (0.026, -0.169, 0.626), 13.0, hardware, 0.045
            ),
        ]
    )

    structural.uv_all(made)
    sleeves = [obj for obj in made if obj.name in {"sleeve_L", "sleeve_R"}]
    facings = [
        obj for obj in made if obj.name in {"sleeve_facing_L", "sleeve_facing_R"}
    ]
    shoulders = [obj for obj in made if obj.name in {"shoulder_L", "shoulder_R"}]
    torso = [
        obj
        for obj in made
        if obj not in sleeves and obj not in facings and obj not in shoulders
    ]

    structural.bind_to_bone(torso, armature, "Hips")
    structural.bind_to_bone(shoulders, armature, "Chest")
    structural.bind_to_bone([sleeves[0]], armature, "UpperArm_L")
    structural.bind_to_bone([sleeves[1]], armature, "UpperArm_R")
    structural.bind_to_bone([facings[0]], armature, "LowerArm_L")
    structural.bind_to_bone([facings[1]], armature, "LowerArm_R")

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
        raise RuntimeError("Aster Fold structural outputs were not created")
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
