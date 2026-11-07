#!/usr/bin/env python3
"""Render SiroinoSotai_PC pose evidence for the fitted military romper."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "siroino-military-sheer-romper-large"
POSES = ("neutral", "arms-up", "arm-cross", "crouch", "sit", "twist", "prone")
BONE_ALIASES = {
    "hips": ("Hips", "Hips.1", "J_Bip_C_Hips"),
    "spine": ("Spine", "Spine.1", "J_Bip_C_Spine"),
    "chest": ("Chest", "Chest.1", "UpperChest", "J_Bip_C_Chest"),
    "upper_arm_l": ("UpperArm_L", "UpperArm_L.1", "LeftUpperArm", "J_Bip_L_UpperArm"),
    "lower_arm_l": ("LowerArm_L", "LowerArm_L.1", "LeftLowerArm", "J_Bip_L_LowerArm"),
    "upper_arm_r": ("UpperArm_R", "UpperArm_R.1", "RightUpperArm", "J_Bip_R_UpperArm"),
    "lower_arm_r": ("LowerArm_R", "LowerArm_R.1", "RightLowerArm", "J_Bip_R_LowerArm"),
    "upper_leg_l": ("UpperLeg_L", "UpperLeg_L.1", "LeftUpperLeg", "J_Bip_L_UpperLeg"),
    "lower_leg_l": ("LowerLeg_L", "LowerLeg_L.1", "LeftLowerLeg", "J_Bip_L_LowerLeg"),
    "upper_leg_r": ("UpperLeg_R", "UpperLeg_R.1", "RightUpperLeg", "J_Bip_R_UpperLeg"),
    "lower_leg_r": ("LowerLeg_R", "LowerLeg_R.1", "RightLowerLeg", "J_Bip_R_LowerLeg"),
}


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    return parser.parse_args(raw)


def repo_path(value: str) -> Path:
    path = (ROOT / value).resolve()
    if path != ROOT and ROOT not in path.parents:
        raise ValueError(f"path escapes repository: {value}")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_body() -> bpy.types.Object:
    candidates = [
        obj for obj in bpy.data.objects
        if obj.type == "MESH" and obj.get("image2outfit_role") == "target-avatar"
    ]
    if not candidates:
        candidates = [
            obj for obj in bpy.data.objects
            if obj.type == "MESH" and obj.name.startswith("SiroinoSotai_PC")
        ]
    if not candidates:
        raise RuntimeError("actual SiroinoSotai_PC body is absent from review Blend")
    return max(candidates, key=lambda obj: len(obj.data.vertices))


def find_armature() -> bpy.types.Object:
    candidates = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
    if not candidates:
        raise RuntimeError("SiroinoSotai_PC armature is absent from review Blend")
    return max(candidates, key=lambda obj: len(obj.data.bones))


def resolve_bone(armature: bpy.types.Object, semantic: str) -> bpy.types.PoseBone:
    for name in BONE_ALIASES[semantic]:
        bone = armature.pose.bones.get(name)
        if bone is not None:
            return bone
    lower = {bone.name.lower(): bone for bone in armature.pose.bones}
    for name in BONE_ALIASES[semantic]:
        candidate = lower.get(name.lower())
        if candidate is not None:
            return candidate
    raise KeyError(
        f"required SiroinoSotai_PC pose bone missing: {semantic}; "
        f"available={sorted(bone.name for bone in armature.pose.bones)}"
    )


def reset_pose(armature: bpy.types.Object) -> None:
    armature.rotation_mode = "XYZ"
    armature.rotation_euler = (0.0, 0.0, 0.0)
    armature.location = (0.0, 0.0, 0.0)
    for bone in armature.pose.bones:
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (0.0, 0.0, 0.0)
        bone.location = (0.0, 0.0, 0.0)
        bone.scale = (1.0, 1.0, 1.0)


def rotate(armature: bpy.types.Object, semantic: str, values) -> None:
    bone = resolve_bone(armature, semantic)
    bone.rotation_mode = "XYZ"
    bone.rotation_euler = values


def apply_pose(armature: bpy.types.Object, name: str) -> None:
    reset_pose(armature)
    if name == "arms-up":
        rotate(armature, "upper_arm_l", (0.0, -0.15, 1.36))
        rotate(armature, "upper_arm_r", (0.0, 0.15, -1.36))
    elif name == "arm-cross":
        rotate(armature, "upper_arm_l", (-0.15, 0.58, 0.48))
        rotate(armature, "upper_arm_r", (-0.15, -0.58, -0.48))
        rotate(armature, "lower_arm_l", (0.0, -0.85, -0.32))
        rotate(armature, "lower_arm_r", (0.0, 0.85, 0.32))
    elif name == "crouch":
        rotate(armature, "hips", (0.20, 0.0, 0.0))
        rotate(armature, "upper_leg_l", (0.92, 0.0, 0.04))
        rotate(armature, "upper_leg_r", (0.92, 0.0, -0.04))
        rotate(armature, "lower_leg_l", (-1.28, 0.0, 0.0))
        rotate(armature, "lower_leg_r", (-1.28, 0.0, 0.0))
    elif name == "sit":
        rotate(armature, "hips", (0.10, 0.0, 0.0))
        rotate(armature, "upper_leg_l", (1.38, 0.0, 0.02))
        rotate(armature, "upper_leg_r", (1.38, 0.0, -0.02))
        rotate(armature, "lower_leg_l", (-1.34, 0.0, 0.0))
        rotate(armature, "lower_leg_r", (-1.34, 0.0, 0.0))
    elif name == "twist":
        rotate(armature, "spine", (0.0, 0.0, 0.26))
        rotate(armature, "chest", (0.0, 0.0, 0.36))
        rotate(armature, "upper_arm_l", (0.0, 0.0, 0.35))
        rotate(armature, "upper_arm_r", (0.0, 0.0, -0.28))
    elif name == "prone":
        rotate(armature, "hips", (1.18, 0.0, 0.0))
        rotate(armature, "chest", (0.28, 0.0, 0.0))
        rotate(armature, "upper_arm_l", (0.0, -0.20, 0.72))
        rotate(armature, "upper_arm_r", (0.0, 0.20, -0.72))
        rotate(armature, "upper_leg_l", (-0.18, 0.0, 0.03))
        rotate(armature, "upper_leg_r", (-0.18, 0.0, -0.03))
    bpy.context.view_layer.update()


def evaluated_bounds(body: bpy.types.Object) -> tuple[Vector, Vector]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = body.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        points = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()
    minimum = Vector((
        min(point.x for point in points),
        min(point.y for point in points),
        min(point.z for point in points),
    ))
    maximum = Vector((
        max(point.x for point in points),
        max(point.y for point in points),
        max(point.z for point in points),
    ))
    return minimum, maximum


def compose(paths: dict[str, Path], output: Path) -> None:
    cell = (350, 350)
    canvas = Image.new("RGB", (cell[0] * 4, cell[1] * 2), (238, 239, 242))
    draw = ImageDraw.Draw(canvas)
    for index, name in enumerate(POSES):
        image = Image.open(paths[name]).convert("RGB")
        image.thumbnail(cell, Image.Resampling.LANCZOS)
        x = (index % 4) * cell[0]
        y = (index // 4) * cell[1]
        canvas.paste(
            image,
            (x + (cell[0] - image.width) // 2, y + (cell[1] - image.height) // 2),
        )
        draw.text((x + 10, y + 10), name, fill=(34, 36, 42))
    canvas.save(output, "WEBP", quality=92, method=6)


def update_manifest(job: dict) -> None:
    path = repo_path(job["productManifestPath"])
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    gates = manifest.setdefault("technicalGates", {})
    gates["actualTargetPoseRender"] = "PASS"
    gates["humanPoseReview"] = "PENDING"
    manifest["poseEvidenceUsesActualTarget"] = True
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def update_hashes(root: Path) -> None:
    lines = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "SOURCE_HASHES.txt":
            lines.append(f"{sha256(path)}  {path.relative_to(root).as_posix()}")
    (root / "SOURCE_HASHES.txt").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def strip_target_body() -> None:
    for obj in list(bpy.data.objects):
        if obj.type == "MESH" and str(obj.get("image2outfit_role", "")).startswith("target-avatar"):
            bpy.data.objects.remove(obj, do_unlink=True)
    for collection in (bpy.data.meshes, bpy.data.materials, bpy.data.images):
        for datablock in list(collection):
            if datablock.users == 0:
                collection.remove(datablock)


def main() -> int:
    parsed = parse_args()
    job = json.loads(Path(parsed.job).read_text(encoding="utf-8-sig"))
    if job.get("id") != PRODUCT_ID:
        raise ValueError(f"unexpected product job: {job.get('id')!r}")
    body = find_body()
    armature = find_armature()
    camera = bpy.data.objects.get("ReviewCamera")
    if camera is None or camera.type != "CAMERA":
        raise RuntimeError("review camera not found")

    product_root = repo_path(job["productRoot"])
    pose_dir = product_root / "Previews" / "Poses"
    pose_dir.mkdir(parents=True, exist_ok=True)
    minimum, maximum = evaluated_bounds(body)
    center = (minimum + maximum) * 0.5
    height = max(1.0, maximum.z - minimum.z)
    camera.location = center + Vector((height * 1.22, -height * 1.42, height * 0.08))
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()

    paths: dict[str, Path] = {}
    for name in POSES:
        apply_pose(armature, name)
        path = pose_dir / f"{name}.png"
        bpy.context.scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        paths[name] = path
    reset_pose(armature)
    bpy.context.view_layer.update()
    output = product_root / "Previews" / f"{PRODUCT_ID}-pose-review.webp"
    compose(paths, output)
    update_manifest(job)
    update_hashes(product_root)

    # Do not redistribute the target avatar mesh in the delivery Blend.
    strip_target_body()
    bpy.ops.wm.save_as_mainfile(
        filepath=str(repo_path(job["blendPath"])),
        compress=True,
    )
    update_hashes(product_root)
    print(
        json.dumps(
            {
                "productId": PRODUCT_ID,
                "poses": list(POSES),
                "poseReview": output.relative_to(ROOT).as_posix(),
                "usesActualSiroinoSotaiPC": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
