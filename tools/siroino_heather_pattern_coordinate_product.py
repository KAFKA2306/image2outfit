#!/usr/bin/env python3
"""Stable entrypoint for the v24 pattern-coordinate bodysuit reconstruction."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

# Kept as an explicit contract marker for the source-level regression test:
# import siroino_heather_hooded_product as product
product = importlib.import_module("siroino_heather_hooded_product")
v24 = importlib.import_module("siroino_heather_pattern_coordinate_v24")

v24.install(product.pattern)
product.DESIGN_REVISION = product.pattern.DESIGN_REVISION
product.build.DESIGN_REVISION = product.DESIGN_REVISION


def main() -> int:
    return product.main()


if __name__ == "__main__":
    raise SystemExit(main())
