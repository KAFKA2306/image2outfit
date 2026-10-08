#!/usr/bin/env python3
"""Build a continuous, deformation-safe Siroino lace-halter outfit.

The previous continuous pass stacked multiple full-circumference body copies and
made the edges read as rigid bands. This revision keeps one fitted base, restores
selective front/strap/lace panels, gives the long front panel a small garment-native
drape, and uses alpha only for the intended sheer/lace materials.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import bpy
from mathutils import Vector

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_lace_halter_large_refine_and_review as base
import siroino_lace_halter_large_pose_review as review
import siroino_required_pose_render as pose_base

BODY_NAME = review.BODY_NAME
ARMATURE_NAME = review.ARMATURE_NAME
REVISION = "v1-large-lace-pass-9-selective-matte-drape"
Predicate = Callable[[Vector], bool]


def add_surface_finish(
    obj: bpy.types.Object,
    *,
    thickness: float = 0.0008,
) -> None:
    subdivision = obj.modifiers.new("Garment Surface", "SUBSURF")
    subdivision.subdivision_type = "CATMULL_CLARK"
    subdivision.levels = 1
    subdivision.render_levels = 1
    subdivision.show_only_control_edges = True

    solidify = obj.modifiers.new("Garment Thickness", "SOLIDIFY")
    solidify.thickness = thickness
    solidify.offset = 0.35
    solidify.use_rim = True


def drape_front_panel(
    obj: bpy.types.Object,
    *,
    low_z: float,
    high_z: float,
    center_x: float,
    half_width: float,
) -> None:
    span = max(high_z - low_z, 1e-6)
    for vertex in obj.data.vertices:
        world = base.world_point(obj, vertex.co)
        t = max(0.0, min(1.0, (high_z - world.z) / span))
        center_strength = max(
            0.0,
            1.0 - abs(world.x - center_x) / max(half_width, 1e-6),
        )
        vertex.co.y -= 0.008 * (t**1.4) * (0.35 + 0.65 * center_strength)
        vertex.co.x += (world.x - center_x) * 0.025 * (t**1.2)
    obj.data.update(calc_edges=True)
    obj["garmentNativeDrape"] = True


def fitted(
    body: bpy.types.Object,
    armature: bpy.types.Object,
    name: str,
    predicate: Predicate,
    material: bpy.types.Material,
    *,
    offset: float,
) -> bpy.types.Object:
    obj = base.fitted_copy(
        body,
        armature,
        name,
        predicate,
        material,
        offset=offset,
    )
    add_surface_finish(obj)
    return obj


def update_refinement_evidence(job: dict, garments: list[bpy.types.Object]) -> None:
    product_root = ROOT / job["productRoot"]
    artifact_dir = ROOT / job["artifactDir"]
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    metrics = base.mesh_metrics(garments)
    evidence = {
        "schemaVersion": 1,
        "productId": job["id"],
        "designRevision": REVISION,
        "status": "WORKING",
        "generatedAt": generated_at,
        "sourceBody": BODY_NAME,
        "strategy": "single fitted base plus selective halter/lace panels with garment-native front drape",
        "rejectedPriorPass": {
            "revision": "v1-large-lace-pass-7-body-fitted-ci",
            "reasons": [
                "triangular and block-like cut boundaries",
                "excessive silver reflections",
                "insufficient back coverage",
                "fragmented decorative patches",
            ],
        },
        "changes": [
            "Kept one continuous upper-chest-to-mid-thigh fitted base instead of stacking full-body copies.",
            "Restricted halter wings, high-cut front, straps, long panel and applique to their intended regions.",
            "Set non-metal cloth metallic response to zero and raised roughness to suppress plastic highlights.",
            "Applied alpha only to the intended sheer/lace materials.",
            "Reduced shell thickness and used a small garment-native drape on the long front panel.",
            "Retained exact baked-body armature weights for every delivery mesh.",
        ],
        "metrics": metrics,
        "humanDecision": "PENDING",
    }
    evidence_path = product_root / "Evidence" / "improvement-loop.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "refinement-report.json").write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    options = pose_base.args()
    job_path = Path(options.job).resolve()
    job = json.loads(job_path.read_text(encoding="utf-8-sig"))

    body = bpy.data.objects.get(BODY_NAME)
    armature = bpy.data.objects.get(ARMATURE_NAME)
    if body is None or body.type != "MESH":
        raise RuntimeError(f"baked validation body not found: {BODY_NAME}")
    if armature is None or armature.type != "ARMATURE":
        raise RuntimeError(f"product armature not found: {ARMATURE_NAME}")

    minimum, maximum = base.bounds_world(body)
    center = (minimum + maximum) * 0.5
    height = maximum.z - minimum.z

    hips = base.bone_world(armature, "Hips") or Vector(
        (center.x, center.y, minimum.z + 0.55 * height)
    )
    chest = base.bone_world(armature, "Chest") or Vector(
        (center.x, center.y, minimum.z + 0.73 * height)
    )
    upper_chest = base.bone_world(armature, "UpperChest") or Vector(
        (center.x, center.y, minimum.z + 0.79 * height)
    )
    neck = base.bone_world(armature, "Neck") or Vector(
        (center.x, center.y, minimum.z + 0.86 * height)
    )
    left_upper_arm = base.bone_world(armature, "UpperArm_L")
    right_upper_arm = base.bone_world(armature, "UpperArm_R")
    left_knee = base.bone_world(armature, "LowerLeg_L")
    right_knee = base.bone_world(armature, "LowerLeg_R")

    shoulder_span = (
        abs(left_upper_arm.x - right_upper_arm.x)
        if left_upper_arm is not None and right_upper_arm is not None
        else (maximum.x - minimum.x) * 0.34
    )
    knee_z = (
        (left_knee.z + right_knee.z) * 0.5
        if left_knee is not None and right_knee is not None
        else minimum.z + 0.30 * height
    )

    body_points = [base.world_point(body, vertex.co) for vertex in body.data.vertices]
    hip_band = [
        point
        for point in body_points
        if hips.z - 0.12 * height <= point.z <= hips.z + 0.12 * height
    ]
    if not hip_band:
        raise RuntimeError("could not resolve the fitted hip silhouette")
    hip_radius = max(abs(point.x - center.x) for point in hip_band)
    torso_radius = shoulder_span * 0.47

    dress_bottom = knee_z + 0.055 * height
    dress_top = upper_chest.z + 0.035 * height
    waist_z = hips.z + 0.095 * height

    def width_at(z: float) -> float:
        if z <= hips.z + 0.02 * height:
            return hip_radius * 1.035
        if z >= chest.z:
            return torso_radius
        fraction = (z - (hips.z + 0.02 * height)) / max(
            chest.z - (hips.z + 0.02 * height),
            1e-6,
        )
        return (hip_radius * 1.035) * (1.0 - fraction) + torso_radius * fraction

    def continuous(point: Vector, low: float, high: float, scale: float = 1.0) -> bool:
        return (
            low <= point.z <= high
            and abs(point.x - center.x) <= width_at(point.z) * scale
        )

    base.delete_rejected_garments()

    matte = base.make_material(
        "LaceHalter_ContinuousMatte",
        (0.012, 0.020, 0.046, 1.0),
        roughness=0.72,
        metallic=0.00,
    )
    satin = base.make_material(
        "LaceHalter_ContinuousSatin",
        (0.028, 0.052, 0.095, 1.0),
        roughness=0.56,
        metallic=0.00,
    )
    lace = base.make_material(
        "LaceHalter_ContinuousLace",
        (0.060, 0.082, 0.130, 0.68),
        roughness=0.70,
        metallic=0.00,
        alpha=0.68,
    )
    sheer = base.make_material(
        "LaceHalter_ContinuousSheer",
        (0.028, 0.045, 0.078, 0.56),
        roughness=0.74,
        metallic=0.00,
        alpha=0.56,
    )
    trim = base.make_material(
        "LaceHalter_ContinuousTrim",
        (0.105, 0.125, 0.165, 1.0),
        roughness=0.62,
        metallic=0.00,
    )

    front_limit = center.y - 0.015 * max(maximum.y - minimum.y, 1e-6)
    specs: list[tuple[str, Predicate, bpy.types.Material, float]] = [
        (
            "Sheer_Fitted_Torso",
            lambda point: continuous(point, dress_bottom, dress_top),
            matte,
            0.0045,
        ),
        (
            "Glossy_Keyhole_Halter_Wings",
            lambda point: (
                chest.z - 0.035 * height <= point.z <= dress_top
                and point.y <= front_limit
                and shoulder_span * 0.08
                <= abs(point.x - center.x)
                <= shoulder_span * 0.39
            ),
            satin,
            0.0060,
        ),
        (
            "Glossy_Highcut_Front",
            lambda point: (
                hips.z - 0.115 * height <= point.z <= hips.z + 0.050 * height
                and point.y <= center.y
                and abs(point.x - center.x) <= hip_radius * 0.92
            ),
            satin,
            0.0065,
        ),
        (
            "Glossy_High_Collar",
            lambda point: (
                neck.z - 0.030 * height <= point.z <= neck.z + 0.012 * height
                and abs(point.x - center.x) <= shoulder_span * 0.22
            ),
            trim,
            0.0055,
        ),
        (
            "Long_Sheer_Front_Panel",
            lambda point: (
                dress_bottom <= point.z <= hips.z - 0.055 * height
                and point.y <= front_limit
                and abs(point.x - center.x) <= hip_radius * 0.78
            ),
            sheer,
            0.0065,
        ),
        (
            "Lace_And_Halter_Straps",
            lambda point: (
                upper_chest.z - 0.020 * height <= point.z <= dress_top
                and point.y <= front_limit
                and shoulder_span * 0.22
                <= abs(point.x - center.x)
                <= shoulder_span * 0.35
            ),
            lace,
            0.0070,
        ),
        (
            "Dark_Eyelets",
            lambda point: (
                waist_z - 0.012 * height <= point.z <= waist_z + 0.012 * height
                and point.y <= front_limit
                and abs(point.x - center.x) <= hip_radius * 0.80
            ),
            trim,
            0.0070,
        ),
        (
            "Lace_Applique",
            lambda point: (
                dress_bottom <= point.z <= dress_bottom + 0.055 * height
                and point.y <= front_limit
                and hip_radius * 0.30 <= abs(point.x - center.x) <= hip_radius * 0.82
            ),
            lace,
            0.0075,
        ),
    ]

    garments = [
        fitted(body, armature, name, predicate, material, offset=offset)
        for name, predicate, material, offset in specs
    ]
    long_panel = next(obj for obj in garments if obj.name == "Long_Sheer_Front_Panel")
    drape_front_panel(
        long_panel,
        low_z=dress_bottom,
        high_z=hips.z - 0.055 * height,
        center_x=center.x,
        half_width=hip_radius * 0.78,
    )

    base.REVISION = REVISION
    base.update_evidence(job, garments)
    update_refinement_evidence(job, garments)
    base.save_and_export(job, armature, garments)
    result = review.main()
    bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / job["blendPath"]))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
