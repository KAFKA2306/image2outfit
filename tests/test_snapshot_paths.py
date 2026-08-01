from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_SNAPSHOT_ROOT = ROOT / "Assets/GenWorks/Legacy/Snapshots"
DEPRECATED_TOOL_PATHS = (
    ROOT / "tools/audit_published.py",
    ROOT / "tools/package_published.py",
)
REQUIRED_TOOL_PATHS = (
    ROOT / "tools/audit_snapshot.py",
    ROOT / "tools/package_snapshot.py",
)
ACTIVE_PATH_FILES = (
    ROOT / "Taskfile.yml",
    ROOT / ".github/workflows/haolan-cow-hood.yml",
    ROOT / ".github/workflows/haolan-cow-hood-hosted.yml",
    ROOT / ".github/workflows/haolan-bordeaux-preview.yml",
    ROOT / ".github/run/genworks-migrate.txt",
)


class SnapshotPathPolicyTests(unittest.TestCase):
    def test_no_directory_is_named_published(self) -> None:
        existing = sorted(
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("*")
            if path.is_dir() and path.name.casefold() == "published"
        )
        self.assertEqual(
            [],
            existing,
            f"Deprecated snapshot directories exist: {existing}",
        )

    def test_legacy_snapshots_are_unity_visible(self) -> None:
        self.assertTrue(
            CANONICAL_SNAPSHOT_ROOT.is_dir(),
            f"Missing canonical snapshot root: {CANONICAL_SNAPSHOT_ROOT}",
        )
        self.assertTrue((CANONICAL_SNAPSHOT_ROOT / "LegacyManifest.json").is_file())

    def test_active_generation_paths_target_snapshots(self) -> None:
        forbidden_tokens = (
            "Assets/GenWorks/Legacy/Published",
            "Published/haolan/",
            "tools/audit_published.py",
            "tools/package_published.py",
        )
        violations: list[str] = []
        for path in ACTIVE_PATH_FILES:
            self.assertTrue(path.is_file(), f"Missing active path file: {path}")
            text = path.read_text(encoding="utf-8")
            for token in forbidden_tokens:
                if token in text:
                    violations.append(
                        f"{path.relative_to(ROOT).as_posix()}: {token}"
                    )
        self.assertEqual(
            [],
            violations,
            f"Deprecated snapshot paths remain: {violations}",
        )

    def test_snapshot_tools_use_current_names(self) -> None:
        stale = [
            path.relative_to(ROOT).as_posix()
            for path in DEPRECATED_TOOL_PATHS
            if path.exists()
        ]
        missing = [
            path.relative_to(ROOT).as_posix()
            for path in REQUIRED_TOOL_PATHS
            if not path.is_file()
        ]
        self.assertEqual([], stale, f"Deprecated snapshot tools remain: {stale}")
        self.assertEqual([], missing, f"Required snapshot tools are missing: {missing}")


if __name__ == "__main__":
    unittest.main()
