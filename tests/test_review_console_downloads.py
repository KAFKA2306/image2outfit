"""Behavioral regression: image downloads do not depend on file timestamps."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import review_console  # noqa: E402


class TestImageDownloadReproducibility(unittest.TestCase):
    def test_same_image_bytes_produce_same_archive_after_mtime_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "Assets" / "GenWorks" / "example"
            preview = workspace / "Previews" / "front.png"
            preview.parent.mkdir(parents=True)
            preview.write_bytes(b"fixed image bytes for archive regression")
            output_dir = root / "pages"
            output_dir.mkdir()
            asset = review_console.Asset(
                kind="front",
                name="front.png",
                status="PASS",
                href=review_console.relative_href(preview, output_dir),
                sha256=review_console.digest(preview),
            )

            first = review_console.collect_downloads(
                root, workspace, output_dir, {}, [asset]
            )
            archive = output_dir / first[0]["href"]
            first_bytes = archive.read_bytes()
            os.utime(preview, (1_500_000_000, 1_500_000_000))
            second = review_console.collect_downloads(
                root, workspace, output_dir, {}, [asset]
            )
            self.assertEqual(first, second)
            self.assertEqual(first_bytes, archive.read_bytes())

            with zipfile.ZipFile(archive) as bundle:
                self.assertEqual(
                    bundle.read("00-front-front.png"),
                    preview.read_bytes(),
                )
                for member in bundle.infolist():
                    self.assertEqual(
                        member.date_time, review_console.CANONICAL_ZIP_TIMESTAMP
                    )


if __name__ == "__main__":
    unittest.main()
