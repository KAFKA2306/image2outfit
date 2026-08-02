#!/usr/bin/env python3
"""Run the smooth military romper build with the tools directory importable."""
from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_military_sheer_romper_smooth as smooth  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(smooth.base.main())
