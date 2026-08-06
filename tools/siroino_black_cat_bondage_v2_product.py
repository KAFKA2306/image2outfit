#!/usr/bin/env python3
"""Second deterministic build: corrected fit, bone binding, and five views."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector
from PIL import Image, ImageDraw, ImageFont

import siroino_black_cat_bondage_geometry as v1

PRODUCT_ID = "siroino-black-cat-bondage"
ROOT = Path.cwd().resolve()


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    return parser.parse_args(raw)


def repo_path(value: str) -> Path:
    return (ROOT / value).resolve()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def convert_curves(objects: list[bpy.types.Object]) -> list[bpy.types.Object]:
    converted: list[bpy.types.Object] = []
    for obj in objects:
        if obj.type != "CURVE":
            converted.append(obj)
            continue
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.convert(target="MESH")
        converted.append(bpy.context.object)
    return converted


def apply_shape_corrections(objects: list[bpy.types.Object]) -> None:
    strap_x = (0.375, 0.435, 0.495, 0.555)
    for obj in objects:
        name = obj.name
        side = -1.0 if "_L" in name else 1.0
        if name == "CatEar_Headband":
            obj.location.z = 1.285
            obj.scale *= 0.80
        elif name.startswith("CatEar_") and obj.type == "MESH":
            for vertex in obj.data.vertices:
                vertex.co.x *= 0.80
                vertex.co.z = 1.285 + (vertex.co.z - 1.455) * 0.80
        elif name.startswith("Gauntlet_L") or name.startswith("Gauntlet_R"):
            if name in {"Gauntlet_L", "Gauntlet_R"}:
                obj.location = (side * 0.475, -0.005, 0.995)
                obj.rotation_euler[1] = math.pi / 2.0
            elif name.startswith("Gauntlet_Ring"):
                obj.location = (side * 0.475, -0.044, 0.995)
            elif name.startswith("Gauntlet_Strap"):
                index = int(name.rsplit("_", 1)[-1])
                obj.location = (side * strap_x[index], -0.004, 0.995)
        elif name.startswith("Thigh_Garter"):
            obj.location.z = 0.438
            obj.rotation_euler = (0.0, 0.0, 0.0)
        elif name == "Corset_Back":
            obj.scale.y = 0.55
    bpy.context.view_layer.update()


def apply_surface_modifiers(objects: list[bpy.types.Object]) -> None:
    for obj in objects:
        if obj.type != "MESH":
            continue
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        for modifier in list(obj.modifiers):
            if modifier.type in {"SOLIDIFY", "BEVEL"}:
                bpy.ops.object.modifier_apply(modifier=modifier.name)


def bone_for(name: str) -> str:
    if name.startswith("CatEar"):
        return "Head"
    if name.startswith("Choker"):
        return "Neck"
    if name.startswith("UpperArm_Band_L"):
        return "UpperArm_L"
    if name.startswith("UpperArm_Band_R"):
        return "UpperArm_R"
    if name.startswith("Gauntlet") and "_L" in name:
        return "LowerArm_L"
    if name.startswith("Gauntlet") and "_R" in name:
        return "LowerArm_R"
    if name.startswith("Thigh") and "_L" in name:
        return "UpperLeg_L"
    if name.startswith("Thigh") and "_R" in name:
        return "UpperLeg_R"
    if name.startswith("Skirt") or name.startswith("Waist") or name == "Corset_Bottom_Binding":
        return "Hips"
    return "Chest"


def bind(objects: list[bpy.types.Object], armature: bpy.types.Object) -> dict[str, Any]:
    available = {bone.name for bone in armature.data.bones}
    fallback = "Hips" if "Hips" in available else next(iter(available))
    assignments: dict[str, str] = {}
    unweighted: list[str] = []
    for obj in objects:
        if obj.type != "MESH":
            unweighted.append(obj.name)
            continue
        requested = bone_for(obj.name)
        bone = requested if requested in available else fallback
        group = obj.vertex_groups.new(name=bone)
        indices = [vertex.index for vertex in obj.data.vertices]
        if indices:
            group.add(indices, 1.0, "REPLACE")
        obj.parent = armature
        modifier = obj.modifiers.new("SiroinoSotai Armature", "ARMATURE")
        modifier.object = armature
        modifier.use_deform_preserve_volume = True
        obj["rigidBone"] = bone
        assignments[obj.name] = bone
    return {
        "armature": armature.name,
        "weightedObjectCount": len(assignments),
        "unweightedObjects": unweighted,
        "assignments": assignments,
    }


def resolve_armature() -> bpy.types.Object:
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if not armatures:
        raise RuntimeError("SiroinoSotai_PC armature was not imported")
    return next((obj for obj in armatures if "Siroino" in obj.name), armatures[0])


def point_camera(camera: bpy.types.Object, location: tuple[float, float, float]) -> None:
    camera.location = location
    camera.rotation_euler = (Vector((0.0, 0.0, 0.82)) - camera.location).to_track_quat("-Z", "Y").to_euler()


def studio() -> bpy.types.Object:
    world = bpy.context.scene.world or bpy.data.worlds.new("BCB_World")
    bpy.context.scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs["Color"].default_value = (0.035, 0.038, 0.050, 1.0)
        background.inputs["Strength"].default_value = 0.38
    for location, energy, size in (
        ((2.5, -3.5, 3.0), 950.0, 3.0),
        ((-2.0, -1.0, 2.2), 600.0, 2.5),
        ((0.0, 2.5, 2.5), 450.0, 2.0),
    ):
        bpy.ops.object.light_add(type="AREA", location=location)
        light = bpy.context.object
        light.data.energy = energy
        light.data.size = size
        light.rotation_euler = (Vector((0.0, 0.0, 0.85)) - light.location).to_track_quat("-Z", "Y").to_euler()
    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.name = "BCB_Render_Camera"
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 1.62
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
        draw.rounded_rectangle((x + 16, y + 16, x + 220, y + 52), 10, fill=(8, 10, 16))
        draw.text((x + 26, y + 20), name.upper(), fill=(245, 245, 248), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, "WEBP", quality=92, method=6)


def render_views(job: dict[str, Any], camera: bpy.types.Object) -> dict[str, str]:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 768
    scene.render.resolution_y = 768
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.view_settings.look = "AgX - Medium High Contrast"
    locations = {
        "front": (0.0, -3.0, 0.92),
        "back": (0.0, 3.0, 0.92),
        "left": (-3.0, 0.0, 0.92),
        "right": (3.0, 0.0, 0.92),
        "three-quarter": (2.15, -2.15, 1.02),
    }
    generated: dict[str, Path] = {}
    for name, location in locations.items():
        output = repo_path(job["previewPaths"][name])
        output.parent.mkdir(parents=True, exist_ok=True)
        point_camera(camera, location)
        scene.render.filepath = str(output)
        bpy.ops.render.render(write_still=True)
        generated[name] = output
    contact_sheet(
        generated,
        repo_path(job["productRoot"]) / "Previews" / "siroino-black-cat-bondage-multiview.webp",
    )
    return {name: str(value.relative_to(ROOT)) for name, value in generated.items()}


def main() -> int:
    job = json.loads(repo_path(parse_args().job).read_text(encoding="utf-8-sig"))
    if job.get("id") != PRODUCT_ID:
        raise RuntimeError(f"job id must be {PRODUCT_ID}")
    v1.clean()
    imported = v1.import_avatar(job)
    armature = resolve_armature()
    leather = v1.mat("BCB_FauxLeather", (0.006, 0.008, 0.012, 1.0), 0.06, 0.22)
    fabric = v1.mat("BCB_MatteFabric", (0.010, 0.010, 0.014, 1.0), 0.0, 0.48)
    metal = v1.mat("BCB_DarkMetal", (0.16, 0.17, 0.19, 1.0), 0.94, 0.18)
    objects = convert_curves(v1.build(leather, fabric, metal))
    apply_shape_corrections(objects)
    apply_surface_modifiers(objects)
    rig = bind(objects, armature)
    for obj in objects:
        obj["productId"] = PRODUCT_ID
        obj["targetAvatar"] = "SiroinoSotai_PC"
        obj["sourceRedistributed"] = False
    views = render_views(job, studio())

    product_root = repo_path(job["productRoot"])
    blend = repo_path(job["blendPath"])
    fbx = repo_path(job["fbxAssetPath"])
    report_path = product_root / "Evidence" / "Build" / "product-build-report.json"
    quality_path = product_root / "Evidence" / "Build" / "quality-audit.json"
    for target in (blend, fbx, report_path, quality_path):
        target.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    for obj in objects:
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

    checks = {
        "pleats24": sum(obj.name.startswith("Skirt_Pleat_") for obj in objects) == 24,
        "catEars2": sum(obj.name.startswith("CatEar_Outer_") for obj in objects) == 2,
        "gauntlets2": sum(obj.name in {"Gauntlet_L", "Gauntlet_R"} for obj in objects) == 2,
        "thighGarters2": sum(obj.name.startswith("Thigh_Garter_") for obj in objects) == 2,
        "fiveViews": len(views) == 5,
    }
    quality = {
        "schemaVersion": 1,
        "productId": PRODUCT_ID,
        "passed": not rig["unweightedObjects"] and all(checks.values()),
        "technicalOnly": True,
        "objectCount": len(objects),
        "weightedObjectCount": rig["weightedObjectCount"],
        "unweightedObjects": rig["unweightedObjects"],
        "componentChecks": checks,
        "renderedViews": sorted(views),
        "visualReviewRequired": True,
        "posePenetrationReviewRequired": True,
    }
    write_json(quality_path, quality)
    report = {
        "schemaVersion": 1,
        "productId": PRODUCT_ID,
        "status": "WORKING",
        "revision": "v2-fitted-rigged-five-view",
        "objectCount": len(objects),
        "armatureResolved": armature.name,
        "importedTargetObjects": imported,
        "rig": rig,
        "blendPath": job["blendPath"],
        "fbxAssetPath": job["fbxAssetPath"],
        "renderedViews": views,
        "qualityAudit": str(quality_path.relative_to(ROOT)),
        "pending": ["six-pose penetration review", "direct visual review", "Unity runtime verification"],
    }
    write_json(report_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if quality["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
