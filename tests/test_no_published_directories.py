from __future__ import annotations

import unittest
from pathlib import Path


FORBIDDEN_DIRECTORIES = (
    Path("Published"),
    Path("Assets/GenWorks/Legacy/Published"),
)

ACTIVE_PATH_FILES = (
    Path("Taskfile.yml"),
    Path(".github/workflows/haolan-cow-hood.yml"),
    Path(".github/workflows/haolan-cow-hood-hosted.yml"),
    Path(".github/workflows/haolan-bordeaux-preview.yml"),
    Path(".github/run/genworks-migrate.txt"),
)


class PublishedDirectoryPolicyTests(unittest.TestCase):
    def test_deprecated_published_directories_do_not_exist(self) -> None:
        existing = [path.as_posix() for path in FORBIDDEN_DIRECTORIES if path.exists()]
        self.assertEqual([], existing, f"Deprecated Published directories exist: {existing}")

    def test_legacy_snapshots_are_unity_visible(self) -> None:
        canonical = Path("Assets/GenWorks/Legacy/Snapshots")
        self.assertTrue(canonical.is_dir(), f"Missing canonical snapshot root: {canonical}")
        self.assertTrue((canonical / "LegacyManifest.json").is_file())

    def test_active_generation_paths_do_not_target_deprecated_roots(self) -> None:
        forbidden_tokens = (
            "Assets/GenWorks/Legacy/Published",
            "Published/haolan/",
        )
        violations: list[str] = []
        for path in ACTIVE_PATH_FILES:
            self.assertTrue(path.is_file(), f"Missing active path file: {path}")
            text = path.read_text(encoding="utf-8")
            for token in forbidden_tokens:
                if token in text:
                    violations.append(f"{path.as_posix()}: {token}")
        self.assertEqual([], violations, f"Deprecated output paths remain: {violations}")


if __name__ == "__main__":
    unittest.main()
