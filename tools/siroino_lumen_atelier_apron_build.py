#!/usr/bin/env python3
"""Build the Issue #670 Lumen Atelier maker coat-dress candidate."""

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


PRODUCT_ID = "siroino-lumen-atelier-apron"


def args():
    return structural.args()


def sleeve(name: str, side: float, mat):
    bpy.ops.mesh.primitive_cone_add(
        vertices=24,
        radius1=0.044,
        radius2=0.062,
        depth=0.28,
        location=(side * 0.225, 0.006, 0.965),
        rotation=(0.0, side * math.radians(75.0), 0.0),
    )
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    return obj


def tray_plate(
    name: str,
    side: float,
    x: float,
    y: float,
    z: float,
    mat,
    angle: float,
):
    obj = structural.cube(
        name, (side * x, y, z), (0.042, 0.032, 0.105), mat, bevel=0.007
    )
    obj.rotation_euler[1] = side * math.radians(angle)
    return obj


def build(job: dict):
    if job["id"] != PRODUCT_ID:
        raise ValueError(f"unexpected product: {job['id']}")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    armature = structural.import_target_armature(job)
    armature.name = "LumenAtelierArmature"
    armature.data.name = "LumenAtelierArmatureData"

    shell = structural.material("MAT_MakerShell", (0.52, 0.56, 0.52, 1), 0.82)
    facing = structural.material("MAT_MakerFacing", (0.86, 0.84, 0.76, 1), 0.76)
    reinforcement = structural.material(
        "MAT_TrayReinforcement", (0.18, 0.12, 0.08, 1), 0.70
    )
    tray_inner = structural.material("MAT_TrayInner", (0.28, 0.30, 0.27, 1), 0.78)
    hardware = structural.material("MAT_Hardware", (0.34, 0.25, 0.12, 1), 0.52)

    made = [
        # One continuous maker coat-dress shell from collar to knee line.
        structural.cube(
            "maker_front_L",
            (-0.090, -0.125, 0.700),
            (0.130, 0.026, 0.520),
            shell,
            bevel=0.012,
        ),
        structural.cube(
            "maker_front_R",
            (0.090, -0.125, 0.700),
            (0.130, 0.026, 0.520),
            shell,
            bevel=0.012,
        ),
        structural.cube(
            "maker_center_front",
            (0.0, -0.177, 0.700),
            (0.045, 0.022, 0.500),
            shell,
            bevel=0.009,
        ),
        structural.cube(
            "maker_back",
            (0.0, 0.075, 0.700),
            (0.190, 0.026, 0.520),
            shell,
            bevel=0.012,
        ),
        structural.cube(
            "maker_shoulder_L",
            (-0.145, -0.040, 0.925),
            (0.052, 0.036, 0.050),
            shell,
            bevel=0.009,
        ),
        structural.cube(
            "maker_shoulder_R",
            (0.145, -0.040, 0.925),
            (0.052, 0.036, 0.050),
            shell,
            bevel=0.009,
        ),
        structural.cube(
            "collar",
            (0.0, -0.035, 0.910),
            (0.108, 0.032, 0.028),
            facing,
            bevel=0.008,
        ),
        structural.cube(
            "front_facing_L",
            (-0.030, -0.158, 0.820),
            (0.016, 0.010, 0.115),
            facing,
            bevel=0.004,
        ),
        structural.cube(
            "front_facing_R",
            (0.030, -0.158, 0.820),
            (0.016, 0.010, 0.115),
            facing,
            bevel=0.004,
        ),
        structural.cube(
            "center_walking_vent",
            (0.0, 0.106, 0.445),
            (0.042, 0.012, 0.018),
            facing,
            bevel=0.004,
        ),
        structural.cube(
            "chest_slot_L",
            (-0.072, -0.160, 0.825),
            (0.030, 0.009, 0.025),
            hardware,
            bevel=0.003,
        ),
        structural.cube(
            "chest_slot_R",
            (0.072, -0.160, 0.825),
            (0.030, 0.009, 0.025),
            hardware,
            bevel=0.003,
        ),
        sleeve("sleeve_L", 1.0, shell),
        sleeve("sleeve_R", -1.0, shell),
        structural.cube(
            "cuff_L", (0.385, 0.006, 0.965), (0.030, 0.050, 0.036), facing, bevel=0.006
        ),
        structural.cube(
            "cuff_R", (-0.385, 0.006, 0.965), (0.030, 0.050, 0.036), facing, bevel=0.006
        ),
    ]

    for side, label in [(-1.0, "L"), (1.0, "R")]:
        # Each side tray has a rooted hinge, an outer shell and a separately
        # readable inner shell. The gap is deliberate physical tray depth,
        # not a texture-only pocket or a hanging pouch.
        made.extend(
            [
                structural.cube(
                    f"worktray_root_{label}",
                    (side * 0.158, -0.080, 0.595),
                    (0.018, 0.032, 0.115),
                    reinforcement,
                    bevel=0.006,
                ),
                tray_plate(
                    f"worktray_outer_{label}",
                    side,
                    0.230,
                    -0.082,
                    0.595,
                    reinforcement,
                    12.0,
                ),
                tray_plate(
                    f"worktray_inner_{label}",
                    side,
                    0.184,
                    -0.142,
                    0.595,
                    tray_inner,
                    -8.0,
                ),
                structural.cube(
                    f"tray_facing_{label}",
                    (side * 0.230, -0.116, 0.595),
                    (0.010, 0.010, 0.112),
                    hardware,
                    bevel=0.003,
                ),
            ]
        )

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
        raise RuntimeError("Lumen Atelier structural outputs were not created")
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
