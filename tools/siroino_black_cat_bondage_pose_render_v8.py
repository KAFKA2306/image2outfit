#!/usr/bin/env python3
"""Render six review poses after pose-conditioned Blender Cloth settling.

The canonical build produces the fitted cloth rest mesh. This verification pass
poses the avatar first, then runs a fresh cloth simulation in that pose so world
gravity and body collision can falsify pose-specific failures such as prone.
The settled pose meshes are evidence only; the exported product remains the
neutral rigged garment and is not replaced by one pose's baked geometry.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector

import siroino_black_cat_bondage_pose_render as v7

PRODUCT_ID = v7.PRODUCT_ID
REVISION = "v8-cs-25-10300-pose-conditioned-cloth"
SETTLE_FRAMES = 32
PIN_GROUP = "Cloth_Pose_Pin"
ROOT = Path.cwd().resolve()


def target_avatar_meshes() -> list[bpy.types.Object]:
    return [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.get("image2outfitRole") == "target-avatar"
    ]


def ensure_body_collision() -> list[str]:
    configured: list[str] = []
    for obj in target_avatar_meshes():
        if not any(mod.type == "COLLISION" for mod in obj.modifiers):
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.modifier_add(type="COLLISION")
        configured.append(obj.name)
    if not configured:
        raise RuntimeError("target avatar collision mesh is unavailable")
    return configured


def evaluated_world_vertices(obj: bpy.types.Object) -> list[Vector]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    return [evaluated.matrix_world @ vertex.co for vertex in evaluated.data.vertices]


def prepare_pose_cloth(skirt: bpy.types.Object) -> tuple[bpy.types.Modifier, int]:
    stale = [modifier for modifier in skirt.modifiers if modifier.type == "CLOTH"]
    for modifier in stale:
        skirt.modifiers.remove(modifier)
    existing_pin = skirt.vertex_groups.get(PIN_GROUP)
    if existing_pin is not None:
        skirt.vertex_groups.remove(existing_pin)

    maximum_z = max(vertex.co.z for vertex in skirt.data.vertices)
    minimum_z = min(vertex.co.z for vertex in skirt.data.vertices)
    height = maximum_z - minimum_z
    threshold = maximum_z - max(0.004, height * 0.08)
    pin_indices = [
        vertex.index for vertex in skirt.data.vertices if vertex.co.z >= threshold
    ]
    if not pin_indices:
        raise RuntimeError("pose cloth pin group would be empty")
    pin = skirt.vertex_groups.new(name=PIN_GROUP)
    pin.add(pin_indices, 1.0, "REPLACE")

    modifier = skirt.modifiers.new("Pose Conditioned Cloth", "CLOTH")
    modifier.settings.quality = 8
    modifier.settings.mass = 0.30
    modifier.settings.vertex_group_mass = PIN_GROUP
    modifier.settings.tension_stiffness = 15.0
    modifier.settings.compression_stiffness = 15.0
    modifier.settings.shear_stiffness = 5.0
    modifier.settings.bending_stiffness = 0.5
    modifier.collision_settings.use_collision = True
    modifier.collision_settings.use_self_collision = True
    modifier.collision_settings.distance_min = 0.004
    modifier.collision_settings.self_distance_min = 0.004
    modifier.point_cache.frame_start = 1
    modifier.point_cache.frame_end = SETTLE_FRAMES
    return modifier, len(pin_indices)


def cleanup_pose_cloth(skirt: bpy.types.Object, modifier: bpy.types.Modifier) -> None:
    skirt.modifiers.remove(modifier)
    pin = skirt.vertex_groups.get(PIN_GROUP)
    if pin is not None:
        skirt.vertex_groups.remove(pin)
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()


def settle_pose(skirt: bpy.types.Object) -> dict[str, Any]:
    modifier, pin_count = prepare_pose_cloth(skirt)
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = SETTLE_FRAMES
    scene.frame_set(1)
    bpy.context.view_layer.update()
    start = evaluated_world_vertices(skirt)
    for frame in range(2, SETTLE_FRAMES + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
    end = evaluated_world_vertices(skirt)
    displacements = [(after - before).length for before, after in zip(start, end)]
    result = {
        "frames": SETTLE_FRAMES,
        "pinVertexCount": pin_count,
        "vertexCount": len(end),
        "movedVertexCount": sum(value > 1e-6 for value in displacements),
        "maxDisplacement": max(displacements, default=0.0),
        "meanDisplacement": (
            sum(displacements) / len(displacements) if displacements else 0.0
        ),
        "collision": True,
        "selfCollision": True,
        "gravity": tuple(float(value) for value in scene.gravity),
    }
    return {"modifier": modifier, "audit": result}


def main() -> int:
    job = json.loads(v7.repo_path(v7.parse_args().job).read_text(encoding="utf-8-sig"))
    if job.get("id") != PRODUCT_ID:
        raise RuntimeError(f"job id must be {PRODUCT_ID}")

    armature = v7.resolve_armature()
    skinning = v7.rebind_cloth_skirt_to_hips(armature)
    body_collision = ensure_body_collision()
    skirt = v7.resolve_cloth_skirt()
    camera = v7.resolve_camera()
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
    pose_audits: dict[str, Any] = {}
    for name in ("neutral", "arms-up", "arm-cross", "crouch", "sit", "prone"):
        v7.apply_pose(armature, base, name)
        settled = settle_pose(skirt)
        pose_audits[name] = settled["audit"]
        location, target, scale = settings[name]
        camera.data.ortho_scale = scale
        v7.point_camera(camera, location, target)
        output = v7.repo_path(job["posePaths"][name])
        output.parent.mkdir(parents=True, exist_ok=True)
        scene.render.filepath = str(output)
        bpy.ops.render.render(write_still=True)
        generated[name] = output
        cleanup_pose_cloth(skirt, settled["modifier"])

    v7.apply_pose(armature, base, "neutral")
    sheet = (
        v7.repo_path(job["productRoot"])
        / "Previews"
        / "siroino-black-cat-bondage-pose-review.webp"
    )
    v7.contact_sheet(generated, sheet)
    v7.finalize_quality_reports(job, skinning)
    bpy.ops.wm.save_as_mainfile(filepath=str(v7.repo_path(job["blendPath"])))
    v7.export_corrected_fbx(job, armature)

    report = {
        "schemaVersion": 2,
        "productId": PRODUCT_ID,
        "revision": REVISION,
        "passed": len(generated) == 6 and all(
            audit["movedVertexCount"] > 0 for audit in pose_audits.values()
        ),
        "technicalOnly": True,
        "method": "pose-first-then-cloth-settle",
        "bodyCollisionObjects": body_collision,
        "poseSettling": pose_audits,
        "poses": {
            name: str(path.relative_to(ROOT)) for name, path in generated.items()
        },
        "contactSheet": str(sheet.relative_to(ROOT)),
        "directImageReviewRequired": True,
        "acceptanceBoundary": (
            "technical settling PASS does not imply visual PASS; all six rendered poses "
            "must still pass direct review"
        ),
    }
    v7.write_json(
        v7.repo_path(job["productRoot"]) / "Evidence" / "Build" / "pose-audit.json",
        report,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
