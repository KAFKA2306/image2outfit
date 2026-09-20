"""Render post-bake evidence for the settled Nocturnal Shrine Maiden panels."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "siroino-nocturnal-shrine-maiden-long-hakama-set"
JOB = ROOT / f"config/products/{PRODUCT_ID}/job.json"
BLEND = ROOT / f"Assets/GenWorks/{PRODUCT_ID}/Source/Blender/SiroinoNocturnalShrineMaidenLongHakama.blend"
REPORT = ROOT / f"Assets/GenWorks/{PRODUCT_ID}/Evidence/Build/product-build-report.json"
EVIDENCE = ROOT / f"Assets/GenWorks/{PRODUCT_ID}/Evidence/Build/post-cloth-render.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_builder():
    path = ROOT / "tools/siroino_nocturnal_shrine_maiden_long_hakama_build.py"
    spec = importlib.util.spec_from_file_location(PRODUCT_ID, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    job = json.loads(JOB.read_text(encoding="utf-8"))
    bpy.ops.wm.open_mainfile(filepath=str(BLEND), load_ui=False)
    builder = load_builder()
    if str(ROOT / "tools") not in sys.path:
        sys.path.insert(0, str(ROOT / "tools"))
    import siroino_strappy_knit_build as import_base
    import siroino_lunar_tech_hoodie_build as shared_base
    builder.base = shared_base
    builder.base.import_base = import_base
    settled_frame = int(job["garmentPipeline"]["clothSimulation"].get("frameEnd", 32))
    bpy.context.scene.frame_set(settled_frame)
    armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
    body = next(obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.name.startswith("SiroinoSotai_PC"))
    body.hide_render = False
    _, camera = import_base.studio_setup()
    camera.data.ortho_scale = 1.44
    target = (0.0, -0.005, 0.69)
    previews = {name: ROOT / path for name, path in job["previewPaths"].items()}
    shared_base.import_base = import_base
    shared_base.render_product_views(camera, previews, target)
    pose_dir = ROOT / Path(job["posePaths"]["neutral"]).parent
    pose_paths = shared_base.render_poses(armature, camera, pose_dir, target)
    multiview = ROOT / f"Assets/GenWorks/{PRODUCT_ID}/Previews/{PRODUCT_ID}-multiview.webp"
    pose_review = ROOT / f"Assets/GenWorks/{PRODUCT_ID}/Previews/{PRODUCT_ID}-pose-review.webp"
    import_base.contact_sheet(previews, multiview)
    shared_base.contact_sheet_named(pose_paths, pose_review, ("neutral", "arms-up", "arm-cross", "crouch", "sit", "prone"))
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    report["checkedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    report["evidenceRenderFrame"] = settled_frame
    for name, path in previews.items():
        report["previews"][name]["sha256"] = sha256(path)
    for name, path in pose_paths.items():
        report["poses"][name]["sha256"] = sha256(path)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evidence = {
        "schemaVersion": 1,
        "productId": PRODUCT_ID,
        "status": "PASS",
        "frame": settled_frame,
        "renderedAfter": f"Assets/GenWorks/{PRODUCT_ID}/Evidence/Build/cloth-simulation.json",
        "views": {name: {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(path)} for name, path in previews.items()},
        "poses": {name: {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(path)} for name, path in pose_paths.items()},
    }
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
