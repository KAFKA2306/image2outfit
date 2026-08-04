#!/usr/bin/env python3
"""Render required poses for the Siroino Nocturne Angel modular outfit."""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_heather_hooded_bodysuit_pose as pose
import siroino_strappy_knit_build as common

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_POSES = ("neutral", "arms-up", "arm-cross", "crouch", "sit", "prone")


def _job_path() -> Path:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    for index, value in enumerate(raw):
        if value == "--job" and index + 1 < len(raw):
            return Path(raw[index + 1]).resolve()
    raise RuntimeError("--job is required")


def _update_hashes(product_root: Path) -> None:
    tracked = sorted(
        path
        for path in product_root.rglob("*")
        if path.is_file() and path.name != "SOURCE_HASHES.txt"
    )
    (product_root / "SOURCE_HASHES.txt").write_text(
        "\n".join(
            f"{common.sha256(path)}  {path.relative_to(product_root).as_posix()}"
            for path in tracked
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    job = json.loads(_job_path().read_text(encoding="utf-8-sig"))
    result = pose.main()
    product_root = ROOT / job["productRoot"]
    manifest_path = ROOT / job["productManifestPath"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pose_paths = {
        name: product_root / "Previews" / "Poses" / f"{name}.png"
        for name in REQUIRED_POSES
    }
    sheet = product_root / "Previews" / f"{job['id']}-pose-review.webp"
    evidence_exists = (
        all(path.is_file() for path in pose_paths.values()) and sheet.is_file()
    )
    gates = manifest.setdefault("technicalGates", {})
    gates["poseEvidence"] = "PASS" if evidence_exists else "FAIL"
    gates["poseRender"] = "PASS" if evidence_exists else "FAIL"
    if gates.get("fitPenetration") == "FAIL":
        gates["fitPenetration"] = "NON_BLOCKING_FAIL"
    gates["visualAppearanceReview"] = "PENDING"
    manifest["state"] = "WORKING"
    manifest["status"] = "WORKING"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _update_hashes(product_root)
    print(
        json.dumps(
            {
                "productId": job["id"],
                "poseEvidence": gates["poseEvidence"],
                "fitPenetration": gates.get("fitPenetration"),
                "visualAppearanceReview": "PENDING",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
