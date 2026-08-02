from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import runtime_paths  # noqa: E402


class RuntimePathsTest(unittest.TestCase):
    def test_product_runtime_is_derived_from_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = runtime_paths.for_product(root, "sample-outfit")
            expected = root.resolve() / ".image2outfit" / "products" / "sample-outfit"
            self.assertEqual(paths.root, expected)
            self.assertEqual(paths.reports, expected / "reports")
            self.assertEqual(paths.candidate, expected / "candidate")
            self.assertEqual(paths.release, expected / "release")

    def test_invalid_product_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                runtime_paths.for_product(Path(temporary), "../escape")

    def test_legacy_product_outputs_are_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for directory in runtime_paths.LEGACY_RUNTIME_ROOTS:
                source = root / directory / "sample-outfit"
                source.mkdir(parents=True)
                (source / "generated.txt").write_text("preserve", encoding="utf-8")

            migrated = runtime_paths.migrate_legacy_product_outputs(
                root, "sample-outfit"
            )
            self.assertEqual(
                migrated,
                [
                    "Artifacts/sample-outfit"
                    " -> .image2outfit/products/sample-outfit/reports",
                    "Candidates/sample-outfit"
                    " -> .image2outfit/products/sample-outfit/candidate",
                    "Release/sample-outfit"
                    " -> .image2outfit/products/sample-outfit/release",
                ],
            )
            paths = runtime_paths.for_product(root, "sample-outfit")
            for target in (paths.reports, paths.candidate, paths.release):
                self.assertEqual(
                    (target / "generated.txt").read_text(encoding="utf-8"),
                    "preserve",
                )
            for directory in runtime_paths.LEGACY_RUNTIME_ROOTS:
                self.assertFalse((root / directory).exists())

    def test_migration_rejects_ambiguous_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "Candidates" / "sample-outfit"
            source.mkdir(parents=True)
            target = runtime_paths.for_product(root, "sample-outfit").candidate
            target.mkdir(parents=True)
            with self.assertRaises(RuntimeError):
                runtime_paths.migrate_legacy_product_outputs(
                    root, "sample-outfit"
                )


if __name__ == "__main__":
    unittest.main()
