#!/usr/bin/env python3
"""Render six deformation poses and finalize cloth-skirt skinning.

The skirt is physically settled by Blender Cloth during the canonical build.
Before verification/export, this script replaces the generic nearest-body
weights on the frozen cloth mesh with one Hips group. That preserves the baked
pleated rest shape when the legs bend instead of mixing left/right upper-leg
weights and producing a fan-shaped skirt.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import bpy
from mathutils import Euler, Vector
from PIL import Image, ImageDraw, ImageFont

PRODUCT_ID = "siroino-black-cat-bondage"
REVISION = "v7-cs-25-10300-cloth-pose-stable-skinning"
SKIRT_METHOD = "hips-rigid-cloth-rest-shape"
ROOT = Path.cwd().resolve()


def parse_args() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    return parser.parse_args(values)


def repo_path(value: str) -> Path:
    return (ROOT / value).resolve()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def resolve_armature() -> bpy.types.Object:
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if not armatures:
        raise RuntimeError("No armature exists in the generated blend")
    return next((obj for obj in armatures if "Siroino" in obj.name), armatures[0])


def garment_meshes() -> list[bpy.types.Object]:
    return [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.get("productId") == PRODUCT_ID
    ]


def resolve_cloth_skirt() -> bpy.types.Object:
    skirts = [obj for obj in garment_meshes() if obj.name == "Skirt_Cloth"]
    if len(skirts) != 1:
        raise RuntimeError(f"expected one Skirt_Cloth, got {len(skirts)}")
    return skirts[0]


def rebind_cloth_skirt_to_hips(
    armature: bpy.types.Object,
) -> dict[str, Any]:
    """Keep the baked cloth shape rigidly attached to the avatar Hips bone."""
    skirt = resolve_cloth_skirt()
    if armature.data.bones.get("Hips") is None:
        raise RuntimeError("Siroino armature does not expose the Hips bone")

    for group in list(skirt.vertex_groups):
        skirt.vertex_groups.remove(group)
    hips = skirt.vertex_groups.new(name="Hips")
    indices = [vertex.index for vertex in skirt.data.vertices]
    if not indices:
        raise RuntimeError("Skirt_Cloth has no vertices")
    hips.add(indices, 1.0, "REPLACE")

    armature_modifiers = [
        modifier for modifier in skirt.modifiers if modifier.type == "ARMATURE"
    ]
    if not armature_modifiers:
        modifier = skirt.modifiers.new("SiroinoSotai Armature", "ARMATURE")
        armature_modifiers = [modifier]
    for modifier in armature_modifiers:
        modifier.object = armature
        modifier.use_deform_preserve_volume = True

    skirt["skinWeightMethod"] = SKIRT_METHOD
    skirt["skinWeightBone"] = "Hips"
    skirt["skinWeightInfluences"] = 1
    bpy.context.view_layer.update()
    return {
        "object": skirt.name,
        "method": SKIRT_METHOD,
        "bone": "Hips",
        "vertexCount": len(indices),
        "influencesPerVertex": 1,
        "armature": armature.name,
    }


def export_corrected_fbx(job: dict[str, Any], armature: bpy.types.Object) -> None:
    fbx = repo_path(job["fbxAssetPath"])
    fbx.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    for obj in garment_meshes():
        obj.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.export_scene.fbx(
        filepath=str(fbx),
        use_selection=True,
        apply_unit_scale=True,
        add_leaf_bones=False,
        bake_anim=False,
        object_types={"ARMATURE", "MESH"},
    )


def finalize_quality_reports(
    job: dict[str, Any],
    skinning: dict[str, Any],
) -> None:
    product_root = repo_path(job["productRoot"])
    quality_path = product_root / "Evidence" / "Build" / "quality-audit.json"
    report_path = product_root / "Evidence" / "Build" / "product-build-report.json"

    meshes = garment_meshes()
    skirt = resolve_cloth_skirt()
    non_skirt = [obj for obj in meshes if obj is not skirt]
    checks_for_weights = {
        "nearestBodyTop4Weights": bool(non_skirt)
        and all(
            obj.get("skinWeightMethod") == "nearest-siroino-body-top4"
            for obj in non_skirt
        ),
        "clothPoseStableSkinning": (
            skirt.get("skinWeightMethod") == SKIRT_METHOD
            and len(skirt.vertex_groups) == 1
            and skirt.vertex_groups[0].name == "Hips"
        ),
    }

    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    component_checks = dict(quality.get("componentChecks", {}))
    component_checks.update(checks_for_weights)
    quality["componentChecks"] = component_checks
    quality["revision"] = REVISION
    quality["finalSkinning"] = skinning
    quality["passed"] = (
        not quality.get("unweightedObjects")
        and all(bool(value) for value in component_checks.values())
    )
    write_json(quality_path, quality)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["revision"] = REVISION
    report["finalSkinning"] = skinning
    report["visualReviewPriorRevisionV6"] = {
        "workflowRun": 31303805825,
        "result": "DIRECT_VISUAL_REVIEW_FAIL",
        "finding": (
            "crouch/sit/prone fan-shaped skirt deformation after generic "
            "nearest-body top-4 skinning"
        ),
        "correction": (
            "preserve baked cloth rest shape with one Hips influence on Skirt_Cloth"
        ),
    }
    report["pending"] = [
        "direct visual review of current five views",
        "direct visual review of all six required poses",
    ]
    write_json(report_path, report)


def reset_pose(
    armature: bpy.types.Object,
    base: tuple[Vector, Euler, Vector],
) -> None:
    location, rotation, scale = base
    armature.location = location.copy()
    armature.rotation_mode = "XYZ"
    armature.rotation_euler = rotation.copy()
    armature.scale = scale.copy()
    for bone in armature.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0.0, 0.0, 0.0)
        bone.location = (0.0, 0.0, 0.0)
        bone.scale = (1.0, 1.0, 1.0)


def rotate(
    armature: bpy.types.Object,
    name: str,
    degrees: tuple[float, float, float],
) -> None:
    bone = armature.pose.bones.get(name)
    if bone is None:
        return
    bone.rotation_mode = "XYZ"
    bone.rotation_euler = tuple(math.radians(value) for value in degrees)


def apply_pose(
    armature: bpy.types.Object,
    base: tuple[Vector, Euler, Vector],
    name: str,
) -> None:
    reset_pose(armature, base)
    if name == "arms-up":
        rotate(armature, "UpperArm_L", (-100.0, 0.0, -8.0))
        rotate(armature, "UpperArm_R", (-100.0, 0.0, 8.0))
        rotate(armature, "LowerArm_L", (-12.0, 0.0, 0.0))
        rotate(armature, "LowerArm_R", (-12.0, 0.0, 0.0))
    elif name == "arm-cross":
        rotate(armature, "UpperArm_L", (-38.0, 18.0, -54.0))
        rotate(armature, "UpperArm_R", (-38.0, -18.0, 54.0))
        rotate(armature, "LowerArm_L", (-86.0, 0.0, 20.0))
        rotate(armature, "LowerArm_R", (-86.0, 0.0, -20.0))
    elif name == "crouch":
        rotate(armature, "UpperLeg_L", (48.0, 0.0, 6.0))
        rotate(armature, "UpperLeg_R", (48.0, 0.0, -6.0))
        rotate(armature, "LowerLeg_L", (-72.0, 0.0, 0.0))
        rotate(armature, "LowerLeg_R", (-72.0, 0.0, 0.0))
        hips = armature.pose.bones.get("Hips")
        if hips is not None:
            hips.location.z = -0.10
    elif name == "sit":
        rotate(armature, "UpperLeg_L", (65.0, 0.0, 2.0))
        rotate(armature, "UpperLeg_R", (65.0, 0.0, -2.0))
        rotate(armature, "LowerLeg_L", (-65.0, 0.0, 0.0))
        rotate(armature, "LowerLeg_R", (-65.0, 0.0, 0.0))
        hips = armature.pose.bones.get("Hips")
        if hips is not None:
            hips.location.z = -0.16
    elif name == "prone":
        armature.rotation_euler.rotate_axis("X", math.radians(90.0))
        armature.location.y += 0.10
        armature.location.z += 0.16
        rotate(armature, "UpperLeg_L", (-10.0, 0.0, 3.0))
        rotate(armature, "UpperLeg_R", (-10.0, 0.0, -3.0))
        rotate(armature, "LowerLeg_L", (20.0, 0.0, 0.0))
        rotate(armature, "LowerLeg_R", (20.0, 0.0, 0.0))
        rotate(armature, "UpperArm_L", (-34.0, 0.0, -18.0))
        rotate(armature, "UpperArm_R", (-34.0, 0.0, 18.0))
        rotate(armature, "LowerArm_L", (-48.0, 0.0, 0.0))
        rotate(armature, "LowerArm_R", (-48.0, 0.0, 0.0))
    bpy.context.view_layer.update()


def point_camera(
    camera: bpy.types.Object,
    location: tuple[float, float, float],
    target: tuple[float, float, float],
) -> None:
    camera.location = location
    camera.rotation_euler = (
        Vector(target) - camera.location
    ).to_track_quat("-Z", "Y").to_euler()


def resolve_camera() -> bpy.types.Object:
    cameras = [obj for obj in bpy.context.scene.objects if obj.type == "CAMERA"]
    camera = next((obj for obj in cameras if obj.name == "BCB_Render_Camera"), None)
    if camera is None:
        bpy.ops.object.camera_add()
        camera = bpy.context.object
    camera.data.type = "ORTHO"
    bpy.context.scene.camera = camera
    return camera


def contact_sheet(paths: dict[str, Path], output: Path) -> None:
    tile = 512
    canvas = Image.new("RGB", (tile * 3, tile * 2), (20, 22, 30))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 24)
    except OSError:
        font = ImageFont.load_default()
    for index, (name, image_path) in enumerate(paths.items()):
        image = Image.open(image_path).convert("RGB")
        image.thumbnail((tile, tile), Image.Resampling.LANCZOS)
        x = index % 3 * tile
        y = index // 3 * tile
        canvas.paste(image, (x + (tile - image.width) // 2, y))
        draw.rounded_rectangle(
            (x + 16, y + 16, x + 220, y + 52),
            10,
            fill=(8, 10, 16),
        )
        draw.text(
            (x + 26, y + 20),
            name.upper(),
            fill=(245, 245, 248),
            font=font,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, "WEBP", quality=92, method=6)


def main() -> int:
    job = json.loads(repo_path(parse_args().job).read_text(encoding="utf-8-sig"))
    if job.get("id") != PRODUCT_ID:
        raise RuntimeError(f"job id must be {PRODUCT_ID}")

    armature = resolve_armature()
    skinning = rebind_cloth_skirt_to_hips(armature)
    finalize_quality_reports(job, skinning)

    camera = resolve_camera()
    base = (
        armature.location.copy(),
        armature.rotation_euler.copy(),
        armature.scale.copy(),
    )
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 768
    scene.render.resolution_y = 768
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.view_settings.look = "AgX - Medium High Contrast"
    settings = {
        "neutral": ((2.15, -2.15, 1.02), (0.0, 0.0, 0.82), 1.62),
        "arms-up": ((2.15, -2.15, 1.10), (0.0, 0.0, 0.88), 1.78),
        "arm-cross": ((2.15, -2.15, 1.02), (0.0, 0.0, 0.82), 1.62),
        "crouch": ((2.20, -2.20, 0.74), (0.0, 0.0, 0.62), 1.45),
        "sit": ((2.20, -2.20, 0.70), (0.0, 0.0, 0.58), 1.45),
        "prone": ((2.30, -0.65, 0.85), (0.0, -0.32, 0.30), 1.55),
    }
    generated: dict[str, Path] = {}
    for name in ("neutral", "arms-up", "arm-cross", "crouch", "sit", "prone"):
        apply_pose(armature, base, name)
        location, target, scale = settings[name]
        camera.data.ortho_scale = scale
        point_camera(camera, location, target)
        output = repo_path(job["posePaths"][name])
        output.parent.mkdir(parents=True, exist_ok=True)
        scene.render.filepath = str(output)
        bpy.ops.render.render(write_still=True)
        generated[name] = output

    apply_pose(armature, base, "neutral")
    sheet = (
        repo_path(job["productRoot"])
        / "Previews"
        / "siroino-black-cat-bondage-pose-review.webp"
    )
    contact_sheet(generated, sheet)
    bpy.ops.wm.save_as_mainfile(filepath=str(repo_path(job["blendPath"])))
    export_corrected_fbx(job, armature)

    meshes = garment_meshes()
    missing_modifiers = [
        obj.name
        for obj in meshes
        if not any(mod.type == "ARMATURE" for mod in obj.modifiers)
    ]
    missing_weights = [obj.name for obj in meshes if not obj.vertex_groups]
    report = {
        "schemaVersion": 1,
        "productId": PRODUCT_ID,
        "revision": REVISION,
        "passed": (
            not missing_modifiers
            and not missing_weights
            and len(generated) == 6
        ),
        "technicalOnly": True,
        "armature": armature.name,
        "garmentMeshCount": len(meshes),
        "missingArmatureModifier": missing_modifiers,
        "missingVertexGroups": missing_weights,
        "finalSkinning": skinning,
        "poses": {
            name: str(path.relative_to(ROOT))
            for name, path in generated.items()
        },
        "contactSheet": str(sheet.relative_to(ROOT)),
        "correctedFbx": job["fbxAssetPath"],
        "directImageReviewRequired": True,
    }
    write_json(
        repo_path(job["productRoot"])
        / "Evidence"
        / "Build"
        / "pose-audit.json",
        report,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
