"""Render post-bake evidence for the settled Verdant Ranger Explorer Set scene."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
JOB = ROOT / "config/products/siroino-verdant-ranger-explorer-set/job.json"
BLEND = (
    ROOT
    / "Assets/GenWorks/siroino-verdant-ranger-explorer-set/Source/Blender/SiroinoVerdantRangerExplorer.blend"
)
REPORT = (
    ROOT
    / "Assets/GenWorks/siroino-verdant-ranger-explorer-set/Evidence/Build/product-build-report.json"
)
EVIDENCE = (
    ROOT
    / "Assets/GenWorks/siroino-verdant-ranger-explorer-set/Evidence/Build/post-cloth-render.json"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_builder():
    path = ROOT / "tools/siroino_verdant_ranger_explorer_build.py"
    spec = importlib.util.spec_from_file_location(
        "siroino_verdant_ranger_explorer_build", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    job = json.loads(JOB.read_text(encoding="utf-8"))
    bpy.ops.wm.open_mainfile(filepath=str(BLEND))
    builder = load_builder()
    if str(ROOT / "tools") not in sys.path:
        sys.path.insert(0, str(ROOT / "tools"))
    import siroino_strappy_knit_build as import_base

    builder.import_base = import_base
    settled_frame = int(job["garmentPipeline"]["clothSimulation"].get("frameEnd", 30))
    bpy.context.scene.frame_set(settled_frame)
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    body = next(
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.name.startswith("SiroinoSotai_PC")
    )
    body.hide_render = False
    _, camera = import_base.studio_setup()
    camera.data.ortho_scale = 1.42
    target = (0.0, -0.005, 0.70)
    previews = {name: (ROOT / path) for name, path in job["previewPaths"].items()}
    builder.render_product_views(camera, previews, target)
    pose_dir = ROOT / Path(job["posePaths"]["neutral"]).parent
    pose_paths = builder.render_poses(armature, camera, pose_dir, target)
    multiview = (
        ROOT
        / "Assets/GenWorks/siroino-verdant-ranger-explorer-set/Previews/siroino-verdant-ranger-explorer-set-multiview.webp"
    )
    pose_review = (
        ROOT
        / "Assets/GenWorks/siroino-verdant-ranger-explorer-set/Previews/siroino-verdant-ranger-explorer-set-pose-review.webp"
    )
    import_base.contact_sheet(previews, multiview)
    builder.contact_sheet_named(
        pose_paths,
        pose_review,
        ("neutral", "arms-up", "arm-cross", "crouch", "sit", "prone"),
    )

    report = json.loads(REPORT.read_text(encoding="utf-8"))
    report["checkedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    report["evidenceRenderFrame"] = settled_frame
    for name, path in previews.items():
        report["previews"][name]["sha256"] = sha256(path)
    for name, path in pose_paths.items():
        report["poses"][name]["sha256"] = sha256(path)
    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    evidence = {
        "schemaVersion": 1,
        "productId": "siroino-verdant-ranger-explorer-set",
        "status": "PASS",
        "frame": settled_frame,
        "renderedAfter": "Assets/GenWorks/siroino-verdant-ranger-explorer-set/Evidence/Build/cloth-simulation.json",
        "views": {
            name: {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256(path),
            }
            for name, path in previews.items()
        },
        "poses": {
            name: {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256(path),
            }
            for name, path in pose_paths.items()
        },
    }
    EVIDENCE.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
