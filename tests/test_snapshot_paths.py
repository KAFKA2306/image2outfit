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
    ROOT / "README.md",
    ROOT / "AGENTS.md",
    ROOT / "tools/audit_snapshot.py",
    ROOT / "tools/package_snapshot.py",
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

    def test_resumable_haolan_products_are_not_legacy_snapshots(self) -> None:
        legacy_haolan = CANONICAL_SNAPSHOT_ROOT / "haolan"
        residuals = sorted(
            path.relative_to(ROOT).as_posix()
            for path in legacy_haolan.rglob("*")
            if path.is_file() or path.is_symlink()
        ) if legacy_haolan.exists() else []
        self.assertEqual(
            [],
            residuals,
            f"Resumable HAOLAN files must use Assets/GenWorks/<slug>: {residuals}",
        )
        for slug in ("haolan-bordeaux-knit-set", "haolan-cow-hood-knit-set"):
            product_root = ROOT / "Assets" / "GenWorks" / slug
            self.assertTrue((product_root / "ProductManifest.json").is_file())
            self.assertTrue((product_root / "README.md").is_file())
            self.assertTrue((product_root / "Prefab").is_dir())

    def test_active_snapshot_paths_use_current_contract(self) -> None:
        forbidden_tokens = (
            "Assets/GenWorks/Legacy/Published",
            "Published/haolan/",
            "Assets/GenWorks/Legacy/Snapshots/haolan",
            "tools/audit_published.py",
            "tools/package_published.py",
            ".github/run/",
            ".github/status/",
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
            f"Deprecated snapshot or runtime paths remain: {violations}",
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
