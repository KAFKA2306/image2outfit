from __future__ import annotations

import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from production_contract import package_release


class ReleaseReproducibilityTests(unittest.TestCase):
    def test_identical_candidate_bytes_produce_identical_release_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            candidate = root / "candidate"
            candidate.mkdir()
            source = candidate / "garment.txt"
            source.write_text("same immutable candidate\n", encoding="utf-8")

            job = {
                "id": "test-garment",
                "productName": "Test Garment",
                "adapterId": "test-adapter",
                "productRoot": "Assets/GenWorks/test-garment",
                "humanEvidence": {},
            }
            candidate_manifest = {"sourceCommit": "a" * 40}
            common = {
                "root": root,
                "job_path": root / "job.json",
                "job": job,
                "policy": {},
                "candidate": candidate,
                "candidate_manifest": candidate_manifest,
                "candidate_hash": "b" * 64,
                "human_evidence": {},
                "verify_candidate": lambda *_args: [],
            }

            first = package_release(
                **common,
                release=root / "release-one",
                now=lambda: "2026-09-12T00:00:00Z",
            )

            os.utime(source, (2_000_000_000, 2_000_000_000))
            second = package_release(
                **common,
                release=root / "release-two",
                now=lambda: "2030-01-01T00:00:00Z",
            )

            self.assertEqual(
                first["releaseManifestSha256"], second["releaseManifestSha256"]
            )
            self.assertEqual(first["zip"]["sha256"], second["zip"]["sha256"])
            self.assertEqual(first["zip"]["bytes"], second["zip"]["bytes"])

            first_archive = root / "release-one" / "test-garment.zip"
            second_archive = root / "release-two" / "test-garment.zip"
            self.assertEqual(first_archive.read_bytes(), second_archive.read_bytes())

            with zipfile.ZipFile(first_archive) as archive:
                infos = archive.infolist()
                names = [info.filename for info in infos]
                self.assertEqual(names, sorted(names))
                self.assertNotIn("release-audit.json", names)
                for info in infos:
                    self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                    self.assertEqual(info.create_system, 3)
                    self.assertEqual((info.external_attr >> 16) & 0xFFFF, 0o100644)

            self.assertNotEqual(
                (root / "release-one" / "release-audit.json").read_text(),
                (root / "release-two" / "release-audit.json").read_text(),
            )


if __name__ == "__main__":
    unittest.main()
