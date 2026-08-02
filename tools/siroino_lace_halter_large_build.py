#!/usr/bin/env python3
"""Load the tracked product-specific Siroino lace builder source."""
from __future__ import annotations
import base64, zlib
from pathlib import Path
payload = Path(__file__).with_name('product_sources').joinpath('siroino_lace_halter_large.b85').read_text(encoding='ascii')
source = zlib.decompress(base64.b85decode(payload.encode('ascii'))).decode('utf-8')
exec(compile(source, __file__, 'exec'), globals(), globals())
