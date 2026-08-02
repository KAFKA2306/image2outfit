from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEGACY_ROOT = ROOT / "Assets" / "GenWorks" / "Legacy"
ACTIVE_CONTRACT_FILES = (
    ROOT / "README.md",
    ROOT / "AGENTS.md",
    ROOT / "Taskfile.yml",
    ROOT / "Assets" / "GenWorks" / "OutfitCatalog.json",
    ROOT
    / "Assets"
    / "GenWorks"
    / "Shared"
    / "Editor"
    / "GeneratedOutfitPrefabConfigurator.cs",
)
REMOVED_SNAPSHOT_TOOLS = (
    ROOT / "tools" / "audit_snapshot.py",
    ROOT / "tools" / "package_snapshot.py",
)


class CanonicalPathPolicyTests(unittest.TestCase):
    def test_no_directory_is_named_published(self) -> None:
        existing = sorted(
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("*")
            if path.is_dir() and path.name.casefold() == "published"
        )
        self.assertEqual(
            [],
            existing,
            f"Deprecated Published directories exist: {existing}",
        )

    def test_genworks_legacy_root_is_absent(self) -> None:
        self.assertFalse(
            LEGACY_ROOT.exists(),
            "Assets/GenWorks/Legacy is forbidden; move resumable evidence into the product workspace",
        )

    def test_layout_contract_forbids_genworks_legacy(self) -> None:
        config = json.loads(
            (ROOT / "config" / "genworks-layout.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("legacyRoot", config)
        self.assertIn(
            "Assets/GenWorks/Legacy",
            config["forbiddenAssetRoots"],
        )

    def test_resumable_haolan_products_use_canonical_roots(self) -> None:
        for slug in ("haolan-bordeaux-knit-set", "haolan-cow-hood-knit-set"):
            product_root = ROOT / "Assets" / "GenWorks" / slug
            self.assertTrue((product_root / "ProductManifest.json").is_file())
            self.assertTrue((product_root / "README.md").is_file())
            self.assertTrue((product_root / "Prefab").is_dir())

    def test_snapshot_entrypoints_and_contracts_are_removed(self) -> None:
        stale_tools = [
            path.relative_to(ROOT).as_posix()
            for path in REMOVED_SNAPSHOT_TOOLS
            if path.exists()
        ]
        self.assertEqual([], stale_tools, f"Snapshot-only tools remain: {stale_tools}")

        forbidden_tokens = (
            "Legacy/Snapshots",
            "legacySnapshots",
            "legacySnapshotCount",
            "audit:snapshot",
            "package:snapshot",
            "LegacyRoot",
            "tools/audit_snapshot.py",
            "tools/package_snapshot.py",
        )
        violations: list[str] = []
        for path in ACTIVE_CONTRACT_FILES:
            self.assertTrue(path.is_file(), f"Missing contract file: {path}")
            text = path.read_text(encoding="utf-8")
            for token in forbidden_tokens:
                if token in text:
                    violations.append(
                        f"{path.relative_to(ROOT).as_posix()}: {token}"
                    )
        self.assertEqual(
            [],
            violations,
            f"Removed snapshot contracts remain: {violations}",
        )


if __name__ == "__main__":
    unittest.main()
