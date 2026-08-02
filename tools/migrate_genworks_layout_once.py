#!/usr/bin/env python3
"""One-time migration to Assets/GenWorks/{slug}/Prefab/*.prefab."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BINARY_SUFFIXES = {
    ".blend",
    ".fbx",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".zip",
    ".glb",
    ".obj",
    ".dll",
    ".so",
    ".a",
    ".exe",
    ".xz",
    ".tar",
    ".woff",
    ".woff2",
}


def git(*args: str) -> None:
    subprocess.run(["git", *args], cwd=ROOT, check=True)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )


def move_meta(source: Path, destination: Path, replacements: dict[str, str]) -> None:
    source_meta = Path(source.as_posix() + ".meta")
    destination_meta = Path(destination.as_posix() + ".meta")
    if not source_meta.exists():
        return
    git("mv", source_meta.as_posix(), destination_meta.as_posix())
    replacements[source_meta.as_posix()] = destination_meta.as_posix()


def replace_text_paths(replacements: dict[str, str]) -> int:
    ordered = sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True)
    changed = 0
    for path in ROOT.rglob("*"):
        if (
            not path.is_file()
            or ".git" in path.parts
            or path.suffix.lower() in BINARY_SUFFIXES
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        updated = text
        for old, new in ordered:
            updated = updated.replace(old, new)
            updated = updated.replace(old.replace("/", "\\"), new.replace("/", "\\"))
        if updated != text:
            path.write_text(updated, encoding="utf-8", newline="")
            changed += 1
    return changed


def find_legacy_snapshot_roots() -> list[Path]:
    legacy_root = ROOT / "Assets/GenWorks/Legacy"
    if not legacy_root.exists():
        return []
    roots: set[Path] = set()
    markers = ("audit.json", "audit-summary.json", "AUDIT_REPORT.md", "ProductManifest.json")
    for prefab in legacy_root.rglob("*.prefab"):
        selected = prefab.parent
        for parent in prefab.parents:
            if parent == legacy_root:
                break
            if any((parent / marker).exists() for marker in markers):
                selected = parent
                break
        roots.add(selected)
    return sorted(roots)


def main() -> int:
    jobs = sorted((ROOT / "config/products").glob("*/job.json"))
    if not jobs:
        raise SystemExit("No configured products found")

    replacements: dict[str, str] = {}

    for job_path in jobs:
        job = read_json(job_path)
        product_id = job_path.parent.name
        if job.get("id") != product_id:
            raise SystemExit(f"job identity mismatch: {job_path}")

        old_root = ROOT / f"Assets/GenWorks/Products/{product_id}"
        new_root = ROOT / f"Assets/GenWorks/{product_id}"
        declared_root = ROOT / str(job.get("productRoot", ""))
        source_root = old_root if old_root.exists() else declared_root

        if source_root.resolve() != new_root.resolve():
            if not source_root.is_dir():
                raise SystemExit(f"configured product root missing: {source_root}")
            if new_root.exists():
                raise SystemExit(f"canonical product root already exists: {new_root}")
            git("mv", source_root.relative_to(ROOT).as_posix(), new_root.relative_to(ROOT).as_posix())
            move_meta(source_root.relative_to(ROOT), new_root.relative_to(ROOT), replacements)
            replacements[source_root.relative_to(ROOT).as_posix()] = new_root.relative_to(ROOT).as_posix()
            replacements[old_root.relative_to(ROOT).as_posix()] = new_root.relative_to(ROOT).as_posix()

        product_root = ROOT / f"Assets/GenWorks/{product_id}"
        prefab_dir = product_root / "Prefab"
        prefab_dir.mkdir(parents=True, exist_ok=True)

        old_prefabs_dir = product_root / "Prefabs"
        old_prefabs_meta = Path(old_prefabs_dir.as_posix() + ".meta")
        new_prefab_meta = Path(prefab_dir.as_posix() + ".meta")
        if old_prefabs_meta.exists() and not new_prefab_meta.exists():
            git(
                "mv",
                old_prefabs_meta.relative_to(ROOT).as_posix(),
                new_prefab_meta.relative_to(ROOT).as_posix(),
            )
            replacements[
                old_prefabs_meta.relative_to(ROOT).as_posix()
            ] = new_prefab_meta.relative_to(ROOT).as_posix()

        prefab_files = sorted(
            path for path in product_root.rglob("*.prefab") if path.parent != prefab_dir
        )
        for source in prefab_files:
            destination = prefab_dir / source.name
            if destination.exists():
                raise SystemExit(f"prefab basename collision: {destination}")
            source_rel = source.relative_to(ROOT)
            destination_rel = destination.relative_to(ROOT)
            old_root_rel = Path(f"Assets/GenWorks/Products/{product_id}")
            new_root_rel = Path(f"Assets/GenWorks/{product_id}")
            original_rel = Path(
                source_rel.as_posix().replace(new_root_rel.as_posix(), old_root_rel.as_posix(), 1)
            )
            git("mv", source_rel.as_posix(), destination_rel.as_posix())
            replacements[source_rel.as_posix()] = destination_rel.as_posix()
            replacements[original_rel.as_posix()] = destination_rel.as_posix()
            move_meta(source_rel, destination_rel, replacements)
            original_meta = original_rel.as_posix() + ".meta"
            destination_meta = destination_rel.as_posix() + ".meta"
            replacements[original_meta] = destination_meta

        if old_prefabs_dir.exists():
            for path in sorted(item for item in old_prefabs_dir.rglob("*") if item.is_file()):
                git("rm", "-f", path.relative_to(ROOT).as_posix())
            shutil.rmtree(old_prefabs_dir)

        if not list(prefab_dir.glob("*.prefab")):
            raise SystemExit(f"product has no canonical prefab: {product_id}")

    products_root = ROOT / "Assets/GenWorks/Products"
    if products_root.exists():
        leftovers = list(products_root.iterdir())
        if leftovers:
            raise SystemExit(
                "Unmigrated entries remain under Products: "
                + ", ".join(path.as_posix() for path in leftovers)
            )
        products_root.rmdir()
    products_meta = ROOT / "Assets/GenWorks/Products.meta"
    if products_meta.exists():
        git("rm", "-f", products_meta.relative_to(ROOT).as_posix())

    replacements.update(
        {
            "Assets/GenWorks/Products/<product-id>": "Assets/GenWorks/<product-id>",
            "Assets/GenWorks/Products/<product-slug>": "Assets/GenWorks/<product-slug>",
            "Assets/GenWorks/Products": "Assets/GenWorks",
        }
    )
    changed_text = replace_text_paths(replacements)

    layout_path = ROOT / "config/genworks-layout.json"
    layout = read_json(layout_path)
    layout["productRoot"] = "Assets/GenWorks"
    layout["requiredProductDirectories"] = [
        "Prefab" if value == "Prefabs" else value
        for value in layout["requiredProductDirectories"]
    ]
    write_json(layout_path, layout)

    policy_path = ROOT / "config/genworks-handoff-policy.json"
    policy = read_json(policy_path)
    policy["canonicalWorkspacePattern"] = "Assets/GenWorks/<product-id>"
    policy["canonicalPrefabPattern"] = "Assets/GenWorks/<product-id>/Prefab/*.prefab"
    write_json(policy_path, policy)

    active_catalog = []
    for job_path in jobs:
        job = read_json(job_path)
        product_id = job_path.parent.name
        expected_root = f"Assets/GenWorks/{product_id}"
        if job.get("productRoot") != expected_root:
            raise SystemExit(f"noncanonical productRoot: {job_path}: {job.get('productRoot')}")
        product_root = ROOT / expected_root
        manifest_path = product_root / "ProductManifest.json"
        manifest = read_json(manifest_path)
        for field in ("prefabAssetPath", "integratedPrefabAssetPath"):
            value = str(job.get(field, ""))
            pattern = rf"^Assets/GenWorks/{re.escape(product_id)}/Prefab/[^/]+\.prefab$"
            if not re.fullmatch(pattern, value):
                raise SystemExit(f"noncanonical {field}: {job_path}: {value}")
            if not (ROOT / value).is_file():
                raise SystemExit(f"missing configured prefab: {value}")
        all_prefabs = sorted(product_root.rglob("*.prefab"))
        for prefab in all_prefabs:
            if prefab.parent != product_root / "Prefab":
                raise SystemExit(f"prefab outside canonical flat directory: {prefab}")
        active_catalog.append(
            {
                "productId": product_id,
                "productName": manifest.get("productName", product_id),
                "status": manifest.get("status", "UNKNOWN"),
                "productRoot": expected_root,
                "prefabs": [path.relative_to(ROOT).as_posix() for path in all_prefabs],
            }
        )

    legacy_catalog = []
    for snapshot_root in find_legacy_snapshot_roots():
        legacy_catalog.append(
            {
                "snapshotId": snapshot_root.name,
                "status": "LEGACY_SNAPSHOT",
                "productRoot": snapshot_root.relative_to(ROOT).as_posix(),
                "prefabs": [
                    path.relative_to(ROOT).as_posix()
                    for path in sorted(snapshot_root.rglob("*.prefab"))
                ],
            }
        )

    catalog = {
        "schemaVersion": 1,
        "canonicalPattern": "Assets/GenWorks/{slug}/Prefab/*.prefab",
        "activeProductCount": len(active_catalog),
        "legacySnapshotCount": len(legacy_catalog),
        "assetBackedOutfitCount": len(active_catalog) + len(legacy_catalog),
        "activeProducts": active_catalog,
        "legacySnapshots": legacy_catalog,
    }
    write_json(ROOT / "Assets/GenWorks/OutfitCatalog.json", catalog)

    residuals: list[str] = []
    for path in ROOT.rglob("*"):
        if (
            not path.is_file()
            or ".git" in path.parts
            or path.suffix.lower() in BINARY_SUFFIXES
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "Assets/GenWorks/Products" in text:
            residuals.append(f"{path.relative_to(ROOT)}: old Products root")
        if re.search(r"Assets/GenWorks/[a-z0-9][a-z0-9._-]*/Prefabs(?:/|\\)", text):
            residuals.append(f"{path.relative_to(ROOT)}: old Prefabs path")
    if residuals:
        raise SystemExit("Stale GenWorks paths remain:\n" + "\n".join(residuals))

    print(json.dumps(catalog, ensure_ascii=False, indent=2))
    print(f"updated text files: {changed_text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
