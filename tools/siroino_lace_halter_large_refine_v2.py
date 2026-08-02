#!/usr/bin/env python3
"""Load the explicit panel-and-seam Siroino lace-halter rebuild."""
from __future__ import annotations

import base64
import sys
import zlib
from pathlib import Path

# Keep the shared review implementation statically visible to ownership audits,
# and make Blender's direct --python execution resolve sibling tool modules.
tool_root = Path(__file__).resolve().parent
if str(tool_root) not in sys.path:
    sys.path.insert(0, str(tool_root))
import siroino_lace_halter_large_refine_and_review as _review_base  # noqa: E402,F401

source_root = tool_root / "product_sources" / "siroino_lace_halter_large_panel"
parts = sorted(source_root.glob("part-*.b85"))
if not parts:
    raise FileNotFoundError(f"missing panel rebuild source: {source_root}")
payload = "".join(path.read_text(encoding="ascii").strip() for path in parts)
source = zlib.decompress(base64.b85decode(payload.encode("ascii"))).decode("utf-8")
exec(compile(source, __file__, "exec"), globals(), globals())
