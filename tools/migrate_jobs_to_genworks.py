#!/usr/bin/env python3
"""Move existing image2outfit job outputs into Assets/GenWorks.

The command is dry-run by default. Use --apply after reviewing the plan.
Unity .meta files are moved together with their assets so existing GUID references survive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Move:
    source: str
    destination: str
    status: str


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def repo_path(root: Path, value: str) -> Path:
    result = (root / value).resolve()
    if result != root and root not in result.parents:
        raise ValueError(f"path escapes repository: {value}")
    return result


def destination_for(product_root: str, source: str, job: dict[str, Any]) -> str:
    suffix = Path(source).suffix.lower()
    name = Path(source).name
    if source == job.get("blendPath") or suffix == ".blend":
        return f"{product_root}/Source/Blender/{name}"
    if source == job.get("fbxAssetPath") or suffix == ".fbx":
        return f"{product_root}/Models/{name}"
    if source == job.get("integratedPrefabAssetPath"):
        adapter = str(job.get("adapterId", "target")).replace("/", "-")
        return f"{product_root}/Prefabs/Integrated/{adapter}/{name}"
    if source == job.get("prefabAssetPath") or suffix == ".prefab":
        return f"{product_root}/Prefabs/Outfit/{name}"
    if suffix == ".mat":
        return f"{product_root}/Materials/{name}"
    if suffix in {".png", ".jpg", ".jpeg", ".tga", ".psd", ".webp"}:
        return f"{product_root}/Textures/{name}"
    if suffix in {".anim", ".controller", ".asset"}:
        return f"{product_root}/Runtime/{name}"
    if suffix in {".md", ".txt", ".json"}:
        return f"{product_root}/Documentation/{name}"
    return f"{product_root}/Extras/{name}"


def move_file(
    root: Path, source_rel: str, destination_rel: str, apply: bool
) -> Move:
    source = repo_path(root, source_rel)
    destination = repo_path(root, destination_rel)
    if source == destination:
        return Move(source_rel, destination_rel, "already-canonical")
    if not source.exists():
        return Move(source_rel, destination_rel, "missing")
    if destination.exists():
        if (
            source.is_file()
            and destination.is_file()
            and sha256(source) == sha256(destination)
        ):
            return Move(source_rel, destination_rel, "duplicate")
        raise FileExistsError(
            f"destination exists with different content: {destination_rel}"
        )
    if apply:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        source_meta = Path(str(source) + ".meta")
        destination_meta = Path(str(destination) + ".meta")
        if source_meta.exists():
            destination_meta.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source_meta), str(destination_meta))
    return Move(source_rel, destination_rel, "moved" if apply else "planned")


def migrate_job(root: Path, job_path: Path, apply: bool) -> dict[str, Any]:
    job = read_json(job_path)
    product_id = str(job.get("id", "")).strip()
    if not product_id:
        raise ValueError(f"job id is missing: {job_path}")
    product_root = f"Assets/GenWorks/Products/{product_id}"
    original_fields = {
        field: job.get(field)
        for field in (
            "blendPath",
            "fbxAssetPath",
            "prefabAssetPath",
            "integratedPrefabAssetPath",
        )
        if job.get(field)
    }
    preview_paths = dict(job.get("previewPaths", {}))
    delivery_assets = list(job.get("deliveryAssets", []))
    inputs = list(
        dict.fromkeys(
            [*original_fields.values(), *preview_paths.values(), *delivery_assets]
        )
    )
    mapping = {
        source: destination_for(product_root, source, job) for source in inputs
    }

    moves = [
        move_file(root, source, destination, apply)
        for source, destination in mapping.items()
    ]
    for field, source in original_fields.items():
        job[field] = mapping[source]
    job["previewPaths"] = {
        view: f"{product_root}/Previews/{view}{Path(source).suffix.lower() or '.png'}"
        for view, source in preview_paths.items()
    }
    for view, source in preview_paths.items():
        planned = mapping[source]
        desired = job["previewPaths"][view]
        if planned != desired:
            if apply:
                current = repo_path(root, planned)
                desired_path = repo_path(root, desired)
                if current.exists() and not desired_path.exists():
                    desired_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(current), str(desired_path))
                    current_meta = Path(str(current) + ".meta")
                    if current_meta.exists():
                        shutil.move(str(current_meta), str(desired_path) + ".meta")
            mapping[source] = desired
    job["deliveryAssets"] = [mapping[source] for source in delivery_assets]
    job["productRoot"] = product_root
    job["productManifestPath"] = f"{product_root}/ProductManifest.json"

    manifest = {
        "schemaVersion": 1,
        "productId": product_id,
        "productName": job.get("productName", product_id),
        "status": "REVIEW_REQUIRED",
        "targetAdapterId": job.get("adapterId", ""),
        "productRoot": product_root,
        "outfitPrefabPath": job.get("prefabAssetPath", ""),
        "integratedPrefabPath": job.get("integratedPrefabAssetPath", ""),
        "previewPath": next(iter(job.get("previewPaths", {}).values()), ""),
        "documentationPath": f"{product_root}/README.md",
        "sourceJobPath": job_path.resolve().relative_to(root.resolve()).as_posix(),
    }
    if apply:
        write_json(job_path, job)
        write_json(root / job["productManifestPath"], manifest)
        readme = root / product_root / "README.md"
        if not readme.exists():
            readme.write_text(
                f"# {manifest['productName']}\n\n"
                f"- Product ID: `{product_id}`\n"
                f"- Target adapter: `{manifest['targetAdapterId']}`\n"
                f"- Status: `{manifest['status']}`\n\n"
                "Unityの `GenWorks > Product Catalog` からPrefabとプレビューを確認してください。\n",
                encoding="utf-8",
            )
    return {
        "job": job_path.resolve().relative_to(root.resolve()).as_posix(),
        "productRoot": product_root,
        "applied": apply,
        "moves": [asdict(item) for item in moves],
        "updatedJob": job,
        "manifest": manifest,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("jobs", nargs="*", type=Path)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    jobs = args.jobs or sorted(
        (root / "Assets" / "_Local" / "Jobs").glob("**/job.json")
    )
    reports = [
        migrate_job(root, path if path.is_absolute() else root / path, args.apply)
        for path in jobs
    ]
    print(
        json.dumps(
            {"schemaVersion": 1, "applied": args.apply, "jobs": reports},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
