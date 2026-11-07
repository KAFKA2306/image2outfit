#!/usr/bin/env python3
from __future__ import annotations

import base64
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
payload = "".join((HERE / "haolan_cow_payload" / f"{index:02d}.txt").read_text(encoding="ascii").strip() for index in range(9))
source = zlib.decompress(base64.b85decode(payload)).decode("utf-8")
override_payload = (HERE / "haolan_cow_v12_overrides.b85").read_text(encoding="ascii").strip()
overrides = zlib.decompress(base64.b85decode(override_payload)).decode("utf-8")
source = source.replace("import zlib\n", "import zlib\nfrom datetime import datetime, timezone\n", 1)
source = source.replace("def main() -> int:", overrides + "\n\ndef main() -> int:", 1)
source = source.replace('"generatedAt": "2026-07-30T03:40:00Z",', '"generatedAt": datetime.now(timezone.utc).isoformat(),')
source = source.replace("HAOLAN Cow Hood Knit Set v1.0", "HAOLAN Cow Hood Knit Set v1.2")
source = source.replace("image2outfit HAOLAN cow hood knit set v1.0", "image2outfit HAOLAN cow hood knit set v1.2")
source = source.replace('abs_name = str(texture_paths[material]).replace("\\\\", "/")', "abs_name = rel")
exec(compile(source, str(Path(__file__).resolve()), "exec"))
