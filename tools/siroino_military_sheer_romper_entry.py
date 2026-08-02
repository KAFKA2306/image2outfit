#!/usr/bin/env python3
"""Run the smooth military romper build with the tools directory importable."""
from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_military_sheer_romper_build as base  # noqa: E402

# Compatibility aliases keep the smooth geometry layer independent from helper renames.
base.box = base.cube
base.plain_material = base.simple_material

import siroino_military_sheer_romper_smooth as smooth  # noqa: E402

# The base v3 generator calls build_preview_body directly.
base.build_preview_body = smooth.build_preview_body


if __name__ == "__main__":
    raise SystemExit(base.main())
