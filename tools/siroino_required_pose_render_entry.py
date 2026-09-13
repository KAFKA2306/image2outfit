#!/usr/bin/env python3
"""Hosted pose entrypoint with render-evidence metadata enabled.

The hosted artifact contract collects WebP evidence. The canonical pose renderer
writes PNGs, so this entrypoint mirrors generated preview PNGs to WebP after a
successful pose run without changing the renderer or deleting the PNG source.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import render_evidence_bootstrap  # noqa: F401,E402
import siroino_required_pose_render as poses  # noqa: E402


def _job_path() -> Path | None:
    if "--job" not in sys.argv:
        return None
    index = sys.argv.index("--job")
    if index + 1 >= len(sys.argv):
        return None
    path = Path(sys.argv[index + 1])
    return path if path.is_absolute() else ROOT / path


def _mirror_preview_pngs_to_webp() -> int:
    job_path = _job_path()
    if job_path is None or not job_path.is_file():
        return 0
    job = json.loads(job_path.read_text(encoding="utf-8"))
    root = ROOT / job["productRoot"] / "Previews"
    if not root.is_dir():
        return 0
    from PIL import Image

    count = 0
    for png in root.rglob("*.png"):
        webp = png.with_suffix(".webp")
        with Image.open(png) as image:
            image.save(webp, format="WEBP", quality=95, method=6)
        count += 1
    print(json.dumps({"previewWebpMirrors": count, "previewRoot": str(root)}))
    return count


if __name__ == "__main__":
    code = poses.main()
    if code:
        raise SystemExit(code)
    _mirror_preview_pngs_to_webp()
    raise SystemExit(0)
