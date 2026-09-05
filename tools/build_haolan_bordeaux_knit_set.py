#!/usr/bin/env python3
"""Run the retained HAOLAN Bordeaux generator from a tracked schema-v2 job.

The licensed HAOLAN avatar is used when it exists on a self-hosted runner. On a
public runner, a geometry-free skeleton seed reproduces the garment rig without
redistributing HAOLAN meshes, materials, textures, or Prefabs.
"""
from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
LEGACY_BUILDER = ROOT / "tools" / "haolan_knit_build.py"
LOCAL_JOB = ROOT / "Assets" / "_Local" / "Jobs" / "haolan-bordeaux-knit-set" / "job.json"
SEED_FBX = ROOT / "Assets" / "_Local" / "GeneratedSeeds" / "haolan-v1.6-skeleton.fbx"


def parse_job_path() -> Path:
    if "--" not in sys.argv:
        raise SystemExit("Blender arguments must contain -- --job <path>")
    args = sys.argv[sys.argv.index("--") + 1 :]
    if "--job" not in args:
        raise SystemExit("--job is required")
    value = Path(args[args.index("--job") + 1])
    return value if value.is_absolute() else (ROOT / value).resolve()


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (ROOT / path).resolve()


def materialize_skeleton(seed_path: Path) -> Path:
    seed = json.loads(seed_path.read_text(encoding="utf-8-sig"))
    if seed.get("adapterId") != "haolan-v1.6":
        raise ValueError("Unexpected skeleton adapter")
    if seed.get("source", {}).get("avatarGeometryIncluded") is not False:
        raise ValueError("Skeleton seed must not contain avatar geometry")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    armature_data = bpy.data.armatures.new("Armature")
    armature = bpy.data.objects.new("Armature", armature_data)
    bpy.context.collection.objects.link(armature)
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    created = {}
    for item in seed["bones"]:
        bone = armature_data.edit_bones.new(item["name"])
        bone.head = item["head"]
        bone.tail = item["tail"]
        if (bone.tail - bone.head).length < 0.001:
            raise ValueError(f"Bone is too short: {bone.name}")
        created[bone.name] = bone
    for item in seed["bones"]:
        parent = item.get("parent")
        if parent:
            created[item["name"]].parent = created[parent]
            created[item["name"]].use_connect = False

    bpy.ops.object.mode_set(mode="OBJECT")
    SEED_FBX.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.fbx(
        filepath=str(SEED_FBX),
        use_selection=True,
        object_types={"ARMATURE"},
        add_leaf_bones=False,
        bake_anim=False,
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_UNITS",
        axis_forward="-Z",
        axis_up="Y",
    )
    if not SEED_FBX.is_file() or SEED_FBX.stat().st_size < 1_000:
        raise RuntimeError("Failed to materialize the geometry-free HAOLAN skeleton seed")
    return SEED_FBX


def main() -> int:
    source_job = parse_job_path()
    job = json.loads(source_job.read_text(encoding="utf-8-sig"))
    if job.get("schemaVersion") != 2:
        raise ValueError("HAOLAN Bordeaux build requires schemaVersion 2")
    if job.get("id") != "haolan-bordeaux-knit-set":
        raise ValueError("Unexpected job id for HAOLAN Bordeaux builder")

    target = resolve(job["targetSourcePath"])
    if not target.is_file():
        seed_path = source_job.parent / "skeleton.json"
        if not seed_path.is_file():
            raise FileNotFoundError(
                f"HAOLAN target source and geometry-free skeleton seed are unavailable: {target}"
            )
        target = materialize_skeleton(seed_path)
        job["targetSourcePath"] = str(target)
        job["buildInputMode"] = "geometry-free-skeleton-seed"
    else:
        job["targetSourcePath"] = str(target)
        job["buildInputMode"] = "licensed-local-avatar-source"

    LOCAL_JOB.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_JOB.write_text(
        json.dumps(job, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    sys.argv = [str(LEGACY_BUILDER), "--", "--job", str(LOCAL_JOB)]
    runpy.run_path(str(LEGACY_BUILDER), run_name="__main__")

    outfit = resolve(job["fbxAssetPath"])
    previews = resolve(job["productRoot"]) / "Previews"
    poses = previews / "Poses"
    previews.mkdir(parents=True, exist_ok=True)
    poses.mkdir(parents=True, exist_ok=True)

    def run_renderer(script: Path, argv: list[str]) -> None:
        previous = sys.argv[:]
        try:
            sys.argv = [str(script), "--", *argv]
            namespace = runpy.run_path(str(script), run_name="image2outfit_renderer")
            code = namespace["main"]()
            if code not in (None, 0):
                raise RuntimeError(f"{script.name} exited {code}")
        finally:
            sys.argv = previous

    run_renderer(
        ROOT / "tools" / "render_haolan_candidate_turnaround.py",
        [
            "--avatar",
            str(target),
            "--outfit",
            str(outfit),
            "--outdir",
            str(previews),
            "--resolution",
            "1024",
        ],
    )
    run_renderer(
        ROOT / "tools" / "render_haolan_candidate_poses.py",
        [
            "--avatar",
            str(target),
            "--outfit",
            str(outfit),
            "--outdir",
            str(poses),
            "--resolution",
            "1024",
        ],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
