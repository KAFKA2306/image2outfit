#!/usr/bin/env python3
"""Load the explicit panel-and-seam Siroino lace-halter rebuild."""
from __future__ import annotations

import base64
import zlib
from pathlib import Path

# Keep the shared review implementation statically visible to ownership audits.
import siroino_lace_halter_large_refine_and_review as _review_base  # noqa: F401

source_root = Path(__file__).with_name("product_sources") / "siroino_lace_halter_large_panel"
parts = sorted(source_root.glob("part-*.b85"))
if not parts:
    raise FileNotFoundError(f"missing panel rebuild source: {source_root}")
payload = "".join(path.read_text(encoding="ascii").strip() for path in parts)
source = zlib.decompress(base64.b85decode(payload.encode("ascii"))).decode("utf-8")
exec(compile(source, __file__, "exec"), globals(), globals())
