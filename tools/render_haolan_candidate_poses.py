#!/usr/bin/env python3
"""Render required deformation poses for an actual HAOLAN outfit candidate."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import bpy
from mathutils import Euler, Vector

POSES = ("neutral", "arms-up", "arm-cross", "crouch", "sit", "prone")


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--avatar", type=Path, required=True)
    parser.add_argument("--outfit", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--resolution", type=int, default=1024)
    return parser.parse_args(raw)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def imported(path: Path) -> list[bpy.types.Object]:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(path.resolve()), use_anim=False)
    return [obj for obj in bpy.data.objects if obj not in before]


def fallback_material(
    name: str,
    color: tuple[float, float, float, float],
    roughness: float,
) -> bpy.types.Material:
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    if shader is not None:
        shader.inputs["Base Color"].default_value = color
        shader.inputs["Roughness"].default_value = roughness
    material.diffuse_color = color
    return material


def ensure_materials(
    objects: list[bpy.types.Object],
    material: bpy.types.Material,
) -> None:
    for obj in objects:
        if obj.type == "MESH" and not obj.data.materials:
            obj.data.materials.append(material)


def look_at(obj: bpy.types.Object, target: Vector) -> None:
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def add_area_light(
    name: str,
    location: Vector,
    target: Vector,
    energy: float,
    size: float,
) -> None:
    data = bpy.data.lights.new(name=name, type="AREA")
    data.energy = energy
    data.shape = "DISK"
    data.size = size
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    look_at(obj, target)


def rotate(
    armature: bpy.types.Object,
    bone_name: str,
    degrees: tuple[float, float, float],
) -> None:
    bone = armature.pose.bones.get(bone_name)
    if bone is None:
        return
    bone.rotation_mode = "XYZ"
    bone.rotation_euler = tuple(math.radians(value) for value in degrees)


def reset_armature(
    armature: bpy.types.Object,
    transform: tuple[Vector, Euler, Vector],
) -> None:
    location, rotation, scale = transform
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
    armatures: list[bpy.types.Object],
    base: dict[str, tuple[Vector, Euler, Vector]],
    pose_name: str,
) -> None:
    for armature in armatures:
        reset_armature(armature, base[armature.name])
        if pose_name == "arms-up":
            rotate(armature, "UpperArm_L", (-105.0, 0.0, -8.0))
            rotate(armature, "UpperArm_R", (-105.0, 0.0, 8.0))
            rotate(armature, "LowerArm_L", (-8.0, 0.0, 0.0))
            rotate(armature, "LowerArm_R", (-8.0, 0.0, 0.0))
        elif pose_name == "arm-cross":
            rotate(armature, "UpperArm_L", (-38.0, 18.0, -54.0))
            rotate(armature, "UpperArm_R", (-38.0, -18.0, 54.0))
            rotate(armature, "LowerArm_L", (-86.0, 0.0, 20.0))
            rotate(armature, "LowerArm_R", (-86.0, 0.0, -20.0))
        elif pose_name == "crouch":
            rotate(armature, "UpperLeg_L", (48.0, 0.0, 6.0))
            rotate(armature, "UpperLeg_R", (48.0, 0.0, -6.0))
            rotate(armature, "LowerLeg_L", (-72.0, 0.0, 0.0))
            rotate(armature, "LowerLeg_R", (-72.0, 0.0, 0.0))
            hips = armature.pose.bones.get("Hips")
            if hips is not None:
                hips.location.z = -0.10
        elif pose_name == "sit":
            rotate(armature, "UpperLeg_L", (65.0, 0.0, 2.0))
            rotate(armature, "UpperLeg_R", (65.0, 0.0, -2.0))
            rotate(armature, "LowerLeg_L", (-65.0, 0.0, 0.0))
            rotate(armature, "LowerLeg_R", (-65.0, 0.0, 0.0))
            hips = armature.pose.bones.get("Hips")
            if hips is not None:
                hips.location.z = -0.16
        elif pose_name == "prone":
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


def evaluated_bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    points: list[Vector] = []
    for obj in objects:
        if obj.type != "MESH" or obj.hide_render:
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            points.extend(\n                evaluated.matrix_world @ vertex.co for vertex in mesh.vertices\n            )
        finally:
            evaluated.to_mesh_clear()
    if not points:
        raise RuntimeError("No evaluated mesh vertices were available for pose framing")
    minimum = Vector(tuple(min(point[index] for point in points) for index in range(3)))
    maximum = Vector(tuple(max(point[index] for point in points) for index in range(3)))
    return minimum, maximum


def main() -> int:
    options = parse_args()
    avatar = options.avatar.resolve()
    outfit = options.outfit.resolve()
    outdir = options.outdir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    if not avatar.is_file():
        raise FileNotFoundError(avatar)
    if not outfit.is_file():
        raise FileNotFoundError(outfit)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    avatar_objects = imported(avatar)
    outfit_objects = imported(outfit)
    render_objects = avatar_objects + outfit_objects
    armatures = [obj for obj in render_objects if obj.type == "ARMATURE"]
    if len(armatures) < 2:
        raise RuntimeError(\n            f"Expected target and outfit armatures, found {len(armatures)}"\n        )

    ensure_materials(
        avatar_objects,
        fallback_material("HAOLAN_Preview_Skin", (0.72, 0.52, 0.43, 1.0), 0.58),
    )
    ensure_materials(
        outfit_objects,
        fallback_material("Bordeaux_Preview_Knit", (0.16, 0.012, 0.035, 1.0), 0.72),
    )

    base = {
        armature.name: (
            armature.location.copy(),
            armature.rotation_euler.copy(),
            armature.scale.copy(),
        )
        for armature in armatures
    }

    world = bpy.data.worlds.new("HAOLAN_Pose_World")
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs["Color"].default_value = (0.82, 0.82, 0.82, 1.0)
        background.inputs["Strength"].default_value = 0.62
    bpy.context.scene.world = world

    camera_data = bpy.data.cameras.new("HAOLAN_Pose_Camera")
    camera_data.type = "ORTHO"
    camera = bpy.data.objects.new("HAOLAN_Pose_Camera", camera_data)
    bpy.context.collection.objects.link(camera)
    bpy.context.scene.camera = camera

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = options.resolution
    scene.render.resolution_y = options.resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.view_settings.look = "AgX - Medium High Contrast"

    rendered: dict[str, str] = {}
    for pose_name in POSES:
        apply_pose(armatures, base, pose_name)
        minimum, maximum = evaluated_bounds(render_objects)
        center = (minimum + maximum) * 0.5
        dimensions = maximum - minimum
        scale = max(dimensions.x, dimensions.y, dimensions.z, 0.01)
        target = center + Vector((0.0, 0.0, dimensions.z * 0.02))

        for light in [obj for obj in list(bpy.data.objects) if obj.type == "LIGHT"]:
            bpy.data.objects.remove(light, do_unlink=True)
        add_area_light("Pose_Key", target + Vector((-scale * 1.8, -scale * 2.0, scale * 1.8)), target, 1100.0, scale * 1.2)
        add_area_light("Pose_Fill", target + Vector((scale * 1.6, -scale * 1.2, scale * 1.0)), target, 650.0, scale * 1.4)
        add_area_light("Pose_Rim", target + Vector((0.0, scale * 2.0, scale * 1.5)), target, 850.0, scale)

        direction = Vector((0.68, -0.73, 0.16))
        if pose_name == "prone":
            direction = Vector((0.58, -0.58, 0.58))
        direction.normalize()
        camera.location = target + direction * max(scale * 3.0, 2.0)
        camera.data.ortho_scale = max(\n            dimensions.z * 1.18, dimensions.x * 1.45, dimensions.y * 1.45\n        )
        look_at(camera, target)

        output = outdir / f"{pose_name}.png"
        scene.render.filepath = str(output)
        bpy.ops.render.render(write_still=True)
        if not output.is_file() or output.stat().st_size < 10_000:
            raise RuntimeError(\n                f"Pose render is missing or unexpectedly small: {output}"\n            )
        rendered[pose_name] = output.name

    manifest = {
        "schemaVersion": 1,
        "candidate": "HAOLAN_BordeauxKnitSet",
        "renderType": "actual-imported-candidate-required-poses",
        "requiredPoses": list(POSES),
        "poses": rendered,
        "resolution": [options.resolution, options.resolution],
        "avatarSha256": sha256(avatar),
        "outfitSha256": sha256(outfit),
        "sourceAvatarIncluded": False,
        "blenderVersion": bpy.app.version_string,
        "renderedAt": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = outdir.parent / "pose-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
