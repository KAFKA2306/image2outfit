#!/usr/bin/env python3
"""Stable entrypoint for the v24 pattern-coordinate bodysuit reconstruction."""

from __future__ import annotations

import siroino_heather_hooded_product as product
import siroino_heather_pattern_coordinate_v24 as v24

v24.install(product.pattern)
product.DESIGN_REVISION = product.pattern.DESIGN_REVISION
product.build.DESIGN_REVISION = product.DESIGN_REVISION


def main() -> int:
    return product.main()


if __name__ == "__main__":
    raise SystemExit(main())
