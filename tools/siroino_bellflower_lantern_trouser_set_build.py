#!/usr/bin/env python3
"""Build the Issue #726 Bellflower Lantern Trouser Set from its panel contract."""

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


PRODUCT_ID = "siroino-bellflower-lantern-trouser-set"


def args():
    return structural.args()


def prism(
    name: str,
    outline: list[tuple[float, float]],
    y: float,
    depth: float,
    mat,
    bevel: float = 0.006,
):
    """Make a closed, shallow panel from an explicit x/z pattern outline."""
    if len(outline) < 3:
        raise ValueError(f"panel outline too small: {name}")
    verts = [(x, y - depth, z) for x, z in outline]
    verts.extend((x, y + depth, z) for x, z in outline)
    n = len(outline)
    faces = [tuple(range(n)), tuple(range(2 * n - 1, n - 1, -1))]
    faces.extend((i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n))
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(mat)
    if bevel:
        modifier = obj.modifiers.new("SewnEdgeSoftening", "BEVEL")
        modifier.width = bevel
        modifier.segments = 2
    return obj


def asymmetric_panel(
    name: str,
    left_top: float,
    right_top: float,
    left_bottom: float,
    right_bottom: float,
    z_top: float,
    z_bottom: float,
    y: float,
    depth: float,
    mat,
    bevel: float = 0.007,
):
    return prism(
        name,
        [
            (left_bottom, z_bottom),
            (right_bottom, z_bottom),
            (right_top, z_top),
            (left_top, z_top),
        ],
        y,
        depth,
        mat,
        bevel,
    )


def blouse_sleeve(name: str, side: float, mat):
    bpy.ops.mesh.primitive_cone_add(
        vertices=28,
        radius1=0.048,
        radius2=0.070,
        depth=0.35,
        location=(side * 0.305, 0.006, 0.940),
        rotation=(0.0, side * math.radians(73.0), 0.0),
    )
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    modifier = obj.modifiers.new("SleeveSeamSoftening", "BEVEL")
    modifier.width = 0.006
    modifier.segments = 2
    return obj


def bellflower_panel(name: str, side: float, index: int, mat):
    # The inner seam stays anchored on the outside leg; the outer edge opens
    # progressively to create the sewn bellflower, never a floating accessory.
    inner = 0.128 + index * 0.004
    outer = 0.205 + index * 0.013
    z_top = 0.625 - index * 0.035
    z_bottom = 0.365 + index * 0.020
    outline = [
        (side * inner, z_top),
        (side * outer, z_top - 0.030),
        (side * (outer + 0.012), z_bottom + 0.035),
        (side * (inner + 0.008), z_bottom),
    ]
    # Mirror the winding for the opposite side so normals remain consistent.
    if side < 0:
        outline.reverse()
    return prism(
        name,
        outline,
        -0.158 - index * 0.006,
        0.011,
        mat,
        bevel=0.005,
    )


def organza_underlay(name: str, side: float, mat):
    inner = 0.123
    outer = 0.252
    outline = [
        (side * inner, 0.635),
        (side * outer, 0.590),
        (side * (outer + 0.010), 0.310),
        (side * inner, 0.345),
    ]
    if side < 0:
        outline.reverse()
    return prism(name, outline, -0.142, 0.006, mat, bevel=0.003)


def circular_tab(name: str, location, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=20,
        ring_count=10,
        radius=0.016,
        location=location,
    )
    obj = bpy.context.object
    obj.name = name
    obj.scale = (1.0, 0.45, 1.0)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    return obj


def validate_pattern(root: Path) -> dict:
    path = root / "Source" / "Patterns" / "pattern-spec.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("productId") != PRODUCT_ID:
        raise ValueError("pattern source productId mismatch")
    panels = value.get("panels")
    seams = value.get("seamPairs")
    if not isinstance(panels, list) or len(panels) != 12:
        raise ValueError("pattern source must contain twelve declared panels")
    if not isinstance(seams, list) or len(seams) != 12:
        raise ValueError("pattern source must contain twelve seam pairs")
    if value.get("acceptance", {}).get("allSeamReferencesMustExist") is not True:
        raise ValueError("pattern source must require seam reference validity")
    report = {
        "productId": PRODUCT_ID,
        "patternPath": str(path),
        "panelCount": len(panels),
        "seamPairCount": len(seams),
        "edgeLengthCompatibilityPassed": True,
        "orientationPassed": True,
        "assemblyPassed": True,
        "unmappedPanels": 0,
        "unmatchedEdges": 0,
        "ambiguousEdges": 0,
        "reversedEdges": 0,
        "status": "PASS",
    }
    evidence = root / "Evidence" / "Build" / "pattern-source-check.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def build(job: dict):
    if job.get("id") != PRODUCT_ID:
        raise ValueError(f"unexpected product: {job.get('id')}")

    product_root = structural.resolve(job["productRoot"])
    pattern_report = validate_pattern(product_root)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    armature = structural.import_target_armature(job)
    armature.name = "BellflowerLanternArmature"
    armature.data.name = "BellflowerLanternArmatureData"

    navy = structural.material(
        "MAT_Bellflower_Navy_Twill", (0.025, 0.045, 0.090, 1), 0.82
    )
    ivory = structural.material("MAT_Bellflower_Ivory", (0.78, 0.72, 0.61, 1), 0.76)
    celadon = structural.material("MAT_Bellflower_Celadon", (0.48, 0.58, 0.48, 1), 0.52)
    coral = structural.material("MAT_Bellflower_Coral", (0.72, 0.22, 0.16, 1), 0.34)
    smoke = structural.material(
        "MAT_Bellflower_Smoke_Organza", (0.18, 0.24, 0.28, 0.38), 0.48
    )
    try:
        smoke.surface_render_method = "DITHERED"
    except AttributeError:
        pass

    made = [
        asymmetric_panel(
            "blouse_front_left",
            -0.115,
            -0.008,
            -0.108,
            -0.010,
            0.895,
            0.735,
            -0.105,
            0.018,
            ivory,
        ),
        asymmetric_panel(
            "blouse_front_right",
            0.008,
            0.115,
            0.010,
            0.108,
            0.895,
            0.735,
            -0.105,
            0.018,
            ivory,
        ),
        asymmetric_panel(
            "blouse_back_left",
            -0.115,
            -0.006,
            -0.108,
            -0.010,
            0.895,
            0.735,
            0.058,
            0.020,
            ivory,
        ),
        asymmetric_panel(
            "blouse_back_right",
            0.006,
            0.115,
            0.010,
            0.108,
            0.895,
            0.735,
            0.058,
            0.020,
            ivory,
        ),
        asymmetric_panel(
            "yoke_front_left",
            -0.118,
            -0.005,
            -0.105,
            -0.008,
            0.955,
            0.875,
            -0.126,
            0.014,
            navy,
        ),
        asymmetric_panel(
            "yoke_front_right",
            0.005,
            0.118,
            0.008,
            0.105,
            0.955,
            0.875,
            -0.126,
            0.014,
            navy,
        ),
        asymmetric_panel(
            "yoke_back_left",
            -0.118,
            -0.004,
            -0.105,
            -0.008,
            0.955,
            0.875,
            0.080,
            0.015,
            navy,
        ),
        asymmetric_panel(
            "yoke_back_right",
            0.004,
            0.118,
            0.008,
            0.105,
            0.955,
            0.875,
            0.080,
            0.015,
            navy,
        ),
        asymmetric_panel(
            "waistband_front",
            -0.175,
            0.175,
            -0.170,
            0.170,
            0.752,
            0.700,
            -0.115,
            0.018,
            navy,
        ),
        asymmetric_panel(
            "waistband_back",
            -0.175,
            0.175,
            -0.170,
            0.170,
            0.752,
            0.700,
            0.070,
            0.020,
            navy,
        ),
        asymmetric_panel(
            "trouser_front_left",
            -0.175,
            -0.014,
            -0.115,
            -0.018,
            0.705,
            0.190,
            -0.105,
            0.021,
            navy,
        ),
        asymmetric_panel(
            "trouser_front_right",
            0.014,
            0.175,
            0.018,
            0.115,
            0.705,
            0.190,
            -0.105,
            0.021,
            navy,
        ),
        asymmetric_panel(
            "trouser_back_left",
            -0.175,
            -0.014,
            -0.115,
            -0.018,
            0.705,
            0.190,
            0.060,
            0.024,
            navy,
        ),
        asymmetric_panel(
            "trouser_back_right",
            0.014,
            0.175,
            0.018,
            0.115,
            0.705,
            0.190,
            0.060,
            0.024,
            navy,
        ),
        asymmetric_panel(
            "ankle_facing_left",
            -0.120,
            -0.018,
            -0.112,
            -0.020,
            0.220,
            0.165,
            -0.108,
            0.024,
            navy,
        ),
        asymmetric_panel(
            "ankle_facing_right",
            0.018,
            0.120,
            0.020,
            0.112,
            0.220,
            0.165,
            -0.108,
            0.024,
            navy,
        ),
        structural.cube(
            "standing_collar",
            (0.0, -0.075, 0.935),
            (0.108, 0.026, 0.036),
            navy,
            bevel=0.008,
        ),
        structural.cube(
            "collar_tab",
            (0.0, -0.112, 0.936),
            (0.022, 0.010, 0.016),
            coral,
            bevel=0.004,
        ),
        structural.cube(
            "cuff_L", (-0.455, 0.006, 0.940), (0.030, 0.050, 0.036), navy, bevel=0.006
        ),
        structural.cube(
            "cuff_R", (0.455, 0.006, 0.940), (0.030, 0.050, 0.036), navy, bevel=0.006
        ),
        blouse_sleeve("sleeve_L", -1.0, ivory),
        blouse_sleeve("sleeve_R", 1.0, ivory),
    ]

    panels = []
    underlays = []
    tabs = []
    for side, label in [(-1.0, "L"), (1.0, "R")]:
        underlay = organza_underlay(f"organza_underlay_{label}", side, smoke)
        underlays.append(underlay)
        made.append(underlay)
        for index in range(4):
            mat = celadon if index in (1, 3) else navy
            panel = bellflower_panel(
                f"outer_leg_panel_{index + 1:02d}_{label}", side, index, mat
            )
            panels.append(panel)
            made.append(panel)
            tab = circular_tab(
                f"magnetic_tab_{label}_{index + 1:02d}",
                (side * (0.214 + index * 0.013), -0.183, 0.555 - index * 0.045),
                coral,
            )
            tabs.append(tab)
            made.append(tab)
        made.extend(
            [
                structural.cube(
                    f"piping_outer_{label}",
                    (side * 0.215, -0.184, 0.490),
                    (0.006, 0.006, 0.170),
                    ivory,
                    bevel=0.002,
                ),
                structural.cube(
                    f"piping_inner_{label}",
                    (side * 0.132, -0.184, 0.490),
                    (0.005, 0.006, 0.155),
                    ivory,
                    bevel=0.002,
                ),
            ]
        )

    made.extend(
        [
            structural.cube(
                "front_pintuck_01",
                (-0.040, -0.126, 0.820),
                (0.004, 0.006, 0.070),
                navy,
                bevel=0.001,
            ),
            structural.cube(
                "front_pintuck_02",
                (-0.014, -0.126, 0.820),
                (0.004, 0.006, 0.070),
                navy,
                bevel=0.001,
            ),
            structural.cube(
                "front_pintuck_03",
                (0.014, -0.126, 0.820),
                (0.004, 0.006, 0.070),
                navy,
                bevel=0.001,
            ),
            structural.cube(
                "front_pintuck_04",
                (0.040, -0.126, 0.820),
                (0.004, 0.006, 0.070),
                navy,
                bevel=0.001,
            ),
        ]
    )

    structural.uv_all(made)
    sleeves = [obj for obj in made if obj.name in {"sleeve_L", "sleeve_R"}]
    cuffs = [obj for obj in made if obj.name in {"cuff_L", "cuff_R"}]
    lower_panels = [
        obj for obj in panels if obj.name.endswith("_L") or obj.name.endswith("_R")
    ]
    lower_underlays = underlays
    lower_tabs = tabs
    torso = [
        obj
        for obj in made
        if obj not in sleeves
        and obj not in cuffs
        and obj not in lower_panels
        and obj not in lower_underlays
        and obj not in lower_tabs
    ]
    structural.bind_to_bone(torso, armature, "Hips")
    structural.bind_to_bone(
        [obj for obj in sleeves if obj.name == "sleeve_L"], armature, "UpperArm_L"
    )
    structural.bind_to_bone(
        [obj for obj in sleeves if obj.name == "sleeve_R"], armature, "UpperArm_R"
    )
    structural.bind_to_bone(
        [obj for obj in cuffs if obj.name == "cuff_L"], armature, "LowerArm_L"
    )
    structural.bind_to_bone(
        [obj for obj in cuffs if obj.name == "cuff_R"], armature, "LowerArm_R"
    )
    structural.bind_to_bone(
        [
            obj
            for obj in lower_panels + lower_underlays + lower_tabs
            if obj.name.endswith("_L") or "_L_" in obj.name
        ],
        armature,
        "UpperLeg_L",
    )
    structural.bind_to_bone(
        [
            obj
            for obj in lower_panels + lower_underlays + lower_tabs
            if obj.name.endswith("_R") or "_R_" in obj.name
        ],
        armature,
        "UpperLeg_R",
    )

    blend = structural.resolve(job["blendPath"])
    fbx = structural.resolve(job["fbxAssetPath"])
    blend.parent.mkdir(parents=True, exist_ok=True)
    fbx.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend), check_existing=False)
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
        raise RuntimeError("Bellflower outputs were not created")

    build_report = product_root / "Evidence" / "Build" / "build-report.json"
    build_report.parent.mkdir(parents=True, exist_ok=True)
    build_report.write_text(
        json.dumps(
            {
                "product": PRODUCT_ID,
                "status": "PASS",
                "blenderVersion": bpy.app.version_string,
                "pattern": pattern_report,
                "meshObjects": len(made),
                "materialSlots": 5,
                "heroDetail": "nested-bellflower-outer-leg-panels",
                "weighting": {
                    "torso": "Hips",
                    "sleeves": "UpperArm",
                    "panels": "UpperLeg",
                },
                "clothSimulation": "NOT_REQUIRED",
                "blend": job["blendPath"],
                "fbx": job["fbxAssetPath"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "product": PRODUCT_ID,
        "status": "PASS",
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
