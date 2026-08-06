#!/usr/bin/env python3
"""Product-specific stage adapter for the private-reference blue happi."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

import run_reference_product_stage as common


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=common.STAGES, required=True)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    return parser.parse_args()


def read_product_document(
    job: dict[str, Any], key: str, label: str
) -> tuple[Path, dict[str, Any]]:
    path = common.repo_path(job["garmentPipeline"][key], label=label)
    payload = common.read_object(path, label)
    if payload.get("schemaVersion") != 1 or payload.get("productId") != job["id"]:
        raise ValueError(f"{label} schema or product identity mismatch")
    return path, payload


def stage_normalize(job: dict[str, Any], result: Path) -> None:
    product_id = str(job["id"])
    audit_path, audit = read_product_document(
        job, "referenceAuditPath", "reference audit"
    )
    schematic_path, schematic = read_product_document(
        job, "normalizationSchematicPath", "normalization schematic"
    )
    canvas_spec = schematic["canvas"]
    canvas = Image.new(
        "RGB",
        (int(canvas_spec["width"]), int(canvas_spec["height"])),
        tuple(canvas_spec["background"]),
    )
    draw = ImageDraw.Draw(canvas)
    for primitive in schematic["primitives"]:
        kind = primitive["type"]
        fill = tuple(primitive["fill"])
        width = int(primitive.get("width", 1))
        if kind == "polygon":
            draw.polygon(
                [tuple(point) for point in primitive["points"]],
                fill=fill,
                outline=tuple(primitive.get("outline", primitive["fill"])),
                width=width,
            )
        elif kind == "line":
            draw.line(
                [tuple(point) for point in primitive["points"]],
                fill=fill,
                width=width,
                joint="curve",
            )
        elif kind == "arc":
            draw.arc(
                tuple(primitive["bbox"]),
                start=float(primitive["start"]),
                end=float(primitive["end"]),
                fill=fill,
                width=width,
            )
        else:
            raise ValueError(f"unsupported schematic primitive: {kind}")

    output_root = common.runtime_root(product_id) / "normalized"
    output_root.mkdir(parents=True, exist_ok=True)
    image_path = output_root / "saturated-blue.png"
    canvas.save(image_path, optimize=True)
    report = common.write_json(
        output_root / "normalized-view.json",
        {
            "schemaVersion": 1,
            "productId": product_id,
            "status": "PASS",
            "records": [
                {
                    "variantId": "saturated-blue",
                    "sourceBoundingBoxPx": audit["variants"][0]["boundingBoxPx"],
                    "output": common.relative(image_path),
                    "normalization": schematic["annotation"],
                }
            ],
            "sourceImageRedistributed": False,
            "viewLimitations": audit["limitations"],
        },
    )
    common.emit(
        result,
        stage="normalize-view",
        product_id=product_id,
        paths=[audit_path, schematic_path, image_path, report],
    )


def stage_initialize(job: dict[str, Any], result: Path) -> None:
    product_id = str(job["id"])
    pattern_path, pattern = read_product_document(
        job, "patternContractPath", "pattern contract"
    )
    stitch_path, stitches = read_product_document(
        job, "stitchGraphPath", "stitch graph"
    )
    placement_path, placement = read_product_document(
        job, "initialPlacementPath", "initial placement"
    )
    report = common.write_json(
        common.runtime_root(product_id)
        / "initialization"
        / "initialization-3d.json",
        {
            "schemaVersion": 1,
            "productId": product_id,
            "status": "PASS",
            "collisionPolicy": (
                "positive body-normal offset with a persistent open-front constraint"
            ),
            "patternPieceCount": len(pattern["pieces"]),
            "stitchCount": len(stitches["stitches"]),
            "placements": placement["placements"],
            "constraints": placement["constraints"],
        },
    )
    common.emit(
        result,
        stage="initialize-3d",
        product_id=product_id,
        paths=[pattern_path, stitch_path, placement_path, report],
    )


def main() -> int:
    args = parse_args()
    job_path = common.repo_path(args.job, label="job")
    request_path = common.repo_path(args.request, label="request")
    result_path = common.repo_path(args.result, label="result")
    runtime = (common.ROOT / ".image2outfit").resolve()
    if result_path != runtime and runtime not in result_path.parents:
        raise ValueError("result must be inside .image2outfit runtime state")
    job = common.read_object(job_path, "job")
    request = common.read_object(request_path, "request")
    if job.get("schemaVersion") != 2 or request.get("schemaVersion") != 1:
        raise ValueError("job/request schema version mismatch")
    if job.get("id") != request.get("productId"):
        raise ValueError("job/request product identity mismatch")

    stage = args.stage
    if stage == "ingest-reference":
        common.stage_ingest(job, request, result_path)
    elif stage == "normalize-view":
        stage_normalize(job, result_path)
    elif stage == "decompose-garment":
        common.stage_static(job, stage, "decompositionPath", result_path)
    elif stage == "draft-patterns":
        common.stage_static(job, stage, "patternContractPath", result_path)
    elif stage == "infer-stitches":
        common.stage_static(job, stage, "stitchGraphPath", result_path)
    elif stage == "initialize-3d":
        stage_initialize(job, result_path)
    elif stage == "build-blender":
        common.stage_build(job_path, job, result_path)
    elif stage == "simulate-cloth":
        common.stage_simulate(job, result_path)
    elif stage == "skin-and-export":
        common.stage_export(job, result_path)
    elif stage == "render-evidence":
        common.stage_render(job, result_path)
    elif stage == "audit-geometry":
        common.stage_audit(job, result_path)
    elif stage == "visual-review":
        common.stage_visual_review(job, request, result_path)
    elif stage == "finalize-candidate":
        common.stage_finalize(job, request, result_path)
    else:
        raise AssertionError(stage)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
