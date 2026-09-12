from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import production_contract  # noqa: E402


class ReleaseManifestVerifierTest(unittest.TestCase):
    def _fixture(self, release: Path) -> tuple[dict, str]:
        payload = release / "Package/UnityAssets/demo.prefab"
        payload.parent.mkdir(parents=True)
        payload.write_bytes(b"prefab")
        candidate_hash = hashlib.sha256(b"candidate").hexdigest()
        manifest = {
            "schemaVersion": 2,
            "kind": "image2outfit-release",
            "jobId": "demo",
            "productName": "Demo",
            "adapterId": "demo-v1",
            "releasedAt": "2026-09-12T00:00:00+00:00",
            "sourceCommit": "abc",
            "candidateManifestSha256": candidate_hash,
            "files": [
                {
                    "path": "Package/UnityAssets/demo.prefab",
                    "bytes": payload.stat().st_size,
                    "sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
                }
            ],
            "evidence": {},
            "decision": "GO",
        }
        return manifest, candidate_hash

    def _write(self, release: Path, manifest: dict) -> None:
        (release / "release-manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )

    def _errors(self, release: Path, candidate_hash: str) -> list[str]:
        return production_contract.verify_release_package(
            root=ROOT,
            release=release,
            expected_job_id="demo",
            expected_adapter_id="demo-v1",
            expected_candidate_manifest_sha256=candidate_hash,
        )

    def test_valid_package_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary)
            manifest, candidate_hash = self._fixture(release)
            self._write(release, manifest)
            self.assertEqual([], self._errors(release, candidate_hash))

    def test_schema_identity_and_inventory_corruption_fail_closed(self) -> None:
        mutations = {
            "missing required field": lambda value: value.pop("decision"),
            "wrong schema": lambda value: value.__setitem__("schemaVersion", 3),
            "wrong kind": lambda value: value.__setitem__("kind", "other"),
            "wrong job": lambda value: value.__setitem__("jobId", "other"),
            "wrong adapter": lambda value: value.__setitem__("adapterId", "other"),
            "wrong candidate": lambda value: value.__setitem__(
                "candidateManifestSha256", "0" * 64
            ),
            "duplicate path": lambda value: value["files"].append(
                copy.deepcopy(value["files"][0])
            ),
            "wrong hash": lambda value: value["files"][0].__setitem__(
                "sha256", "0" * 64
            ),
            "wrong bytes": lambda value: value["files"][0].__setitem__("bytes", 99),
            "escape path": lambda value: value["files"][0].__setitem__(
                "path", "../escape"
            ),
            "absolute path": lambda value: value["files"][0].__setitem__(
                "path", "/tmp/escape"
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                release = Path(temporary)
                manifest, candidate_hash = self._fixture(release)
                mutate(manifest)
                self._write(release, manifest)
                self.assertTrue(self._errors(release, candidate_hash), name)

    def test_missing_listed_file_and_unlisted_file_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary)
            manifest, candidate_hash = self._fixture(release)
            self._write(release, manifest)
            (release / manifest["files"][0]["path"]).unlink()
            self.assertTrue(self._errors(release, candidate_hash))

        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary)
            manifest, candidate_hash = self._fixture(release)
            self._write(release, manifest)
            extra = release / "Package/unlisted.txt"
            extra.write_text("extra", encoding="utf-8")
            errors = self._errors(release, candidate_hash)
            self.assertTrue(
                any("omitted from manifest" in error for error in errors), errors
            )

    def test_exact_release_zip_is_an_explicit_inventory_exclusion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary)
            manifest, candidate_hash = self._fixture(release)
            self._write(release, manifest)
            (release / "demo.zip").write_bytes(b"archive")
            self.assertEqual([], self._errors(release, candidate_hash))


if __name__ == "__main__":
    unittest.main()
