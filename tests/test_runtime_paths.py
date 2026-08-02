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

    def test_legacy_product_outputs_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for directory in runtime_paths.LEGACY_RUNTIME_ROOTS:
                target = root / directory / "sample-outfit"
                target.mkdir(parents=True)
                (target / "generated.txt").write_text("obsolete", encoding="utf-8")
            removed = runtime_paths.remove_legacy_product_outputs(
                root, "sample-outfit"
            )
            self.assertEqual(
                removed,
                [
                    "Artifacts/sample-outfit",
                    "Candidates/sample-outfit",
                    "Release/sample-outfit",
                ],
            )
            for directory in runtime_paths.LEGACY_RUNTIME_ROOTS:
                self.assertFalse((root / directory).exists())


if __name__ == "__main__":
    unittest.main()
