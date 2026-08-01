#!/usr/bin/env python3
"""Render an actual five-direction Blender preview for a HAOLAN outfit candidate.

Run with Blender:
  blender --background --factory-startup --python-exit-code 1 \
    --python tools/render_haolan_candidate_turnaround.py -- \
    --avatar <HAOLAN_Lowpoly.fbx> \
    --outfit <HAOLAN_BordeauxKnitSet.fbx> \
    --outdir Published/haolan/candidate/Previews

The script renders the imported avatar and outfit. It does not synthesize or
replace the candidate with an illustration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import bpy
from mathutils import Vector


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--avatar", type=Path, required=True)
    parser.add_argument("--outfit", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--resolution", type=int, default=1024)
    return parser.parse_args(argv)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def look_at(obj: bpy.types.Object, target: Vector) -> None:
    direction = target - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def add_area_light(name: str, location: Vector, target: Vector, energy: float, size: float) -> None:
    data = bpy.data.lights.new(name=name, type="AREA")
    data.energy = energy
    data.shape = "DISK"
    data.size = size
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    look_at(obj, target)


def fallback_material(name: str, color: tuple[float, float, float, float], roughness: float) -> bpy.types.Material:
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    if shader is not None:
        shader.inputs["Base Color"].default_value = color
        shader.inputs["Roughness"].default_value = roughness
    material.diffuse_color = color
    return material


def imported_objects(path: Path) -> list[bpy.types.Object]:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(path.resolve()))
    return [obj for obj in bpy.data.objects if obj not in before]


def mesh_bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    points: list[Vector] = []
    for obj in objects:
        if obj.type != "MESH" or obj.hide_render:
            continue
        points.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
    if not points:
        raise RuntimeError("No renderable mesh objects were imported")
    minimum = Vector((min(point.x for point in points), min(point.y for point in points), min(point.z for point in points)))
    maximum = Vector((max(point.x for point in points), max(point.y for point in points), max(point.z for point in points)))
    return minimum, maximum


def main() -> int:
    args = parse_args()
    avatar_path = args.avatar.resolve()
    outfit_path = args.outfit.resolve()
    outdir = args.outdir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    if not avatar_path.is_file():
        raise FileNotFoundError(avatar_path)
    if not outfit_path.is_file():
        raise FileNotFoundError(outfit_path)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    avatar_objects = imported_objects(avatar_path)
    outfit_objects = imported_objects(outfit_path)
    imported = avatar_objects + outfit_objects

    for obj in list(bpy.data.objects):
        if obj.type in {"CAMERA", "LIGHT"}:
            bpy.data.objects.remove(obj, do_unlink=True)

    skin_fallback = fallback_material("Preview_Skin_Fallback", (0.72, 0.52, 0.43, 1.0), 0.58)
    outfit_fallback = fallback_material("Preview_Outfit_Fallback", (0.16, 0.012, 0.035, 1.0), 0.72)
    for obj in avatar_objects:
        if obj.type == "MESH" and not obj.data.materials:
            obj.data.materials.append(skin_fallback)
    for obj in outfit_objects:
        if obj.type == "MESH" and not obj.data.materials:
            obj.data.materials.append(outfit_fallback)

    minimum, maximum = mesh_bounds(imported)
    center = (minimum + maximum) * 0.5
    dimensions = maximum - minimum
    height = max(dimensions.z, 0.01)
    horizontal = max(dimensions.x, dimensions.y, 0.01)
    scene_scale = max(height, horizontal)

    ground_material = fallback_material("Preview_Ground", (0.82, 0.82, 0.82, 1.0), 0.82)
    bpy.ops.mesh.primitive_plane_add(size=max(scene_scale * 8.0, 2.0), location=(center.x, center.y, minimum.z - height * 0.012))
    ground = bpy.context.object
    ground.name = "Preview_Ground"
    ground.data.materials.append(ground_material)

    world = bpy.data.worlds.new("Preview_World")
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs["Color"].default_value = (0.82, 0.82, 0.82, 1.0)
        background.inputs["Strength"].default_value = 0.65
    bpy.context.scene.world = world

    target = Vector((center.x, center.y, minimum.z + height * 0.52))
    add_area_light(
        "Key",
        target + Vector((-scene_scale * 1.8, -scene_scale * 2.1, scene_scale * 2.0)),
        target,
        1150.0,
        scene_scale * 1.25,
    )
    add_area_light(
        "Fill",
        target + Vector((scene_scale * 1.7, -scene_scale * 1.3, scene_scale * 1.1)),
        target,
        700.0,
        scene_scale * 1.5,
    )
    add_area_light(
        "Rim",
        target + Vector((0.0, scene_scale * 2.2, scene_scale * 1.7)),
        target,
        950.0,
        scene_scale * 1.0,
    )

    camera_data = bpy.data.cameras.new("Preview_Camera")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = max(height * 1.15, horizontal * 1.45)
    camera = bpy.data.objects.new("Preview_Camera", camera_data)
    bpy.context.collection.objects.link(camera)
    bpy.context.scene.camera = camera

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = args.resolution
    scene.render.resolution_y = args.resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.use_file_extension = True
    scene.view_settings.look = "AgX - Medium High Contrast"

    distance = max(scene_scale * 3.0, 2.0)
    directions = {
        "front": Vector((0.0, -1.0, 0.0)),
        "back": Vector((0.0, 1.0, 0.0)),
        "left": Vector((1.0, 0.0, 0.0)),
        "right": Vector((-1.0, 0.0, 0.0)),
        "three-quarter": Vector((math.sqrt(0.5), -math.sqrt(0.5), 0.0)),
    }

    rendered: dict[str, str] = {}
    for name, direction in directions.items():
        camera.location = target + direction * distance + Vector((0.0, 0.0, height * 0.025))
        look_at(camera, target)
        output = outdir / f"{name}.png"
        scene.render.filepath = str(output)
        bpy.ops.render.render(write_still=True)
        if not output.is_file() or output.stat().st_size < 10_000:
            raise RuntimeError(f"Preview render is missing or unexpectedly small: {output}")
        rendered[name] = output.name

    manifest = {
        "schemaVersion": 1,
        "candidate": "HAOLAN_BordeauxKnitSet",
        "sourceAvatarIncluded": False,
        "renderType": "actual-imported-candidate",
        "views": rendered,
        "requiredViews": ["front", "back", "left", "right", "three-quarter"],
        "resolution": [args.resolution, args.resolution],
        "avatarSha256": sha256(avatar_path),
        "outfitSha256": sha256(outfit_path),
        "blenderVersion": bpy.app.version_string,
        "renderedAt": datetime.now(timezone.utc).isoformat(),
    }
    (outdir / "preview-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
