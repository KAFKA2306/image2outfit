#!/usr/bin/env python3
"""Render and audit the required SiroinoSotai_PC fit-pose suite."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Euler, Vector
from mathutils.bvhtree import BVHTree

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_required_pose_render as generic
import siroino_strappy_knit_build as common

ROOT = Path(__file__).resolve().parents[1]
POSES = ("neutral", "arms-up", "forward-bend", "legs-apart", "walk", "crouch")


def args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    return parser.parse_args(raw)


def rotate(
    armature: bpy.types.Object,
    name: str,
    degrees: tuple[float, float, float],
) -> None:
    bone = armature.pose.bones.get(name)
    if bone is None:
        raise RuntimeError(f"Required Siroino pose bone missing: {name}")
    bone.rotation_mode = "XYZ"
    bone.rotation_euler = tuple(math.radians(value) for value in degrees)


def clear(
    armature: bpy.types.Object,
    base_transform: tuple[Vector, Euler, Vector],
) -> None:
    location, rotation, scale = base_transform
    armature.location = location.copy()
    armature.rotation_mode = "XYZ"
    armature.rotation_euler = rotation.copy()
    armature.scale = scale.copy()
    for bone in armature.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0.0, 0.0, 0.0)
        bone.location = (0.0, 0.0, 0.0)
        bone.scale = (1.0, 1.0, 1.0)


def apply_pose(
    armature: bpy.types.Object,
    base_transform: tuple[Vector, Euler, Vector],
    name: str,
) -> None:
    clear(armature, base_transform)
    if name == "arms-up":
        rotate(armature, "UpperArm_L", (-112.0, 0.0, -8.0))
        rotate(armature, "UpperArm_R", (-112.0, 0.0, 8.0))
        rotate(armature, "LowerArm_L", (-7.0, 0.0, 0.0))
        rotate(armature, "LowerArm_R", (-7.0, 0.0, 0.0))
    elif name == "forward-bend":
        rotate(armature, "Spine", (28.0, 0.0, 0.0))
        rotate(armature, "Chest", (24.0, 0.0, 0.0))
        rotate(armature, "UpperLeg_L", (-8.0, 0.0, 0.0))
        rotate(armature, "UpperLeg_R", (-8.0, 0.0, 0.0))
        rotate(armature, "UpperArm_L", (-18.0, 0.0, -10.0))
        rotate(armature, "UpperArm_R", (-18.0, 0.0, 10.0))
    elif name == "legs-apart":
        rotate(armature, "UpperLeg_L", (0.0, 0.0, 25.0))
        rotate(armature, "UpperLeg_R", (0.0, 0.0, -25.0))
        rotate(armature, "LowerLeg_L", (-8.0, 0.0, 0.0))
        rotate(armature, "LowerLeg_R", (-8.0, 0.0, 0.0))
        rotate(armature, "UpperArm_L", (-18.0, 0.0, -14.0))
        rotate(armature, "UpperArm_R", (-18.0, 0.0, 14.0))
    elif name == "walk":
        rotate(armature, "UpperLeg_L", (30.0, 0.0, 1.0))
        rotate(armature, "LowerLeg_L", (-42.0, 0.0, 0.0))
        rotate(armature, "UpperLeg_R", (-24.0, 0.0, -1.0))
        rotate(armature, "LowerLeg_R", (12.0, 0.0, 0.0))
        rotate(armature, "UpperArm_L", (-30.0, 0.0, -5.0))
        rotate(armature, "UpperArm_R", (25.0, 0.0, 5.0))
        rotate(armature, "LowerArm_L", (-18.0, 0.0, 0.0))
        rotate(armature, "LowerArm_R", (-28.0, 0.0, 0.0))
    elif name == "crouch":
        rotate(armature, "UpperLeg_L", (48.0, 0.0, 7.0))
        rotate(armature, "UpperLeg_R", (48.0, 0.0, -7.0))
        rotate(armature, "LowerLeg_L", (-72.0, 0.0, 0.0))
        rotate(armature, "LowerLeg_R", (-72.0, 0.0, 0.0))
        rotate(armature, "Spine", (12.0, 0.0, 0.0))
        hips = armature.pose.bones.get("Hips")
        if hips is not None:
            hips.location.z = -0.10
    bpy.context.view_layer.update()


def zone_for_object(name: str) -> list[str]:
    if "Sleeve" in name:
        return ["shoulder", "underarm", "elbow", "wrist"]
    if "Cuff" in name:
        return ["wrist"]
    if "Front_Upper" in name:
        return ["chest", "underarm", "abdomen"]
    if "Back_Upper" in name:
        return ["shoulder", "underarm", "back"]
    if "Highcut_Front" in name:
        return ["abdomen", "hip-crest", "groin", "inner-thigh", "leg-root"]
    if "Highcut_Back" in name:
        return ["hip-crest", "buttocks", "groin", "inner-thigh", "leg-root"]
    if "Hood" in name or "Drawcord" in name:
        return ["neck", "hood", "drawcord"]
    if "Tie" in name or "Bow" in name:
        return ["hip-crest", "side-tie"]
    if "Placket" in name or "Button" in name:
        return ["chest", "placket"]
    if "Seam" in name:
        return ["center-seam"]
    return ["other"]


def audit_intersections(
    body: bpy.types.Object,
    garments: list[bpy.types.Object],
) -> dict:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    body_tree = BVHTree.FromObject(body, depsgraph, deform=True, cage=False)
    if body_tree is None:
        raise RuntimeError("Could not construct Siroino body BVH")
    objects = []
    total = 0
    zones: dict[str, int] = {}
    for garment in garments:
        tree = BVHTree.FromObject(garment, depsgraph, deform=True, cage=False)
        overlaps = [] if tree is None else body_tree.overlap(tree)
        count = len(overlaps)
        total += count
        object_zones = zone_for_object(garment.name)
        if count:
            for zone in object_zones:
                zones[zone] = zones.get(zone, 0) + count
        objects.append(
            {
                "object": garment.name,
                "triangleOverlapPairs": count,
                "zones": object_zones,
            }
        )
    return {
        "triangleOverlapPairs": total,
        "objects": objects,
        "zoneSignals": zones,
        "pass": total == 0,
        "interpretation": "A nonzero value is a narrow-phase triangle intersection signal and requires visual inspection; zero is required for automatic PASS.",
    }


def update_manifest(
    job: dict,
    paths: dict[str, Path],
    sheet: Path,
    fit_audit: dict,
) -> None:
    manifest_path = ROOT / job["productManifestPath"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    all_images = all(path.is_file() for path in paths.values()) and sheet.is_file()
    manifest["technicalGates"]["poseRender"] = "PASS" if all_images else "FAIL"
    manifest["technicalGates"]["fitPenetration"] = (
        "PASS" if fit_audit["pass"] else "FAIL"
    )
    manifest["poseEvidence"] = {
        name: {
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": common.sha256(path),
        }
        for name, path in paths.items()
    }
    manifest["poseEvidence"]["sheet"] = {
        "path": str(sheet.relative_to(ROOT)).replace("\\", "/"),
        "sha256": common.sha256(sheet),
    }
    manifest["fitAuditSummary"] = {
        "pass": fit_audit["pass"],
        "posesWithIntersections": [
            pose
            for pose, result in fit_audit["poses"].items()
            if result["triangleOverlapPairs"] > 0
        ],
        "totalTriangleOverlapPairs": sum(
            result["triangleOverlapPairs"] for result in fit_audit["poses"].values()
        ),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    options = args()
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
        "forward-bend": ((1.65, -1.96, 0.62), (0.0, 0.0, 0.39), 1.30),
        "legs-apart": ((1.68, -1.98, 0.55), (0.0, 0.0, 0.34), 1.34),
        "walk": ((1.66, -1.98, 0.57), (0.0, 0.0, 0.35), 1.31),
        "crouch": ((1.72, -2.05, 0.46), (0.0, 0.0, 0.31), 1.28),
    }

    paths: dict[str, Path] = {}
    pose_audits: dict[str, dict] = {}
    for name in POSES:
        apply_pose(armature, base_transform, name)
        pose_audits[name] = audit_intersections(body, garments)
        path = pose_dir / f"{name}.png"
        location, target, ortho_scale = camera_settings[name]
        camera.data.ortho_scale = ortho_scale
        common.point_camera(camera, location, target)
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        paths[name] = path
    apply_pose(armature, base_transform, "neutral")
    sheet = root / "Previews" / f"{job['id']}-pose-review.webp"
    generic.sheet(paths, sheet)
    fit_audit = {
        "schemaVersion": 1,
        "checkedAt": common.utc_now(),
        "target": "SiroinoSotai_PC",
        "method": "Blender evaluated-mesh BVH narrow-phase triangle overlap",
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
        "pass": all(result["pass"] for result in pose_audits.values()),
        "failureCondition": "Any evaluated garment/body triangle intersection in any required pose produces FAIL and must be visually diagnosed before completion.",
    }
    audit_path = root / "Tests" / "fit-audit.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        json.dumps(fit_audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    update_manifest(job, paths, sheet, fit_audit)
    print(
        json.dumps(
            {
                "passed": all(path.is_file() for path in paths.values()),
                "targetSource": job["targetSourcePath"],
                "targetBody": body.name,
                "garmentObjectCount": len(garments),
                "poses": {name: str(path) for name, path in paths.items()},
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
