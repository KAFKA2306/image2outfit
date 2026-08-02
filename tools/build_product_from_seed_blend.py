#!/usr/bin/env python3
"""Build a product from a tracked Blender seed without private runner assets.

The seed is expected to contain the target body and armature. This tool exports
only that body/armature to a temporary FBX, verifies required body shape keys,
materializes a temporary job, and delegates to ``productBuildScript``. It is a
Blender-only fallback; Unity integration remains a separate self-hosted gate.
"""
from __future__ import annotations

import argparse
import json
import runpy
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import bpy
import genworks_product_common as common

ROOT = TOOLS_DIR.parent


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    parser.add_argument("--seed-config")
    return parser.parse_args(raw)


def repo_path(value: str) -> Path:
    path = (ROOT / value).resolve()
    if path != ROOT and ROOT not in path.parents:
        raise ValueError(f"path escapes repository: {value}")
    return path


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def export_seed_target(body: bpy.types.Object, armature: bpy.types.Object, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    body.hide_set(False)
    body.hide_render = False
    armature.hide_set(False)
    body.select_set(True)
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.export_scene.fbx(
        filepath=str(output),
        use_selection=True,
        object_types={"ARMATURE", "MESH"},
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_ALL",
        bake_space_transform=False,
        use_mesh_modifiers=False,
        mesh_smooth_type="FACE",
        add_leaf_bones=False,
        primary_bone_axis="Y",
        secondary_bone_axis="X",
        use_armature_deform_only=False,
        bake_anim=False,
        path_mode="AUTO",
        embed_textures=False,
    )
    if not output.is_file() or output.stat().st_size <= 0:
        raise RuntimeError(f"temporary target FBX was not exported: {output}")


def verify_large_keys(body: bpy.types.Object, profile: dict[str, float]) -> dict[str, object]:
    keys = body.data.shape_keys.key_blocks if body.data.shape_keys else None
    available = [] if keys is None else [block.name for block in keys]
    required = [name for name, value in profile.items() if float(value) != 0.0]
    missing = [name for name in required if name not in available]
    if missing:
        raise RuntimeError(
            "seed body does not contain the requested Large profile keys: "
            + ", ".join(missing)
        )
    return {
        "required": required,
        "availableCount": len(available),
        "verified": True,
    }


def main() -> int:
    args = parse_args()
    tracked_job = Path(args.job).resolve()
    seed_config_path = (
        Path(args.seed_config).resolve()
        if args.seed_config
        else tracked_job.parent / "hosted-seed.json"
    )
    job = json.loads(tracked_job.read_text(encoding="utf-8-sig"))
    if not seed_config_path.is_file():
        raise FileNotFoundError(f"hosted seed config not found: {seed_config_path}")
    seed_config = json.loads(seed_config_path.read_text(encoding="utf-8-sig"))
    seed_value = seed_config.get("targetSeedBlendPath")
    if not isinstance(seed_value, str) or not seed_value:
        raise ValueError("seed config targetSeedBlendPath is required")
    seed = repo_path(seed_value)
    if not seed.is_file():
        raise FileNotFoundError(f"tracked seed blend not found: {seed_value}")

    bpy.ops.wm.open_mainfile(filepath=str(seed))
    body, armature = common.select_body_and_armature()
    profile = job.get("bodyShapeProfile")
    if not isinstance(profile, dict) or not profile:
        raise ValueError("job.bodyShapeProfile is required")
    key_evidence = verify_large_keys(body, profile)

    artifact_dir = repo_path(job["artifactDir"])
    artifact_dir.mkdir(parents=True, exist_ok=True)
    temporary_fbx = artifact_dir / "seed-target" / "SiroinoSotai_LargeSeed.fbx"
    export_seed_target(body, armature, temporary_fbx)

    materialized_job = dict(job)
    materialized_job["targetSourcePath"] = relative(temporary_fbx)
    materialized_job["targetAvatarAssetPath"] = "hosted-seed://Siroino_Large"
    materialized_job["resolvedTarget"] = {
        "strategy": "tracked-seed-blend",
        "profile": seed_config.get("profile", "Siroino _Large"),
        "seedBlend": seed_value,
        "sourceFbx": relative(temporary_fbx),
        "shapeKeyEvidence": key_evidence,
        "unityIntegration": "PENDING_SELF_HOSTED",
    }
    materialized_path = artifact_dir / "hosted-job.json"
    materialized_path.write_text(
        json.dumps(materialized_job, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (artifact_dir / "hosted-target-evidence.json").write_text(
        json.dumps(materialized_job["resolvedTarget"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    build_script_value = job.get("productBuildScript")
    if not isinstance(build_script_value, str) or not build_script_value:
        raise ValueError("job.productBuildScript is required for hosted seed builds")
    build_script = repo_path(build_script_value)
    if build_script.resolve() == Path(__file__).resolve():
        raise RuntimeError("productBuildScript cannot point back to the seed wrapper")
    if not build_script.is_file():
        raise FileNotFoundError(f"product build script not found: {build_script_value}")
    sys.argv = [str(build_script), "--", "--job", str(materialized_path)]
    try:
        runpy.run_path(str(build_script), run_name="__main__")
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
