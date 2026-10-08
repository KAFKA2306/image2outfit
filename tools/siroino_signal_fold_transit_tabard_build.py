#!/usr/bin/env python3
"""Build the Issue #669 Signal Fold Transit Tabard candidate."""

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


PRODUCT_ID = "siroino-signal-fold-transit-tabard"


def args():
    return structural.args()


def sleeve(name: str, side: float, mat):
    bpy.ops.mesh.primitive_cone_add(
        vertices=24,
        radius1=0.034,
        radius2=0.046,
        depth=0.31,
        location=(side * 0.305, 0.006, 0.965),
        rotation=(0.0, side * math.radians(75.0), 0.0),
    )
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    return obj


def tilted_plate(name: str, location, scale, mat, angle: float):
    obj = structural.cube(name, location, scale, mat, bevel=0.007)
    obj.rotation_euler[1] = math.radians(angle)
    return obj


def tapered_panel(
    name: str,
    x_top: float,
    x_bottom: float,
    y: float,
    z_top: float,
    z_bottom: float,
    depth: float,
    mat,
    bevel: float = 0.009,
):
    """Create a thin, tapered garment panel instead of a boxy apron block."""
    verts = [
        (-x_bottom, y - depth, z_bottom),
        (x_bottom, y - depth, z_bottom),
        (x_top, y - depth, z_top),
        (-x_top, y - depth, z_top),
        (-x_bottom, y + depth, z_bottom),
        (x_bottom, y + depth, z_bottom),
        (x_top, y + depth, z_top),
        (-x_top, y + depth, z_top),
    ]
    faces = [
        (0, 1, 2, 3),
        (7, 6, 5, 4),
        (0, 4, 5, 1),
        (1, 5, 6, 2),
        (2, 6, 7, 3),
        (3, 7, 4, 0),
    ]
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(mat)
    modifier = obj.modifiers.new("GarmentEdge", "BEVEL")
    modifier.width = bevel
    modifier.segments = 2
    return obj


def build(job: dict):
    if job["id"] != PRODUCT_ID:
        raise ValueError(f"unexpected product: {job['id']}")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    armature = structural.import_target_armature(job)
    armature.name = "SignalFoldArmature"
    armature.data.name = "SignalFoldArmatureData"

    tabard = structural.material("MAT_Tabard", (0.08, 0.11, 0.16, 1), 0.82)
    underlayer = structural.material("MAT_Underlayer", (0.22, 0.27, 0.33, 1), 0.80)
    signal = structural.material("MAT_SignalFold", (0.50, 0.34, 0.12, 1), 0.62)
    hardware = structural.material("MAT_Hardware", (0.16, 0.18, 0.20, 1), 0.48)

    made = [
        # Closed knee-above tabard shell with no exposed midriff or lower garment.
        tapered_panel(
            "tabard_front_under",
            0.165,
            0.190,
            -0.125,
            0.915,
            0.360,
            0.026,
            tabard,
            bevel=0.012,
        ),
        tapered_panel(
            "tabard_front_over",
            0.105,
            0.130,
            -0.165,
            0.845,
            0.620,
            0.018,
            tabard,
            bevel=0.009,
        ),
        tapered_panel(
            "tabard_back",
            0.165,
            0.190,
            0.075,
            0.915,
            0.360,
            0.026,
            tabard,
            bevel=0.012,
        ),
        structural.cube(
            "underlayer_front",
            (0.0, -0.178, 0.885),
            (0.120, 0.014, 0.045),
            underlayer,
            bevel=0.006,
        ),
        structural.cube(
            "underlayer_back",
            (0.0, 0.060, 0.885),
            (0.120, 0.014, 0.045),
            underlayer,
            bevel=0.006,
        ),
        structural.cube(
            "neck_facing",
            (0.0, -0.035, 0.910),
            (0.105, 0.030, 0.028),
            hardware,
            bevel=0.007,
        ),
        structural.cube(
            "armhole_facing_L",
            (-0.170, -0.155, 0.855),
            (0.012, 0.010, 0.055),
            tabard,
            bevel=0.003,
        ),
        structural.cube(
            "armhole_facing_R",
            (0.170, -0.155, 0.855),
            (0.012, 0.010, 0.055),
            tabard,
            bevel=0.003,
        ),
        structural.cube(
            "center_back_vent",
            (0.0, 0.105, 0.455),
            (0.040, 0.012, 0.018),
            hardware,
            bevel=0.003,
        ),
        sleeve("underlayer_sleeve_L", 1.0, underlayer),
        sleeve("underlayer_sleeve_R", -1.0, underlayer),
        structural.cube(
            "underlayer_cuff_L",
            (0.455, 0.006, 0.965),
            (0.030, 0.050, 0.036),
            underlayer,
            bevel=0.006,
        ),
        structural.cube(
            "underlayer_cuff_R",
            (-0.455, 0.006, 0.965),
            (0.030, 0.050, 0.036),
            underlayer,
            bevel=0.006,
        ),
    ]

    for side, label in [(-1.0, "L"), (1.0, "R")]:
        # Two side-fold wedges, each made of three readable depth plates.
        made.extend(
            [
                structural.cube(
                    f"side_wedge_root_{label}",
                    (side * 0.160, -0.115, 0.610),
                    (0.012, 0.018, 0.105),
                    hardware,
                    bevel=0.004,
                ),
                tilted_plate(
                    f"side_wedge_{label}",
                    (side * 0.180, -0.145, 0.610),
                    (0.027, 0.021, 0.105),
                    tabard,
                    side * 14.0,
                ),
                tilted_plate(
                    f"side_wedge_fold_A_{label}",
                    (side * 0.198, -0.135, 0.610),
                    (0.022, 0.019, 0.105),
                    tabard,
                    side * 27.0,
                ),
                tilted_plate(
                    f"side_wedge_fold_B_{label}",
                    (side * 0.214, -0.125, 0.610),
                    (0.017, 0.017, 0.105),
                    signal,
                    side * 38.0,
                ),
            ]
        )

    # Short, bounded diagonal Hero closure with actual overlap depth.
    made.extend(
        [
            tilted_plate(
                "signal_fold_root",
                (0.0, -0.198, 0.830),
                (0.014, 0.012, 0.080),
                hardware,
                -22.0,
            ),
            tilted_plate(
                "signal_fold_outer",
                (-0.040, -0.205, 0.805),
                (0.012, 0.014, 0.090),
                signal,
                -22.0,
            ),
            tilted_plate(
                "signal_fold_inner",
                (0.035, -0.212, 0.770),
                (0.010, 0.012, 0.075),
                hardware,
                -22.0,
            ),
            structural.cube(
                "signal_fold_lock",
                (0.018, -0.225, 0.745),
                (0.014, 0.012, 0.014),
                signal,
                bevel=0.004,
            ),
        ]
    )

    structural.uv_all(made)
    sleeves = [
        obj
        for obj in made
        if obj.name in {"underlayer_sleeve_L", "underlayer_sleeve_R"}
    ]
    cuffs = [
        obj for obj in made if obj.name in {"underlayer_cuff_L", "underlayer_cuff_R"}
    ]
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
        raise RuntimeError("Signal Fold structural outputs were not created")
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
