import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools" / "reconcile_publication.py"
spec = importlib.util.spec_from_file_location("reconcile_publication", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


def product(
    root: Path, slug: str, rendered: bool, preview_name: str = "front.png"
) -> None:
    workspace = root / "Assets" / "GenWorks" / slug
    workspace.mkdir(parents=True)
    (workspace / "ProductManifest.json").write_text("{}", encoding="utf-8")
    if rendered:
        previews = workspace / "Previews"
        previews.mkdir()
        (previews / preview_name).write_bytes(b"real-render")


class PublicationReconciliationTests(unittest.TestCase):
    def test_reconciliation_exposes_silent_omission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            product(root, "public", True)
            product(root, "omitted", True)
            product(root, "no-render", False)
            console = root / "review-console.json"
            console.write_text(
                json.dumps({"products": [{"slug": "public"}]}), encoding="utf-8"
            )

            result = module.reconcile(root, console)

            self.assertEqual(result["canonicalProductCount"], 3)
            self.assertEqual(result["productsWithRealRender"], 2)
            self.assertEqual(result["publicProductCount"], 1)
            self.assertEqual(result["missingProjection"], ["omitted"])
            self.assertEqual(result["missingPrimaryRender"], ["no-render"])
            self.assertEqual(result["silentOmissionCount"], 1)
            self.assertEqual(
                result["classification"],
                {"no-render": "C", "omitted": "B", "public": "A"},
            )

    def test_non_primary_preview_does_not_count_as_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            product(root, "pattern-only", True, "pattern-layout.png")
            console = root / "review-console.json"
            console.write_text(
                json.dumps({"products": [{"slug": "pattern-only"}]}), encoding="utf-8"
            )

            result = module.reconcile(root, console)

            self.assertEqual(result["productsWithRealRender"], 0)
            self.assertEqual(result["publicProductCount"], 0)
            self.assertEqual(result["missingPrimaryRender"], ["pattern-only"])
            self.assertEqual(result["classification"], {"pattern-only": "C"})


if __name__ == "__main__":
    unittest.main()
