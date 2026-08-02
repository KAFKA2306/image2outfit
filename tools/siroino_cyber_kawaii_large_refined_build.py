#!/usr/bin/env python3
"""Refine the Cyber Kawaii Large garment proportions and handoff metadata.

This module reuses the established material/export pipeline while replacing the
first-pass oversized sleeve and rigid skirt geometry.  It keeps the official
Siroino PC source and applies the declared ``_Large`` shape keys before fit.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

import siroino_cyber_kawaii_large_build as legacy
import siroino_strappy_knit_build as base

ROOT = Path(__file__).resolve().parents[1]


def bone_segment(armature: bpy.types.Object, bone_name: str) -> tuple[Vector, Vector]:
    bone = armature.data.bones.get(bone_name)
    if bone is None:
        raise RuntimeError(f"Required Siroino bone missing: {bone_name}")
    return (
        armature.matrix_world @ bone.head_local,
        armature.matrix_world @ bone.tail_local,
    )


def near_segment(point: Vector, start: Vector, end: Vector, *, t0: float, t1: float, radius: float) -> bool:
    direction = end - start
    length_squared = direction.length_squared
    if length_squared <= 1e-12:
        return False
    t = (point - start).dot(direction) / length_squared
    if not t0 <= t <= t1:
        return False
    closest = start + direction * t
    return (point - closest).length <= radius


def create_outfit(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    materials: dict[str, bpy.types.Material],
) -> list[bpy.types.Object]:
    white = materials["white"]
    plaid = materials["plaid"]
    pink = materials["pink"]
    black = materials["black"]
    silver = materials["silver"]
    garments: list[bpy.types.Object] = []

    garments.append(
        base.extract_surface(
            body,
            armature,
            "White_Cropped_Blouse_Front",
            lambda c: 0.835 <= c.z <= 1.018 and c.y < 0.005 and abs(c.x) <= 0.145,
            white,
            0.0062,
        )
    )
    garments.append(
        base.extract_surface(
            body,
            armature,
            "White_Cropped_Blouse_Back",
            lambda c: 0.842 <= c.z <= 0.985 and c.y >= -0.006 and abs(c.x) <= 0.143,
            white,
            0.0060,
        )
    )
    garments.append(
        base.extract_surface(
            body,
            armature,
            "White_Waist_Base",
            lambda c: 0.705 <= c.z <= 0.792 and abs(c.x) <= 0.155,
            white,
            0.0052,
        )
    )

    outer_skirt = legacy.ring_skirt(
        "Black_Pink_Plaid_Pleated_Skirt",
        body,
        armature,
        plaid,
        top_z=0.786,
        bottom_z=0.625,
        top_rx=0.148,
        top_ry=0.106,
        bottom_rx=0.205,
        bottom_ry=0.148,
        pleats=16,
    )
    underskirt = legacy.ring_skirt(
        "White_Ruffle_Underskirt",
        body,
        armature,
        white,
        top_z=0.648,
        bottom_z=0.585,
        top_rx=0.187,
        top_ry=0.134,
        bottom_rx=0.216,
        bottom_ry=0.156,
        pleats=20,
        scallop=0.008,
    )
    garments.extend((outer_skirt, underskirt))

    garments.append(
        base.extract_surface(
            body,
            armature,
            "White_Thigh_High_Stockings",
            lambda c: 0.045 <= c.z <= 0.492 and abs(c.x) >= 0.016,
            white,
            0.0045,
        )
    )

    for side_name in ("L", "R"):
        upper_start, upper_end = bone_segment(armature, f"UpperArm_{side_name}")
        shoulder = upper_start.lerp(upper_end, 0.18)
        puff = legacy.ellipsoid(
            f"White_Puff_Sleeve_{side_name}",
            tuple(shoulder),
            (0.050, 0.046, 0.058),
            white,
            body,
            armature,
        )
        garments.append(puff)

        lower_start, lower_end = bone_segment(armature, f"LowerArm_{side_name}")
        garments.append(
            base.extract_surface(
                body,
                armature,
                f"White_Detached_Sleeve_{side_name}",
                lambda c, a=lower_start, b=lower_end: near_segment(
                    c, a, b, t0=0.10, t1=0.84, radius=0.052
                ),
                white,
                0.0050,
            )
        )

        x = -0.067 if side_name == "L" else 0.067
        thigh_loop = base.surface_cross_section_loop(
            body, 0.497, x - 0.043, x + 0.043, 0.005, 32
        )
        garments.append(
            base.curve_tube(
                f"Black_Thigh_Band_{side_name}",
                thigh_loop,
                0.0022,
                black,
                armature,
                f"UpperLeg_{side_name}",
                cyclic=True,
            )
        )
        pink_loop = [(px, py - 0.001, pz - 0.010) for px, py, pz in thigh_loop]
        garments.append(
            base.curve_tube(
                f"Pink_Thigh_Trim_{side_name}",
                pink_loop,
                0.0012,
                pink,
                armature,
                f"UpperLeg_{side_name}",
                cyclic=True,
            )
        )

    neck_loop = base.surface_cross_section_loop(body, 1.022, -0.050, 0.050, 0.004, 40)
    garments.append(
        base.curve_tube(
            "Black_Neck_Choker", neck_loop, 0.0020, black, armature, "Chest", cyclic=True
        )
    )
    neck_y = base.body_front_y(body, 0.0, 0.982) - 0.010
    garments.extend(
        legacy.bow("Pink_Collar_Bow", (0.0, neck_y, 0.982), 0.018, pink, body, armature)
    )

    waist_loop = base.surface_cross_section_loop(body, 0.773, -0.155, 0.155, 0.006, 56)
    garments.append(
        base.curve_tube(
            "Black_Waist_Harness", waist_loop, 0.0024, black, armature, "Hips", cyclic=True
        )
    )
    pink_waist_loop = [(x, y - 0.001, z - 0.014) for x, y, z in waist_loop]
    garments.append(
        base.curve_tube(
            "Pink_Waist_Accent",
            pink_waist_loop,
            0.0012,
            pink,
            armature,
            "Hips",
            cyclic=True,
        )
    )

    for side, x in (("L", -0.145), ("R", 0.145)):
        garments.extend(
            legacy.bow(
                f"Pink_Skirt_Bow_{side}",
                (x, -0.142, 0.665),
                0.016,
                pink,
                body,
                armature,
            )
        )
        garments.append(
            base.heart_curve(
                f"Silver_Heart_{side}",
                (x, -0.153, 0.705),
                0.00044,
                silver,
                armature,
                "Hips",
            )
        )

    hem_loop = base.ellipse_points((0.0, 0.0, 0.590), (0.216, 0.156), 96)
    garments.append(
        base.curve_tube(
            "Pink_Underskirt_Hem", hem_loop, 0.0016, pink, armature, "Hips", cyclic=True
        )
    )

    for obj in garments:
        if obj.type == "MESH" and obj.parent is None:
            legacy.finish_mesh(obj, body, armature)
    return garments


def rewrite_handoff(job: dict, return_code: int) -> None:
    product_root = legacy.repo_path(job["productRoot"])
    artifact_dir = legacy.repo_path(job["artifactDir"])
    report_path = artifact_dir / "product-build-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    passed = bool(report.get("passed")) and return_code == 0
    report["visualRevision"] = "v2-proportional-sleeves-soft-skirt"
    report["notes"] = [
        "The tracked official SiroinoSotai PC FBX is the target source.",
        "The declared All_L, Chest_L, Hips_01_L, UpperLeg_L, and Breasts_L shape keys are verified and applied before garment extraction.",
        "The output delivery contains only original garment assets; the shared CC0 avatar reference is outside the product payload.",
        "Five-view and pose images are actual Blender renders of this generated scene.",
    ]
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest = {
        "schemaVersion": 1,
        "productId": job["id"],
        "productName": job["productName"],
        "status": "WORKING" if passed else "REJECTED",
        "targetAdapterId": job["adapterId"],
        "productRoot": job["productRoot"],
        "outfitPrefabPath": job["prefabAssetPath"],
        "integratedPrefabPath": job["integratedPrefabAssetPath"],
        "previewPath": job["previewPaths"]["front"],
        "documentationPath": f"{job['productRoot']}/README.md",
        "sourceJobPath": f"config/products/{job['id']}/job.json",
        "productBuildScript": job["productBuildScript"],
        "designRevision": "v2-proportional-sleeves-soft-skirt",
        "handoff": {
            "resumable": True,
            "canonicalWorkspace": job["productRoot"],
            "doNotRebuildFromZero": True,
            "resumeFrom": job["productBuildScript"],
            "lastAttempt": {
                "result": "HOSTED_MODELED" if passed else "REJECTED",
                "visualRevision": "v2-proportional-sleeves-soft-skirt",
            },
            "blockers": [
                "Import and save both Prefabs in pinned Unity",
                "Pass Prefab reload and Modular Avatar/NDMF checks",
                "Complete human multiview, pose-penetration, and VRChat runtime reviews",
            ],
        },
        "technicalGates": {
            "targetLargeResolved": "PASS",
            "blender": "PASS" if passed else "FAIL",
            "fbx": "PASS" if passed else "FAIL",
            "bodyClearance": "PASS" if passed else "FAIL",
            "fiveViewRender": "PASS" if passed else "FAIL",
            "poseRender": "PASS" if passed else "FAIL",
            "unityImport": "PENDING",
            "prefabSerialized": "PENDING",
            "prefabReload": "PENDING",
            "modularAvatar": "PENDING",
            "vrchatBuildAndTest": "PENDING",
            "humanVisualReview": "PENDING",
            "humanPoseReview": "PENDING",
            "humanRuntimeReview": "PENDING",
        },
        "outputs": {
            "blend": job["blendPath"],
            "fbx": job["fbxAssetPath"],
            "prefab": job["prefabAssetPath"],
            "integratedPrefab": job["integratedPrefabAssetPath"],
            "multiview": f"{job['productRoot']}/Previews/{job['id']}-multiview.webp",
            "poseReview": f"{job['productRoot']}/Previews/{job['id']}-pose-review.webp",
        },
    }
    legacy.repo_path(job["productManifestPath"]).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    (product_root / "README.md").write_text(
        f"""# {job['productName']}

Target: **Siroino `_Large`**. The tracked official `SiroinoSotai_PC.fbx` is fitted by applying the declared official Large shape keys before garment extraction.

## Visual revision v2

- proportionally reduced shoulder puffs
- body-fitted detached forearm sleeves instead of oversized ellipsoids
- softer, narrower pleated mini-skirt silhouette
- fitted waist/choker bands instead of floating wire harnesses
- white thigh-high legwear, pink bows, and silver heart accents

## Outputs

- Blender source: `{job['blendPath']}`
- FBX: `{job['fbxAssetPath']}`
- outfit Prefab: `{job['prefabAssetPath']}`
- integrated Prefab target: `{job['integratedPrefabAssetPath']}`
- five-view render: `{manifest['outputs']['multiview']}`
- pose review: `{manifest['outputs']['poseReview']}`

The shared CC0 avatar reference is build input and is not part of the outfit delivery payload. Unity import, Prefab reload, Modular Avatar/NDMF, and runtime review remain explicit gates.
""",
        encoding="utf-8",
    )


def main() -> int:
    _, job = base.load_job()
    legacy.create_outfit = create_outfit
    return_code = legacy.main()
    rewrite_handoff(job, return_code)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
