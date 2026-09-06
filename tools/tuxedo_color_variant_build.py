#!/usr/bin/env python3
"""Generate a material-only Tuxedo variant from the canonical base blend."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy

import genworks_product_common as g
import siroino_strappy_knit_build as base
from tuxedo_halter_runtime import (
    garment_geometry_sha256,
    write_prefabs,
)

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "siroino-tuxedo-halter-dress-large"


def parse_args() -> argparse.Namespace:
    raw = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    parser.add_argument("--base-report", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--variant-id", required=True)
    parser.add_argument("--waistcoat-material", required=True)
    parser.add_argument("--proof-only", action="store_true")
    return parser.parse_args(raw)


def read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def main() -> int:
    args = parse_args()
    job = read_json(Path(args.job).resolve())
    base_report_path = Path(args.base_report).resolve()
    base_report = read_json(base_report_path)
    output_root = Path(args.output_root).resolve()
    if job.get("id") != PRODUCT_ID or base_report.get("productId") != PRODUCT_ID:
        raise ValueError("color variant product identity mismatch")
    if args.waistcoat_material != "black":
        raise ValueError("color proof only permits the tracked black waistcoat preset")

    body, armature = g.select_body_and_armature()
    garments = [
        obj
        for obj in bpy.data.objects
        if obj.parent == armature and obj is not body and obj.type in {"MESH", "CURVE"}
    ]
    if not garments:
        raise RuntimeError("base blend contains no reusable garment geometry")

    expected_geometry = str(base_report["geometrySha256"])
    before_geometry = garment_geometry_sha256(garments)
    if before_geometry != expected_geometry:
        raise RuntimeError(
            "base blend geometry does not match its build report: "
            f"{before_geometry} != {expected_geometry}"
        )

    black = bpy.data.materials.get("MAT_Black_Satin")
    if black is None:
        raise RuntimeError("base blend is missing MAT_Black_Satin")
    replaced = 0
    for obj in garments:
        materials = getattr(getattr(obj, "data", None), "materials", None)
        if materials is None:
            continue
        for index, material in enumerate(materials):
            if material is not None and material.name == "MAT_Wine_Satin":
                materials[index] = black
                replaced += 1
    if replaced == 0:
        raise RuntimeError("no MAT_Wine_Satin slots were replaced")

    after_geometry = garment_geometry_sha256(garments)
    if after_geometry != before_geometry:
        raise RuntimeError("material-only variant changed geometry")

    blend_path = output_root / "Source" / "Blender" / "SiroinoTuxedoHalterDressLarge.blend"
    report_path = output_root / "Evidence" / "Build" / "product-build-report.json"
    blend_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)

    report = {
        "schemaVersion": 1,
        "passed": True,
        "productId": PRODUCT_ID,
        "productName": job["productName"],
        "variantId": args.variant_id,
        "variantKind": "color",
        "recipeVersion": base_report["materialRecipe"]["recipeVersion"],
        "geometrySha256": after_geometry,
        "geometryReuse": {
            "sourceBlend": job["blendPath"],
            "sourceReport": str(base_report_path),
            "before": before_geometry,
            "after": after_geometry,
            "materialSlotsReplaced": replaced,
            "passed": before_geometry == after_geometry,
        },
        "materialOverride": {
            "waistcoat": args.waistcoat_material,
            "materialName": "MAT_Black_Satin",
        },
        "clothSimulation": {
            "mode": "reused-settled-base-geometry",
            "rerun": False,
        },
        "views": {},
    }

    if not args.proof_only:
        _, camera = g.pastel_studio()
        g.set_pose(armature, "neutral")
        preview_dir = output_root / "Previews"
        previews = {
            name: preview_dir / f"{name}.png"
            for name in ("front", "back", "left", "right", "three-quarter")
        }
        g.render_five_views(camera, previews)
        multiview = preview_dir / f"{PRODUCT_ID}-{args.variant_id}-multiview.webp"
        g.contact_sheet(
            previews,
            multiview,
            order=("front", "three-quarter", "left", "right", "back"),
            title=f"TUXEDO HALTER / {args.variant_id}",
        )
        report["views"] = {
            name: str(path.relative_to(ROOT)).replace("\\", "/")
            for name, path in previews.items()
        }
        report["multiview"] = str(multiview.relative_to(ROOT)).replace("\\", "/")

        g.reset_pose(armature)
        body.hide_render = True
        fbx_path = output_root / "Models" / "SiroinoTuxedoHalterDressLarge.fbx"
        prefab = output_root / "Prefab" / "SiroinoTuxedoHalterDressLarge.prefab"
        integrated = (
            output_root
            / "Prefab"
            / "Siroino_Large_TuxedoHalterDress.prefab"
        )
        base.export_fbx(fbx_path, armature, garments)
        write_prefabs(
            fbx_path,
            prefab,
            integrated,
            f"{job['productName']} / {args.variant_id}",
        )

    write_json(report_path, report)
    write_json(
        output_root / "ProductManifest.json",
        {
            "schemaVersion": 1,
            "productId": PRODUCT_ID,
            "productName": job["productName"],
            "variantId": args.variant_id,
            "status": "WORKING",
            "recipeVersion": report["recipeVersion"],
            "geometrySha256": after_geometry,
            "technicalGates": {
                "geometryReuse": "PASS",
                "materialVariant": "PASS",
                "visualAppearanceReview": "PENDING",
            },
            "buildReport": str(report_path.relative_to(ROOT)).replace("\\", "/"),
        },
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
