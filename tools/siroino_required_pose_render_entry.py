#!/usr/bin/env python3
"""Hosted pose entrypoint with render-evidence metadata enabled."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import render_evidence_bootstrap  # noqa: F401,E402
import siroino_required_pose_render as poses  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(poses.main())
