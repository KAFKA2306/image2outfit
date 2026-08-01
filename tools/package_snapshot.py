from __future__ import annotations

import argparse
import hashlib
import zipfile
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def candidate_files(root: Path, archive_name: str) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.name not in {"SOURCE_HASHES.txt", archive_name}
    )


def write_archive(root: Path, archive: Path, source_files: list[Path]) -> None:
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as handle:
        for path in source_files:
            info = zipfile.ZipInfo(
                path.relative_to(root).as_posix(), (1980, 1, 1, 0, 0, 0)
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0o100644 << 16
            handle.writestr(info, path.read_bytes())


def write_manifest(root: Path) -> None:
    manifest = root / "SOURCE_HASHES.txt"
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "SOURCE_HASHES.txt":
            entries.append(f"{sha256(path)}  {path.relative_to(root).as_posix()}")
    manifest.write_text("\n".join(entries) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--archive", default="HAOLAN_CowHoodKnitSet_v1.zip")
    options = parser.parse_args()
    root = Path(options.root).resolve()
    archive = root / options.archive
    source_files = candidate_files(root, options.archive)
    archive.unlink(missing_ok=True)
    (root / "SOURCE_HASHES.txt").unlink(missing_ok=True)
    write_archive(root, archive, source_files)
    write_manifest(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
