#!/usr/bin/env python3
"""Write deterministic SHA-256 inventory for a GenWorks product directory."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    output = root / "SOURCE_HASHES.txt"
    files = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and path != output
        and not path.name.endswith(".blend1")
        and "/Library/" not in path.as_posix()
    ]
    output.write_text(
        "\n".join(
            f"{sha256(path)}  {path.relative_to(root).as_posix()}"
            for path in sorted(files)
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(files)} hashes to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
