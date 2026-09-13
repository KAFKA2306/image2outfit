#!/usr/bin/env python3
"""Render canonical Siroino poses for Rainveil and mirror PNG evidence to WebP."""
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


def _job_path() -> Path:
    if "--job" not in sys.argv:
        raise RuntimeError("--job is required")
    value = Path(sys.argv[sys.argv.index("--job") + 1])
    return value if value.is_absolute() else ROOT / value


def mirror_previews() -> int:
    job = json.loads(_job_path().read_text(encoding="utf-8"))
    root = ROOT / job["productRoot"] / "Previews"
    from PIL import Image

    count = 0
    for png in root.rglob("*.png"):
        with Image.open(png) as image:
            image.save(png.with_suffix(".webp"), format="WEBP", quality=95, method=6)
        count += 1
    print(json.dumps({"previewWebpMirrors": count, "previewRoot": str(root)}))
    return count


if __name__ == "__main__":
    code = poses.main()
    if code:
        raise SystemExit(code)
    mirror_previews()
    raise SystemExit(0)
