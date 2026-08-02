#!/usr/bin/env python3
"""Reusable Blender helpers for GenWorks product generators.

This module contains target-profile resolution, geometry clearance refinement,
studio rendering, pose review, and contact-sheet generation. Product-specific
silhouette and decoration stay in the individual product build script.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable, Iterable

import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree
from PIL import Image, ImageDraw, ImageFont


def select_body_and_armature() -> tuple[bpy.types.Object, bpy.types.Object]:
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if not armatures:
        raise RuntimeError("No armature was imported from the target FBX")
    armature = max(armatures, key=lambda obj: len(obj.data.bones))
    meshes = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH"
        and not obj.name.lower().startswith(("eye", "hair", "cloth", "outfit"))
    ]
    if not meshes:
        raise RuntimeError("No body mesh was imported from the target FBX")
    named = [obj for obj in meshes if "siroino" in obj.name.lower()]
    body = max(named or meshes, key=lambda obj: len(obj.data.vertices))
    return body, armature


def apply_large_profile(
    body: bpy.types.Object,
    requested: dict[str, float] | None = None,
) -> dict[str, object]:
    """Bake the Siroino Large profile into the validation body geometry.

    A Large-labelled prefab is still required by the workflow. The FBX may be
    shared by all size prefabs, so this function applies the official Large
    shape keys before garment extraction and then bakes the evaluated mesh.
    """
    requested = requested or {
        "All_L": 1.0,
        "Chest_L": 1.0,
        "Hips_01_L": 1.0,
        "UpperLeg_L": 1.0,
        "Breasts_L": 0.65,
    }
    keys = body.data.shape_keys.key_blocks if body.data.shape_keys else None
    if keys is None:
        raise RuntimeError("Target body has no shape keys; Siroino _Large cannot be verified")
    applied: dict[str, float] = {}
    for name, value in requested.items():
        block = keys.get(name)
        if block is not None:
            block.value = float(value)
            applied[name] = float(value)
    if "All_L" not in applied or len(applied) < 3:
        available = [block.name for block in keys]
        raise RuntimeError(
            "Siroino Large profile keys were not found; available keys: "
            + ", ".join(available[:40])
        )

    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = body.evaluated_get(depsgraph)
    baked = bpy.data.meshes.new_from_object(
        evaluated,
        preserve_all_data_layers=True,
        depsgraph=depsgraph,
    )
    if len(baked.vertices) != len(body.data.vertices):
        raise RuntimeError("Large profile bake changed topology; vertex weights would be invalid")
    original_name = body.data.name
    body.data = baked
    body.data.name = f"{original_name}_LargeBaked"
    bpy.context.view_layer.update()
    return {
        "profile": "Siroino _Large",
        "appliedShapeKeys": applied,
        "vertices": len(body.data.vertices),
    }


def body_tree(body: bpy.types.Object) -> KDTree:
    tree = KDTree(len(body.data.vertices))
    for vertex in body.data.vertices:
        tree.insert(body.matrix_world @ vertex.co, vertex.index)
    tree.balance()
    return tree


def clearance_stats(
    body: bpy.types.Object,
    objects: Iterable[bpy.types.Object],
) -> dict[str, float | int]:
    tree = body_tree(body)
    distances: list[float] = []
    for obj in objects:
        if obj.type != "MESH":
            continue
        for vertex in obj.data.vertices:
            world = obj.matrix_world @ vertex.co
            _, _, distance = tree.find(world)
            distances.append(float(distance))
    if not distances:
        return {"vertices": 0, "minimum": 0.0, "p01": 0.0, "mean": 0.0}
    values = sorted(distances)
    p01 = values[min(len(values) - 1, max(0, int(len(values) * 0.01)))]
    return {
        "vertices": len(values),
        "minimum": values[0],
        "p01": p01,
        "mean": sum(values) / len(values),
    }


def improve_clearance(
    body: bpy.types.Object,
    objects: Iterable[bpy.types.Object],
    *,
    targets: tuple[float, ...] = (0.0018, 0.0028, 0.0036),
    movable: Callable[[bpy.types.Object], bool] | None = None,
) -> list[dict[str, object]]:
    """Run deterministic body-clearance refinement passes."""
    candidates = [obj for obj in objects if obj.type == "MESH"]
    if movable is not None:
        candidates = [obj for obj in candidates if movable(obj)]
    history: list[dict[str, object]] = []
    tree = body_tree(body)
    for index, target in enumerate(targets, start=1):
        moved = 0
        maximum_move = 0.0
        for obj in candidates:
            inverse = obj.matrix_world.inverted()
            for vertex in obj.data.vertices:
                world = obj.matrix_world @ vertex.co
                nearest, _, distance = tree.find(world)
                if distance >= target:
                    continue
                direction = world - nearest
                if direction.length < 1e-8:
                    direction = Vector((world.x, world.y, 0.0))
                    if direction.length < 1e-8:
                        direction = Vector((0.0, -1.0, 0.0))
                direction.normalize()
                delta = target - distance
                vertex.co = inverse @ (world + direction * delta)
                moved += 1
                maximum_move = max(maximum_move, delta)
            obj.data.update()
        bpy.context.view_layer.update()
        history.append(
            {
                "pass": index,
                "target": target,
                "movedVertices": moved,
                "maximumMove": maximum_move,
                "clearance": clearance_stats(body, candidates),
            }
        )
    return history


def pastel_studio() -> tuple[bpy.types.Object, bpy.types.Object]:
    world = bpy.context.scene.world or bpy.data.worlds.new("GenWorks Studio World")
    bpy.context.scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (
        0.045,
        0.050,
        0.070,
        1.0,
    )
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.32

    floor_material = bpy.data.materials.new("GenWorks Pastel Floor")
    floor_material.use_nodes = True
    shader = next(
        node for node in floor_material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"
    )
    shader.inputs["Base Color"].default_value = (0.73, 0.76, 0.86, 1.0)
    shader.inputs["Roughness"].default_value = 0.78
    bpy.ops.mesh.primitive_plane_add(size=8, location=(0.0, 0.0, -0.002))
    floor = bpy.context.active_object
    floor.name = "GenWorks_Studio_Floor"
    floor.data.materials.append(floor_material)

    def area(name: str, location, energy: float, color, size: float) -> None:
        data = bpy.data.lights.new(name, type="AREA")
        data.energy = energy
        data.color = color
        data.shape = "DISK"
        data.size = size
        obj = bpy.data.objects.new(name, data)
        bpy.context.collection.objects.link(obj)
        obj.location = location
        obj.rotation_euler = (
            Vector((0.0, 0.0, 0.76)) - obj.location
        ).to_track_quat("-Z", "Y").to_euler()

    area("Key_Pink", (-1.25, -1.55, 1.75), 82, (1.0, 0.76, 0.86), 1.6)
    area("Fill_Blue", (1.45, -0.70, 1.25), 54, (0.72, 0.84, 1.0), 1.8)
    area("Rim_White", (0.75, 1.45, 1.60), 105, (1.0, 0.95, 0.90), 1.3)
    area("Front_Soft", (0.0, -1.85, 0.70), 30, (1.0, 0.97, 0.93), 1.1)

    camera_data = bpy.data.cameras.new("GenWorks_Product_Camera")
    camera = bpy.data.objects.new("GenWorks_Product_Camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = 1.30
    camera_data.lens = 72
    bpy.context.scene.camera = camera
    return floor, camera


def point_camera(
    camera: bpy.types.Object,
    location: tuple[float, float, float],
    target: tuple[float, float, float] = (0.0, -0.006, 0.62),
) -> None:
    camera.location = location
    camera.rotation_euler = (
        Vector(target) - camera.location
    ).to_track_quat("-Z", "Y").to_euler()


def reset_pose(armature: bpy.types.Object) -> None:
    for bone in armature.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0.0, 0.0, 0.0)
        bone.location = (0.0, 0.0, 0.0)
        bone.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()


def rotate(armature: bpy.types.Object, name: str, xyz_degrees: tuple[float, float, float]) -> None:
    bone = armature.pose.bones.get(name)
    if bone is None:
        return
    bone.rotation_mode = "XYZ"
    bone.rotation_euler = tuple(math.radians(value) for value in xyz_degrees)


def set_pose(armature: bpy.types.Object, name: str) -> None:
    reset_pose(armature)
    if name == "neutral":
        rotate(armature, "UpperArm_L", (-58, 0, -4))
        rotate(armature, "UpperArm_R", (-58, 0, 4))
    elif name == "arms-up":
        rotate(armature, "UpperArm_L", (12, 0, -132))
        rotate(armature, "UpperArm_R", (12, 0, 132))
        rotate(armature, "LowerArm_L", (0, 0, -20))
        rotate(armature, "LowerArm_R", (0, 0, 20))
    elif name == "arm-cross":
        rotate(armature, "UpperArm_L", (-38, 10, -48))
        rotate(armature, "UpperArm_R", (-38, -10, 48))
        rotate(armature, "LowerArm_L", (0, 0, -96))
        rotate(armature, "LowerArm_R", (0, 0, 96))
    elif name == "crouch":
        rotate(armature, "Hips", (13, 0, 0))
        rotate(armature, "UpperLeg_L", (-62, 5, -6))
        rotate(armature, "UpperLeg_R", (-62, -5, 6))
        rotate(armature, "LowerLeg_L", (92, 0, 0))
        rotate(armature, "LowerLeg_R", (92, 0, 0))
        rotate(armature, "UpperArm_L", (-35, 0, -12))
        rotate(armature, "UpperArm_R", (-35, 0, 12))
    elif name == "sit":
        rotate(armature, "Hips", (8, 0, 0))
        rotate(armature, "UpperLeg_L", (-82, 0, -5))
        rotate(armature, "UpperLeg_R", (-82, 0, 5))
        rotate(armature, "LowerLeg_L", (84, 0, 0))
        rotate(armature, "LowerLeg_R", (84, 0, 0))
        rotate(armature, "UpperArm_L", (-50, 0, -8))
        rotate(armature, "UpperArm_R", (-50, 0, 8))
    elif name == "twist":
        rotate(armature, "Hips", (0, 0, 18))
        rotate(armature, "Chest", (0, 0, -22))
        rotate(armature, "UpperArm_L", (-42, 20, -70))
        rotate(armature, "UpperArm_R", (-65, -15, 25))
        rotate(armature, "UpperLeg_L", (-12, 0, -8))
        rotate(armature, "UpperLeg_R", (8, 0, 10))
    bpy.context.view_layer.update()


def configure_render(resolution: int = 1024) -> None:
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 32
    scene.cycles.use_denoising = True
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = 0.04
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.film_transparent = False
    scene.view_settings.look = "AgX - Medium High Contrast"


def render_five_views(camera: bpy.types.Object, paths: dict[str, Path]) -> None:
    configure_render(1024)
    scene = bpy.context.scene
    views = {
        "front": (0.0, -2.55, 0.70),
        "back": (0.0, 2.55, 0.70),
        "left": (2.55, 0.0, 0.70),
        "right": (-2.55, 0.0, 0.70),
        "three-quarter": (1.70, -2.05, 0.73),
    }
    for name, location in views.items():
        output = paths[name]
        output.parent.mkdir(parents=True, exist_ok=True)
        point_camera(camera, location)
        scene.render.filepath = str(output)
        bpy.ops.render.render(write_still=True)


def render_pose_set(
    armature: bpy.types.Object,
    camera: bpy.types.Object,
    directory: Path,
) -> dict[str, Path]:
    configure_render(1024)
    scene = bpy.context.scene
    directory.mkdir(parents=True, exist_ok=True)
    locations = {
        "neutral": (0.0, -2.55, 0.70),
        "arms-up": (0.0, -2.55, 0.73),
        "arm-cross": (1.60, -2.10, 0.72),
        "crouch": (1.75, -2.05, 0.55),
        "sit": (1.70, -2.05, 0.52),
        "twist": (1.70, -2.05, 0.70),
    }
    outputs: dict[str, Path] = {}
    for name, location in locations.items():
        set_pose(armature, name)
        point_camera(camera, location)
        output = directory / f"{name}.png"
        scene.render.filepath = str(output)
        bpy.ops.render.render(write_still=True)
        outputs[name] = output
    reset_pose(armature)
    return outputs


def contact_sheet(
    images: dict[str, Path],
    output: Path,
    *,
    order: tuple[str, ...] | None = None,
    title: str = "",
) -> None:
    order = order or tuple(images)
    tile = 640
    columns = 3
    rows = math.ceil(len(order) / columns)
    header = 72 if title else 0
    canvas = Image.new("RGB", (tile * columns, tile * rows + header), (29, 32, 45))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 30)
        title_font = ImageFont.truetype("DejaVuSans.ttf", 38)
    except OSError:
        font = ImageFont.load_default()
        title_font = font
    if title:
        draw.text((28, 18), title, fill=(250, 243, 248), font=title_font)
    for index, name in enumerate(order):
        image = Image.open(images[name]).convert("RGB")
        image.thumbnail((tile, tile), Image.Resampling.LANCZOS)
        x = (index % columns) * tile
        y = (index // columns) * tile + header
        canvas.paste(image, (x + (tile - image.width) // 2, y))
        draw.rounded_rectangle((x + 18, y + 18, x + 260, y + 64), 15, fill=(18, 21, 31))
        draw.text((x + 32, y + 25), name.upper(), fill=(250, 245, 249), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, "WEBP", quality=94, method=6)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
