"""Render the actual weighted prototype and imported target for direct review."""
import argparse
import hashlib
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from blender_cloth_simulation import read_json, repo_path, write_json
from genworks_product_common import pastel_studio, point_camera, configure_render, reset_pose, set_pose


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def raise_arms_world_up(armature):
    """Resolve the imported rig's local axes instead of guessing Euler angles."""
    evidence = {}
    for name in ("UpperArm_L", "UpperArm_R"):
        bone = armature.pose.bones[name]
        rest_world = armature.matrix_world @ bone.matrix
        local_up = (rest_world.to_3x3().inverted() @ Vector((0, 0, 1))).normalized()
        bone.rotation_mode = "QUATERNION"
        bone.rotation_quaternion = Vector((0, 1, 0)).rotation_difference(local_up)
        bpy.context.view_layer.update()
        head = armature.matrix_world @ bone.head
        tail = armature.matrix_world @ bone.tail
        direction = (tail - head).normalized()
        if direction.z < 0.98:
            raise ValueError(f"arms-up world-axis check failed for {name}: {direction}")
        evidence[name] = {"headWorldM": list(head), "tailWorldM": list(tail),
                          "directionWorld": list(direction), "pointsUp": True}
    return evidence


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    job = read_json(repo_path(args.job))
    runtime = ROOT / ".image2outfit/products" / job["id"]
    skin = read_json(runtime / "skin/skin-export-report.json")
    source = repo_path(skin["weightedBlendPath"])
    if digest(source) != skin["weightedBlendSha256"]:
        raise ValueError("weighted render source is stale")
    bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False)
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if len(armatures) != 1:
        raise ValueError("render requires one target armature")
    armature = armatures[0]
    required = {"Hips", "UpperArm_L", "UpperArm_R", "LowerArm_L", "LowerArm_R",
                "UpperLeg_L", "UpperLeg_R", "LowerLeg_L", "LowerLeg_R"}
    if not required <= set(armature.pose.bones.keys()):
        raise ValueError("required pose bones are absent")
    floor, camera = pastel_studio()
    configure_render(1024)
    bpy.context.scene.render.engine = "BLENDER_EEVEE_NEXT"
    floor.hide_render = True
    views = {"front": (0, -1, 0), "back": (0, 1, 0), "left": (1, 0, 0),
             "right": (-1, 0, 0), "three-quarter": (0.7, -0.7, 0)}
    records = []
    for kind, outputs in (("view", job["previewPaths"]), ("pose", job["posePaths"])):
        for name, value in outputs.items():
            reset_pose(armature)
            pose_measurements = {}
            if kind == "pose":
                if name == "prone":
                    armature.pose.bones["Hips"].rotation_euler.x = math.pi / 2
                    bpy.context.view_layer.update()
                elif name == "arms-up":
                    pose_measurements = raise_arms_world_up(armature)
                elif name in {"neutral", "arm-cross", "crouch", "sit"}:
                    set_pose(armature, name)
                else:
                    raise ValueError(f"unknown render pose: {name}")
            deps = bpy.context.evaluated_depsgraph_get()
            points = [obj.evaluated_get(deps).matrix_world @ Vector(corner)
                      for obj in bpy.context.scene.objects if obj.type == "MESH" and obj != floor
                      for corner in obj.evaluated_get(deps).bound_box]
            lower = Vector(tuple(min(p[a] for p in points) for a in range(3)))
            upper = Vector(tuple(max(p[a] for p in points) for a in range(3)))
            centre = (lower + upper) / 2
            span = (upper - lower).length
            camera.data.ortho_scale = span * 1.12
            direction = Vector(views[name] if kind == "view" else (0.7, -0.7, 0.12))
            point_camera(camera, tuple(centre + direction * 3), tuple(centre))
            output = repo_path(value)
            output.parent.mkdir(parents=True, exist_ok=True)
            bpy.context.scene.render.filepath = str(output)
            bpy.ops.render.render(write_still=True)
            records.append({"kind": kind, "name": name, "path": value, "sha256": digest(output),
                            "poseMeasurements": pose_measurements,
                            "boneRotationsQuaternion": {b.name: list(b.rotation_quaternion)
                                                        for b in armature.pose.bones if b.rotation_mode == "QUATERNION"},
                            "boneRotationsRadians": {b.name: list(b.rotation_euler) for b in armature.pose.bones
                                                     if any(abs(x) > 1e-9 for x in b.rotation_euler)}})
    write_json(runtime / "reports/weighted-render.json", {
        "schemaVersion": 1, "productId": job["id"], "sourcePath": skin["weightedBlendPath"],
        "sourceSha256": digest(source), "blenderVersion": bpy.app.version_string,
        "engine": bpy.context.scene.render.engine, "records": records,
        "qualityDecision": "UNVERIFIED", "grantsVisualAcceptance": False,
        "evidenceBoundary": "Actual neutral prototype and diagnostic bone poses; no fit, runtime, or appearance acceptance.",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
