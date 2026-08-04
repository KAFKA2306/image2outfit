from __future__ import annotations

import json
from pathlib import Path

from tools.review_console_ui import build


def test_public_review_console_keeps_unique_product_landmarks(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    output = root / ".image2outfit" / "review-console"
    (root / "config").mkdir(parents=True)
    (root / "config" / "release-policy.json").write_text(
        json.dumps({"required_views": ["front"], "required_poses": []}),
        encoding="utf-8",
    )
    workspace = root / "Assets" / "GenWorks" / "demo"
    workspace.mkdir(parents=True)
    (workspace / "ProductManifest.json").write_text(
        json.dumps({"state": "WORKING", "resume_point": "build"}),
        encoding="utf-8",
    )

    build(root, output)
    html = (output / "index.html").read_text(encoding="utf-8")

    assert html.count('id="product-list"') == 1
    assert html.count('id="products"') == 1
    assert '<section class="product-list" id="product-list">' in html
    assert '<div class="product-buttons" id="products">' in html
    assert "document.querySelector" in html
    assert "READ ONLY · RELEASE EVIDENCE" in html
