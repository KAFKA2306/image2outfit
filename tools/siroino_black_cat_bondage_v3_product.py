#!/usr/bin/env python3
"""Final corrective wrapper for black cat gauntlet strap placement."""

from __future__ import annotations

import siroino_black_cat_bondage_v2_product as v2

_ORIGINAL = v2.apply_shape_corrections


def corrected_shape(objects):
    _ORIGINAL(objects)
    strap_x = (0.375, 0.435, 0.495, 0.555)
    for obj in objects:
        if not obj.name.startswith("Gauntlet_Strap_"):
            continue
        side = -1.0 if "_L_" in obj.name else 1.0
        index = int(obj.name.rsplit("_", 1)[-1])
        obj.location = (side * strap_x[index], -0.004, 0.995)


v2.apply_shape_corrections = corrected_shape


if __name__ == "__main__":
    raise SystemExit(v2.main())
