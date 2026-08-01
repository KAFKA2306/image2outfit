#!/usr/bin/env python3
"""Portable Blender entry point for required pose rendering."""
from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_required_pose_render as renderer

if __name__ == "__main__":
    raise SystemExit(renderer.main())
