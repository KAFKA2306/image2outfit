import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools" / "reconcile_publication.py"
spec = importlib.util.spec_from_file_location("reconcile_publication", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(module)


def product(root: Path, slug: str, rendered: bool) -> None:
    workspace = root / "Assets" / "GenWorks" / slug
    workspace.mkdir(parents=True)
    (workspace / "ProductManifest.json").write_text("{}", encoding="utf-8")
    if rendered:
        previews = workspace / "Previews"
        previews.mkdir()
        (previews / "front.png").write_bytes(b"real-render")


def test_reconciliation_exposes_silent_omission(tmp_path: Path) -> None:
    product(tmp_path, "public", True)
    product(tmp_path, "omitted", True)
    product(tmp_path, "no-render", False)
    console = tmp_path / "review-console.json"
    console.write_text(json.dumps({"products": [{"slug": "public"}]}), encoding="utf-8")

    result = module.reconcile(tmp_path, console)

    assert result["canonicalProductCount"] == 3
    assert result["productsWithRealRender"] == 2
    assert result["publicProductCount"] == 1
    assert result["missingProjection"] == ["omitted"]
    assert result["missingPrimaryRender"] == ["no-render"]
    assert result["silentOmissionCount"] == 1
    assert result["classification"] == {"no-render": "C", "omitted": "B", "public": "A"}
