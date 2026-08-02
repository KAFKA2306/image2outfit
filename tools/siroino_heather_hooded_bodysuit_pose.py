#!/usr/bin/env python3
"""Render the standard Siroino pose suite with a product-specific sheet name."""
from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_required_pose_render as generic

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_SHEET = generic.sheet


def product_sheet(paths, _output):
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    job_arg = raw[raw.index("--job") + 1]
    job = json.loads(Path(job_arg).read_text(encoding="utf-8-sig"))
    output = ROOT / job["productRoot"] / "Previews" / f"{job['id']}-pose-review.webp"
    return ORIGINAL_SHEET(paths, output)


def main() -> int:
    generic.sheet = product_sheet
    return generic.main()


if __name__ == "__main__":
    raise SystemExit(main())
