from __future__ import annotations

import json
from pathlib import Path

from tools.review_console import build


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_review_console_builds_product_state_and_evidence(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    output = root / ".image2outfit" / "review-console"
    write_json(
        root / "config" / "release-policy.json",
        {"required_views": ["front", "back"], "required_poses": ["arms-up"]},
    )
    product = root / "Assets" / "GenWorks" / "demo"
    write_json(
        product / "ProductManifest.json",
        {
            "state": "HUMAN_REVIEW_PENDING",
            "updated_at": "2026-08-04T00:00:00Z",
            "resume_point": "human review",
            "candidate_hash": "abc123",
            "blockers": [{"severity": "major", "message": "back clipping", "status": "open"}],
            "gates": {
                "fit": {"status": "PASS"},
                "runtime": {"status": "FAIL", "message": "missing screenshot"},
            },
            "evidence": [{"label": "review", "path": "Evidence/review.json", "status": "PASS"}],
        },
    )
    (product / "Previews").mkdir(parents=True)
    (product / "Previews" / "front.png").write_bytes(b"front")
    (product / "Evidence").mkdir()
    (product / "Evidence" / "review.json").write_text("{}", encoding="utf-8")

    data = build(root, output)

    assert data["schema_version"] == "review-console.v1"
    assert data["required_views"] == ["front", "back"]
    assert data["required_poses"] == ["arms-up"]
    assert len(data["products"]) == 1
    record = data["products"][0]
    assert record["slug"] == "demo"
    assert record["state"] == "HUMAN_REVIEW_PENDING"
    assert record["blocker_count"] == 1
    assert record["resume_point"] == "human review"
    assert [asset["status"] for asset in record["assets"]] == ["PASS", "MISSING", "MISSING"]
    assert record["assets"][0]["sha256"]
    assert record["gates"][1]["status"] == "FAIL"
    assert record["evidence"][0]["href"]

    html = (output / "index.html").read_text(encoding="utf-8")
    for marker in (
        "READ ONLY · RELEASE EVIDENCE",
        "未解決blocker",
        "必須ビュー・ポーズ",
        "release gate",
        "window.REVIEW_CONSOLE_DATA",
        "ArrowLeft",
        "ArrowRight",
        "Escape",
        "min-height:44px",
        "prefers-reduced-motion",
    ):
        assert marker in html


def test_review_console_does_not_execute_product_commands(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    output = root / ".image2outfit" / "review-console"
    write_json(root / "config" / "release-policy.json", {})
    data = build(root, output)
    html = (output / "index.html").read_text(encoding="utf-8")

    assert data["products"] == []
    assert "subprocess" not in html
    assert "fetch(" not in html
    assert "release操作は既存gateを使用" in html
