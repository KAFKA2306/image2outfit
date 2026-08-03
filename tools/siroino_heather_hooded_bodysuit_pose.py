#!/usr/bin/env python3
"""Render required and diagnostic SiroinoSotai_PC fit poses for the heather suit."""
from __future__ import annotations

import json
import math
from pathlib import Path

import bpy

import siroino_heather_hooded_bodysuit_pose_legacy as legacy
import siroino_required_pose_render as generic
import siroino_strappy_knit_build as common

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_POSES = ("neutral", "arms-up", "arm-cross", "crouch", "sit", "prone")
DIAGNOSTIC_POSES = ("forward-bend", "legs-apart", "walk")
POSES = (*REQUIRED_POSES, *DIAGNOSTIC_POSES)


def apply_pose(armature: bpy.types.Object, base_transform, name: str) -> None:
    """Apply the central release poses plus product-specific diagnostic poses."""
    legacy.clear(armature, base_transform)
    if name == "arms-up":
        legacy.rotate(armature, "UpperArm_L", (-105.0, 0.0, -8.0))
        legacy.rotate(armature, "UpperArm_R", (-105.0, 0.0, 8.0))
        legacy.rotate(armature, "LowerArm_L", (-8.0, 0.0, 0.0))
        legacy.rotate(armature, "LowerArm_R", (-8.0, 0.0, 0.0))
    elif name == "arm-cross":
        legacy.rotate(armature, "UpperArm_L", (-38.0, 18.0, -54.0))
        legacy.rotate(armature, "UpperArm_R", (-38.0, -18.0, 54.0))
        legacy.rotate(armature, "LowerArm_L", (-86.0, 0.0, 20.0))
        legacy.rotate(armature, "LowerArm_R", (-86.0, 0.0, -20.0))
    elif name == "crouch":
        legacy.rotate(armature, "UpperLeg_L", (48.0, 0.0, 6.0))
        legacy.rotate(armature, "UpperLeg_R", (48.0, 0.0, -6.0))
        legacy.rotate(armature, "LowerLeg_L", (-72.0, 0.0, 0.0))
        legacy.rotate(armature, "LowerLeg_R", (-72.0, 0.0, 0.0))
        hips = armature.pose.bones.get("Hips")
        if hips is not None:
            hips.location.z = -0.10
    elif name == "sit":
        legacy.rotate(armature, "UpperLeg_L", (65.0, 0.0, 2.0))
        legacy.rotate(armature, "UpperLeg_R", (65.0, 0.0, -2.0))
        legacy.rotate(armature, "LowerLeg_L", (-65.0, 0.0, 0.0))
        legacy.rotate(armature, "LowerLeg_R", (-65.0, 0.0, 0.0))
        hips = armature.pose.bones.get("Hips")
        if hips is not None:
            hips.location.z = -0.16
    elif name == "prone":
        armature.rotation_euler.rotate_axis("X", math.radians(90.0))
        armature.location.y += 0.10
        armature.location.z += 0.16
        legacy.rotate(armature, "UpperLeg_L", (-10.0, 0.0, 3.0))
        legacy.rotate(armature, "UpperLeg_R", (-10.0, 0.0, -3.0))
        legacy.rotate(armature, "LowerLeg_L", (20.0, 0.0, 0.0))
        legacy.rotate(armature, "LowerLeg_R", (20.0, 0.0, 0.0))
        legacy.rotate(armature, "UpperArm_L", (-34.0, 0.0, -18.0))
        legacy.rotate(armature, "UpperArm_R", (-34.0, 0.0, 18.0))
        legacy.rotate(armature, "LowerArm_L", (-48.0, 0.0, 0.0))
        legacy.rotate(armature, "LowerArm_R", (-48.0, 0.0, 0.0))
    elif name in DIAGNOSTIC_POSES:
        legacy.apply_pose(armature, base_transform, name)
        return
    bpy.context.view_layer.update()


def zone_for_object(name: str) -> list[str]:
    if "Front_Body" in name:
        return ["chest", "underarm", "abdomen", "hip-crest", "groin", "leg-root"]
    if "Back_Body" in name:
        return ["shoulder", "underarm", "back", "hip-crest", "buttocks", "groin"]
    return legacy.zone_for_object(name)


def main() -> int:
    options = legacy.args()
    job = json.loads(Path(options.job).read_text(encoding="utf-8-sig"))
    root = ROOT / job["productRoot"]
    pose_dir = root / "Previews" / "Poses"
    pose_dir.mkdir(parents=True, exist_ok=True)

    body = next(
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.name.startswith("SiroinoSotai_PC")
    )
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    garments = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH"
        and obj != body
        and any(
            modifier.type == "ARMATURE" and modifier.object == armature
            for modifier in obj.modifiers
        )
    ]
    if not garments:
        raise RuntimeError("No Siroino-bound garment meshes found for pose audit")

    body.hide_render = False
    common.set_skin_material(body)
    base_transform = (
        armature.location.copy(),
        armature.rotation_euler.copy(),
        armature.scale.copy(),
    )
    legacy.zone_for_object = zone_for_object

    _, camera = common.studio_setup()
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 28
    scene.cycles.use_denoising = True
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = 0.045
    scene.render.resolution_x = 1200
    scene.render.resolution_y = 1200
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.look = "AgX - Medium High Contrast"

    camera_settings = {
        "neutral": ((1.62, -1.90, 0.64), (0.0, 0.0, 0.40), 1.23),
        "arms-up": ((1.62, -1.90, 0.68), (0.0, 0.0, 0.44), 1.30),
        "arm-cross": ((1.62, -1.90, 0.64), (0.0, 0.0, 0.40), 1.23),
        "crouch": ((1.72, -2.05, 0.46), (0.0, 0.0, 0.31), 1.28),
        "sit": ((1.72, -2.05, 0.46), (0.0, 0.0, 0.30), 1.23),
        "prone": ((1.90, -0.46, 0.70), (0.0, -0.44, 0.17), 1.32),
        "forward-bend": ((1.65, -1.96, 0.62), (0.0, 0.0, 0.39), 1.30),
        "legs-apart": ((1.68, -1.98, 0.55), (0.0, 0.0, 0.34), 1.34),
        "walk": ((1.66, -1.98, 0.57), (0.0, 0.0, 0.35), 1.31),
    }

    paths: dict[str, Path] = {}
    pose_audits: dict[str, dict] = {}
    for name in POSES:
        apply_pose(armature, base_transform, name)
        pose_audits[name] = legacy.audit_intersections(body, garments)
        path = pose_dir / f"{name}.png"
        location, target, ortho_scale = camera_settings[name]
        camera.data.ortho_scale = ortho_scale
        common.point_camera(camera, location, target)
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        paths[name] = path

    apply_pose(armature, base_transform, "neutral")
    required_paths = {name: paths[name] for name in REQUIRED_POSES}
    sheet = root / "Previews" / f"{job['id']}-pose-review.webp"
    generic.sheet(required_paths, sheet)
    fit_audit = {
        "schemaVersion": 1,
        "checkedAt": common.utc_now(),
        "target": "SiroinoSotai_PC",
        "method": "Blender evaluated-mesh BVH narrow-phase triangle overlap",
        "requiredPoses": list(REQUIRED_POSES),
        "diagnosticPoses": list(DIAGNOSTIC_POSES),
        "requiredZones": [
            "chest",
            "underarm",
            "shoulder",
            "elbow",
            "wrist",
            "abdomen",
            "hip-crest",
            "buttocks",
            "groin",
            "inner-thigh",
            "leg-root",
            "hood",
            "drawcord",
            "side-tie",
        ],
        "poses": pose_audits,
        "pass": all(pose_audits[name]["pass"] for name in REQUIRED_POSES),
        "failureCondition": "Any evaluated garment/body triangle intersection in a required pose produces FAIL and requires visual diagnosis.",
    }
    audit_path = root / "Tests" / "fit-audit.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        json.dumps(fit_audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    legacy.update_manifest(job, paths, sheet, fit_audit)
    print(
        json.dumps(
            {
                "passed": all(path.is_file() for path in paths.values()),
                "targetSource": job["targetSourcePath"],
                "targetBody": body.name,
                "garmentObjectCount": len(garments),
                "requiredPoses": {name: str(paths[name]) for name in REQUIRED_POSES},
                "diagnosticPoses": {
                    name: str(paths[name]) for name in DIAGNOSTIC_POSES
                },
                "sheet": str(sheet),
                "fitAudit": str(audit_path),
                "fitAuditPass": fit_audit["pass"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
