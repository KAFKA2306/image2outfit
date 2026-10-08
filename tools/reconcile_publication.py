#!/usr/bin/env python3
"""Reconcile canonical products against review-console.v2 publication projection."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

IMAGE_SUFFIXES = {".png", ".webp", ".jpg", ".jpeg"}
PRIMARY_VIEW_STEMS = {"front", "primary"}


def real_render_exists(workspace: Path) -> bool:
    """Return true only when a canonical primary garment view exists."""
    for root in (workspace / "Previews", workspace / "Evidence" / "Rejected"):
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if (
                path.is_file()
                and path.suffix.lower() in IMAGE_SUFFIXES
                and path.stem.lower() in PRIMARY_VIEW_STEMS
            ):
                return True
    return False


def reconcile(root: Path, console_path: Path) -> dict:
    product_root = root / "Assets" / "GenWorks"
    canonical = (
        {
            p.name: p
            for p in product_root.iterdir()
            if p.is_dir() and (p / "ProductManifest.json").is_file()
        }
        if product_root.is_dir()
        else {}
    )
    console = (
        json.loads(console_path.read_text(encoding="utf-8"))
        if console_path.is_file()
        else {"products": []}
    )
    projected = {
        str(row.get("slug"))
        for row in console.get("products", [])
        if isinstance(row, dict) and row.get("slug")
    }
    rendered = {
        slug for slug, workspace in canonical.items() if real_render_exists(workspace)
    }
    missing_projection = sorted(rendered - projected)
    missing_primary_render = sorted(set(canonical) - rendered)
    broken_public = sorted(projected - set(canonical))
    classification = {
        slug: (
            "A"
            if slug in projected and slug in rendered
            else "B"
            if slug in rendered
            else "C"
        )
        for slug in sorted(canonical)
    }
    classification_counts = Counter(classification.values())
    return {
        "schemaVersion": "publication-reconciliation.v1",
        "canonicalProductCount": len(canonical),
        "productsWithRealRender": len(rendered),
        "projectedProductCount": len(projected & set(canonical)),
        "publicProductCount": len(projected & rendered),
        "missingPrimaryRender": missing_primary_render,
        "missingProjection": missing_projection,
        "brokenPublicProducts": broken_public,
        "silentOmissionCount": len(missing_projection),
        "classificationCounts": {
            "A": classification_counts.get("A", 0),
            "B": classification_counts.get("B", 0),
            "C": classification_counts.get("C", 0),
        },
        "classification": classification,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--console",
        type=Path,
        default=Path(".image2outfit/review-console/review-console.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".image2outfit/review-console/publication-reconciliation.json"),
    )
    args = parser.parse_args()
    root = args.root.resolve()
    console = args.console if args.console.is_absolute() else root / args.console
    output = args.output if args.output.is_absolute() else root / args.output
    result = reconcile(root, console)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result["silentOmissionCount"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
