#!/usr/bin/env python3
"""Derive each product's main flow as a star schema plus a triplet graph.

The model is derived from canonical product sources and written next to them as
``config/products/<slug>/flow-model.json``. Facts reference dimensions by id, and
every triple is traceable to the fact or pipeline stage that produced it.
Usage:
    python tools/product_flow_model.py --write [PRODUCT ...]
    python tools/product_flow_model.py --check [PRODUCT ...]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.pipeline import PIPELINE_STAGES  # noqa: E402

SCHEMA_VERSION = 1
MODEL_NAME = "star-schema-triplet-graph"
MODEL_FILE = "flow-model.json"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _product_ids() -> list[str]:
    products = ROOT / "config" / "products"
    return sorted(
        path.name
        for path in products.iterdir()
        if path.is_dir() and (path / "job.json").is_file()
    )


def _split_endpoint(value: str) -> tuple[str, str | None]:
    piece, _, edge = value.partition(".")
    return piece, edge or None


def _stitch_rows(stitch_graph: dict[str, Any]) -> list[dict[str, Any]]:
    # Products record seams as `stitches` (lilac, blue-happi, lily) or as `edges`
    # with a `seam` label (sage-breeze). Both reduce to the same triple.
    rows = list(stitch_graph.get("stitches", []))
    for edge in stitch_graph.get("edges", []):
        rows.append(
            {"id": edge.get("seam"), "from": edge.get("from"), "to": edge.get("to")}
        )
    return rows


def _normalize_stitch(raw: dict[str, Any], index: int) -> dict[str, Any] | None:
    stitch_id = str(raw.get("stitchId") or raw.get("id") or f"stitch-{index}")
    if isinstance(raw.get("first"), dict) and isinstance(raw.get("second"), dict):
        first_piece, first_edge = (
            raw["first"].get("pieceId"),
            raw["first"].get("edgeId"),
        )
        second_piece, second_edge = (
            raw["second"].get("pieceId"),
            raw["second"].get("edgeId"),
        )
        if not first_piece or not second_piece:
            return None
    elif isinstance(raw.get("a"), str) and isinstance(raw.get("b"), str):
        first_piece, first_edge = _split_endpoint(raw["a"])
        second_piece, second_edge = _split_endpoint(raw["b"])
    elif isinstance(raw.get("from"), str) and isinstance(raw.get("to"), str):
        first_piece, first_edge = _split_endpoint(raw["from"])
        second_piece, second_edge = _split_endpoint(raw["to"])
    else:
        return None
    return {
        "stitchId": stitch_id,
        "firstPieceId": first_piece,
        "firstEdgeId": first_edge,
        "secondPieceId": second_piece,
        "secondEdgeId": second_edge,
        "type": str(raw.get("type") or "unspecified"),
    }


def build_model(product_id: str, root: Path = ROOT) -> dict[str, Any]:
    product_dir = root / "config" / "products" / product_id
    stitch_path = product_dir / "stitch-graph.json"
    overlay_path = product_dir / "surface-attachment-graph.json"

    stage_ids = [stage.value for stage in PIPELINE_STAGES]
    dim_stage = [{"id": stage, "order": index} for index, stage in enumerate(stage_ids)]
    fact_stage_run = [
        {"productId": product_id, "stageId": stage, "order": index}
        for index, stage in enumerate(stage_ids)
    ]
    triples: list[dict[str, str]] = [
        {
            "subject": f"stage:{previous}",
            "predicate": "precedes",
            "object": f"stage:{following}",
            "evidence": "pipeline.PIPELINE_STAGES",
        }
        for previous, following in zip(stage_ids, stage_ids[1:], strict=False)
    ]

    pieces: set[str] = set()
    fact_stitch: list[dict[str, Any]] = []
    unresolved: list[Any] = []
    if stitch_path.is_file():
        stitch_graph = _read_json(stitch_path)
        unresolved = list(stitch_graph.get("unresolved", []))
        for index, raw in enumerate(_stitch_rows(stitch_graph)):
            stitch = _normalize_stitch(raw, index)
            if stitch is None:
                unresolved.append(
                    {"item": f"stitch row {index}", "status": "unrecognized-shape"}
                )
                continue
            pieces.update({stitch["firstPieceId"], stitch["secondPieceId"]})
            fact_stitch.append(stitch)
            triples.append(
                {
                    "subject": f"piece:{stitch['firstPieceId']}",
                    "predicate": "stitchedTo",
                    "object": f"piece:{stitch['secondPieceId']}",
                    "evidence": f"stitch:{stitch['stitchId']}",
                }
            )

    fact_overlay: list[dict[str, Any]] = []
    if overlay_path.is_file():
        surface_graph = _read_json(overlay_path)
        for overlay in surface_graph.get("overlays", []):
            pieces.update({overlay["hostPieceId"], overlay["overlayPieceId"]})
            fact_overlay.append(
                {
                    "overlayId": overlay["overlayId"],
                    "hostPieceId": overlay["hostPieceId"],
                    "overlayPieceId": overlay["overlayPieceId"],
                    "side": overlay["side"],
                    "mirrorGroupId": overlay["mirrorGroupId"],
                    "attachmentHypothesis": overlay["attachmentHypothesis"],
                }
            )
            triples.append(
                {
                    "subject": f"piece:{overlay['overlayPieceId']}",
                    "predicate": "attachedTo",
                    "object": f"piece:{overlay['hostPieceId']}",
                    "evidence": f"overlay:{overlay['overlayId']}",
                }
            )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "productId": product_id,
        "model": MODEL_NAME,
        "mainFlow": {
            "hub": f"product:{product_id}",
            "stageOrder": stage_ids,
            "stageSource": "src/image2outfit/pipeline.py PIPELINE_STAGES",
        },
        "dimensions": {
            "stage": dim_stage,
            "piece": [{"id": piece} for piece in sorted(pieces)],
        },
        "facts": {
            "stageRun": fact_stage_run,
            "stitch": fact_stitch,
            "overlayAttachment": fact_overlay,
        },
        "unresolved": unresolved,
        "triples": triples,
    }


def validate_model(model: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    stages = {row["id"] for row in model["dimensions"]["stage"]}
    pieces = {row["id"] for row in model["dimensions"]["piece"]}
    for row in model["facts"]["stageRun"]:
        if row["stageId"] not in stages:
            errors.append(f"stageRun references unknown stage {row['stageId']}")
    for row in model["facts"]["stitch"]:
        for key in ("firstPieceId", "secondPieceId"):
            if row[key] not in pieces:
                errors.append(
                    f"stitch {row['stitchId']} references unknown piece {row[key]}"
                )
    for row in model["facts"]["overlayAttachment"]:
        for key in ("hostPieceId", "overlayPieceId"):
            if row[key] not in pieces:
                errors.append(
                    f"overlay {row['overlayId']} references unknown piece {row[key]}"
                )
    for triple in model["triples"]:
        if not triple.get("evidence"):
            errors.append(
                f"triple {triple['subject']} {triple['predicate']} has no evidence"
            )
    return errors


def check_product(product_id: str, root: Path = ROOT) -> list[str]:
    stored_path = root / "config" / "products" / product_id / MODEL_FILE
    expected = build_model(product_id, root)
    errors = validate_model(expected)
    if not stored_path.is_file():
        errors.append(f"{product_id}: {MODEL_FILE} is missing")
        return errors
    if _read_json(stored_path) != expected:
        errors.append(f"{product_id}: {MODEL_FILE} is stale; run --write")
    return errors


def write_product(product_id: str, root: Path = ROOT) -> Path:
    model = build_model(product_id, root)
    errors = validate_model(model)
    if errors:
        raise ValueError(f"{product_id}: " + "; ".join(errors))
    path = root / "config" / "products" / product_id / MODEL_FILE
    path.write_text(
        json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("products", nargs="*")
    args = parser.parse_args(argv)
    product_ids = args.products or _product_ids()
    if args.write:
        for product_id in product_ids:
            print(write_product(product_id))
        return 0
    errors = [
        error for product_id in product_ids for error in check_product(product_id)
    ]
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
