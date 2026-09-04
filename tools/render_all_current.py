#!/usr/bin/env python3
"""Render every canonical product at its current completion and build Pages."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import review_console
from resolve_product_build_scope import resolve

IMAGE_SUFFIXES = {".png", ".webp", ".jpg", ".jpeg"}


def run_logged(command: list[str], log_path: Path, env: dict[str, str]) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as stream:
        proc = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    return proc.returncode


def mark_attempt(
    job: dict[str, Any],
    job_path: Path,
    *,
    status: str,
    stage: str,
    detail: str,
) -> None:
    product_root = ROOT / str(job["productRoot"])
    manifest_path = product_root / "ProductManifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        manifest = {
            "schemaVersion": 1,
            "productId": job["id"],
            "productName": job.get("productName", job["id"]),
            "status": "WORKING",
            "productRoot": job["productRoot"],
            "sourceJobPath": job_path.relative_to(ROOT).as_posix(),
        }

    manifest["status"] = manifest.get("status") or "WORKING"
    manifest["currentRenderAttempt"] = {
        "status": status,
        "stage": stage,
        "detail": detail,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }

    blockers = manifest.get("blockers")
    if not isinstance(blockers, list):
        blockers = []
    blockers = [
        item
        for item in blockers
        if not (isinstance(item, dict) and item.get("code") == "CURRENT_HOSTED_RENDER")
    ]
    if status != "PASS":
        blockers.append(
            {
                "code": "CURRENT_HOSTED_RENDER",
                "severity": "CURRENT_RENDER",
                "message": detail,
                "state": "open",
            }
        )
    manifest["blockers"] = blockers
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def clear_stale_previews(job: dict[str, Any]) -> None:
    previews = ROOT / str(job["productRoot"]) / "Previews"
    shutil.rmtree(previews, ignore_errors=True)
    previews.mkdir(parents=True, exist_ok=True)


def render_one(blender: str, job_path: Path) -> dict[str, Any]:
    job = json.loads(job_path.read_text(encoding="utf-8"))
    product_id = str(job["id"])
    clear_stale_previews(job)

    resolution = resolve(
        root=ROOT,
        explicit_job=job_path.relative_to(ROOT).as_posix(),
        changed=[],
        materialize_job=False,
        include_pipeline_request=True,
    )
    env_map = resolution.environment
    if env_map.get("SKIP_PRODUCT_BUILD") == "true":
        detail = f"{product_id}: build skipped ({resolution.reason})"
        mark_attempt(job, job_path, status="FAIL", stage="scope", detail=detail)
        return {
            "productId": product_id,
            "status": "FAIL",
            "stage": "scope",
            "detail": detail,
        }

    process_env = os.environ.copy()
    process_env.update(env_map)
    reports = ROOT / env_map["REPORT_DIR"]
    reports.mkdir(parents=True, exist_ok=True)

    if env_map["PIPELINE_MODE"] == "true":
        command = [
            "uv",
            "run",
            "--locked",
            "--no-default-groups",
            "python",
            "tools/run_garment_pipeline.py",
            "--execute",
            "--engine",
            "deterministic",
            "--request",
            env_map["REQUEST_PATH"],
            "--checkpoint-output",
            env_map["CHECKPOINT_PATH"],
            "--output",
            env_map["CHECKPOINT_PATH"],
        ]
        code = run_logged(command, reports / "render-current-pipeline.log", process_env)
        if code != 0:
            detail = f"{product_id}: canonical pipeline exited {code}"
            mark_attempt(job, job_path, status="FAIL", stage="pipeline", detail=detail)
            return {
                "productId": product_id,
                "status": "FAIL",
                "stage": "pipeline",
                "detail": detail,
            }
    else:
        build_command = [
            blender,
            "--python-use-system-env",
            "--background",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python",
            env_map["BUILD_SCRIPT"],
            "--",
            "--job",
            env_map["JOB_PATH"],
        ]
        code = run_logged(
            build_command,
            reports / "render-current-build.log",
            process_env,
        )
        if code != 0:
            detail = f"{product_id}: Blender build exited {code}"
            mark_attempt(job, job_path, status="FAIL", stage="build", detail=detail)
            return {
                "productId": product_id,
                "status": "FAIL",
                "stage": "build",
                "detail": detail,
            }

        pose_script = env_map.get("HOSTED_POSE_SCRIPT", "")
        if pose_script:
            pose_command = [
                blender,
                "--python-use-system-env",
                "--background",
                env_map["BLEND_PATH"],
                "--python-exit-code",
                "1",
                "--python",
                pose_script,
                "--",
                "--job",
                env_map["JOB_PATH"],
            ]
            code = run_logged(
                pose_command,
                reports / "render-current-poses.log",
                process_env,
            )
            if code != 0:
                detail = f"{product_id}: hosted pose render exited {code}"
                mark_attempt(job, job_path, status="FAIL", stage="poses", detail=detail)
                return {
                    "productId": product_id,
                    "status": "FAIL",
                    "stage": "poses",
                    "detail": detail,
                }

    subprocess.run(
        [
            sys.executable,
            "tools/update_product_hashes.py",
            "--root",
            env_map["PRODUCT_ROOT"],
        ],
        cwd=ROOT,
        env=process_env,
        check=False,
    )

    preview_root = ROOT / env_map["PRODUCT_ROOT"] / "Previews"
    preview_files = sorted(
        path.relative_to(ROOT).as_posix()
        for path in preview_root.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    status = "PASS" if preview_files else "FAIL"
    detail = (
        f"{product_id}: current render captured {len(preview_files)} images"
        if preview_files
        else f"{product_id}: build completed but produced no review images"
    )
    mark_attempt(job, job_path, status=status, stage="capture", detail=detail)
    return {
        "productId": product_id,
        "status": status,
        "stage": "capture",
        "detail": detail,
        "previewFiles": preview_files,
    }


def write_webp(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() == ".webp":
        shutil.copy2(source, destination)
        return
    with Image.open(source) as image:
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA")
        image.save(destination, format="WEBP", quality=90, method=6)


def build_io_gallery(site: Path) -> dict[str, Any]:
    io_root = site / "io"
    io_root.mkdir(parents=True, exist_ok=True)
    products: list[dict[str, Any]] = []
    total_webp = 0

    product_root = ROOT / "Assets" / "GenWorks"
    for workspace in sorted(product_root.iterdir()):
        manifest_path = workspace / "ProductManifest.json"
        if not workspace.is_dir() or not manifest_path.is_file():
            continue
        manifest = review_console.load_json(manifest_path, {})
        preview_root, origin = review_console.preview_directory(workspace)
        sources = review_console.image_files(preview_root)
        selected: dict[Path, Path] = {}
        for source in sources:
            relative = source.relative_to(preview_root)
            target_relative = relative.with_suffix(".webp")
            existing = selected.get(target_relative)
            if existing is None or source.suffix.lower() == ".webp":
                selected[target_relative] = source

        assets: list[dict[str, str]] = []
        for target_relative, source in sorted(selected.items()):
            destination = io_root / workspace.name / target_relative
            write_webp(source, destination)
            assets.append(
                {
                    "name": target_relative.as_posix(),
                    "href": destination.relative_to(site).as_posix(),
                    "source": source.relative_to(ROOT).as_posix(),
                    "sourceKind": origin,
                }
            )
        total_webp += len(assets)
        gates = manifest.get("technicalGates")
        visual_status = (
            str(gates.get("visualAppearanceReview", "UNKNOWN"))
            if isinstance(gates, dict)
            else "UNKNOWN"
        )
        products.append(
            {
                "productId": workspace.name,
                "state": review_console.safe_state(manifest),
                "visualAppearanceReview": visual_status,
                "sourceKind": origin,
                "webpCount": len(assets),
                "assets": assets,
            }
        )

    catalog = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "productCount": len(products),
        "webpCount": total_webp,
        "products": products,
    }
    (io_root / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    cards: list[str] = []
    for product in products:
        images = "".join(
            f'<figure><img loading="lazy" src="../{asset["href"]}" '
            f'alt="{product["productId"]} {asset["name"]}">'
            f'<figcaption>{asset["name"]}</figcaption></figure>'
            for asset in product["assets"]
        )
        if not images:
            images = "<p>現時点で追跡済みレンダーなし</p>"
        cards.append(
            "<section>"
            f'<h2 id="{product["productId"]}">{product["productId"]}</h2>'
            f'<p>state={product["state"]} · '
            f'visualAppearanceReview={product["visualAppearanceReview"]} · '
            f'source={product["sourceKind"]} · WebP={product["webpCount"]}</p>'
            f'<div class="grid">{images}</div>'
            "</section>"
        )

    (io_root / "index.html").write_text(
        "<!doctype html><html lang=\"ja\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>image2outfit io WebP previews</title>"
        "<style>body{font-family:system-ui,sans-serif;margin:24px;background:#0f1117;color:#f5f7fb}"
        "a{color:#8bdcff}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}"
        "figure{margin:0;padding:8px;border:1px solid #465064;border-radius:10px;background:#1b1e28}"
        "img{width:100%;aspect-ratio:1;object-fit:contain;background:#090b10}figcaption{overflow-wrap:anywhere}"
        "section{margin:36px 0}</style></head><body>"
        '<p><a href="../">Review Console</a> · <a href="./catalog.json">catalog.json</a></p>'
        "<h1>io WebP previews</h1>"
        "<p>品質判定と公開を分離し、WORKING / REJECTED / visualAppearanceReview FAIL も現在の証拠として表示します。</p>"
        + "".join(cards)
        + "</body></html>",
        encoding="utf-8",
    )
    return catalog


def build_site(site: Path, summary_path: Path) -> dict[str, Any]:
    data = review_console.build(ROOT, ROOT)
    site.mkdir(parents=True, exist_ok=True)

    for name in ("index.html", "review-console.json"):
        shutil.copy2(ROOT / name, site / name)
    for name in ("review-showcase.css", "review-showcase.js"):
        shutil.copy2(ROOT / "site" / name, site / name)

    index_path = site / "index.html"
    html = index_path.read_text(encoding="utf-8")
    html = html.replace(
        "</head>",
        '<link rel="stylesheet" href="./review-showcase.css"></head>',
        1,
    )
    html = html.replace(
        "</body>",
        '<script src="./review-showcase.js"></script></body>',
        1,
    )
    index_path.write_text(html, encoding="utf-8")

    hrefs: set[str] = set()
    for product in data.get("products", []):
        hrefs.add(product["manifest_href"])
        for key in ("assets", "gates", "evidence"):
            for item in product.get(key, []):
                href = item.get("href")
                if href and not href.startswith(("https://", "http://")):
                    hrefs.add(href)

    for href in sorted(hrefs):
        source = (ROOT / href).resolve()
        if source != ROOT and ROOT not in source.parents:
            raise RuntimeError(f"local review link escapes repository: {href}")
        if not source.is_file():
            continue
        destination = site / href
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    if summary_path.is_file():
        destination = site / ".image2outfit" / "render-current-summary.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(summary_path, destination)

    gallery = build_io_gallery(site)
    index_path = site / "index.html"
    html = index_path.read_text(encoding="utf-8")
    html = html.replace(
        "</nav>",
        '<a href="./io/">io WebP</a></nav>',
        1,
    )
    index_path.write_text(html, encoding="utf-8")
    data["io"] = {
        "productCount": gallery["productCount"],
        "webpCount": gallery["webpCount"],
    }
    return data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender", required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--site", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    jobs = sorted((ROOT / "config" / "products").glob("*/job.json"))
    results: list[dict[str, Any]] = []

    for job_path in jobs:
        product_id = job_path.parent.name
        print(f"=== render-current {product_id} ===", flush=True)
        try:
            results.append(render_one(args.blender, job_path))
        except Exception as exc:
            job = json.loads(job_path.read_text(encoding="utf-8"))
            detail = (
                f"{product_id}: unhandled render exception: {type(exc).__name__}: {exc}"
            )
            mark_attempt(
                job,
                job_path,
                status="FAIL",
                stage="exception",
                detail=detail,
            )
            results.append(
                {
                    "productId": product_id,
                    "status": "FAIL",
                    "stage": "exception",
                    "detail": detail,
                }
            )

    summary_path = args.summary if args.summary.is_absolute() else ROOT / args.summary
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "productCount": len(results),
        "passCount": sum(row["status"] == "PASS" for row in results),
        "failCount": sum(row["status"] != "PASS" for row in results),
        "products": results,
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    site = args.site if args.site.is_absolute() else ROOT / args.site
    data = build_site(site, summary_path)
    print(
        json.dumps(
            {
                "renderSummary": summary,
                "pagesProducts": len(data.get("products", [])),
                "ioProducts": data.get("io", {}).get("productCount", 0),
                "ioWebpCount": data.get("io", {}).get("webpCount", 0),
                "site": site.relative_to(ROOT).as_posix(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
