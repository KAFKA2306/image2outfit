#!/usr/bin/env python3
"""Canonical stable entrypoint for the SiroinoSotai_PC blue happi build."""

from __future__ import annotations

import sys
from pathlib import Path

# Blender executes a --python file with the script directory available only
# inconsistently across launch modes.  Keep the canonical product entrypoint
# self-contained so the configured job can be run directly as well as through
# the managed pipeline.
_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from siroino_blue_happi_v2_build import main

# Product jobs bind only to this unversioned entrypoint; visual iterations and
# their committed render evidence remain auditable without changing job paths.


if __name__ == "__main__":
    raise SystemExit(main())
