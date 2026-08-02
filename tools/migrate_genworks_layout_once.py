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
    ".blend", ".fbx", ".png", ".jpg", ".jpeg", ".webp", ".zip",
    ".glb", ".obj", ".dll", ".so", ".a", ".exe", ".xz", ".tar",
    ".woff", ".woff2",
}
PREFAB_FIELDS = ("prefabAssetPath", "integratedPrefabAssetPath")


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
    source_meta = ROOT / f"{source.as_posix()}.meta"
    destination_meta = ROOT / f"{destination.as_posix()}.meta"
    if not source_meta.exists():
        return
    git("mv", source_meta.relative_to(ROOT).as_posix(), destination_meta.relative_to(ROOT).as_posix())
    replacements[source_meta.relative_to(ROOT).as_posix()] = destination_meta.relative_to(ROOT).as_posix()


def replace_text_paths(replacements: dict[str, str]) -> int:
    ordered = sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True)
    changed = 0
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path.suffix.lower() in BINARY_SUFFIXES:
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


def canonical_prefab_path(product_id: str, value: str) -> str:
    name = Path(value).name
    if not name.lower().endswith(".prefab"):
        raise SystemExit(f"invalid configured prefab filename: {value}")
    return f"Assets/GenWorks/{product_id}/Prefab/{name}"


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

        old_root_rel = Path(f"Assets/GenWorks/Products/{product_id}")
        new_root_rel = Path(f"Assets/GenWorks/{product_id}")
        old_root = ROOT / old_root_rel
        new_root = ROOT / new_root_rel
        declared_root = ROOT / str(job.get("productRoot", ""))
        source_root = old_root if old_root.exists() else declared_root

        for field in PREFAB_FIELDS:
            configured = str(job.get(field, ""))
            if configured:
                replacements[configured] = canonical_prefab_path(product_id, configured)

        if source_root.resolve() != new_root.resolve():
            if not source_root.is_dir():
                raise SystemExit(f"configured product root missing: {source_root}")
            if new_root.exists():
                raise SystemExit(f"canonical product root already exists: {new_root}")
            source_rel = source_root.relative_to(ROOT)
            git("mv", source_rel.as_posix(), new_root_rel.as_posix())
            move_meta(source_rel, new_root_rel, replacements)
            replacements[source_rel.as_posix()] = new_root_rel.as_posix()
            replacements[old_root_rel.as_posix()] = new_root_rel.as_posix()

        product_root = ROOT / new_root_rel
        prefab_dir = product_root / "Prefab"
        prefab_dir.mkdir(parents=True, exist_ok=True)

        old_prefabs_dir = product_root / "Prefabs"
        old_prefabs_meta = Path(f"{old_prefabs_dir.as_posix()}.meta")
        new_prefab_meta = Path(f"{prefab_dir.as_posix()}.meta")
        if old_prefabs_meta.exists() and not new_prefab_meta.exists():
            git(
                "mv",
                old_prefabs_meta.relative_to(ROOT).as_posix(),
                new_prefab_meta.relative_to(ROOT).as_posix(),
            )
            replacements[old_prefabs_meta.relative_to(ROOT).as_posix()] = new_prefab_meta.relative_to(ROOT).as_posix()

        prefab_files = sorted(path for path in product_root.rglob("*.prefab") if path.parent != prefab_dir)
        for source in prefab_files:
            destination = prefab_dir / source.name
            if destination.exists():
                raise SystemExit(f"prefab basename collision: {destination}")
            source_rel = source.relative_to(ROOT)
            destination_rel = destination.relative_to(ROOT)
            original_rel = Path(source_rel.as_posix().replace(new_root_rel.as_posix(), old_root_rel.as_posix(), 1))
            git("mv", source_rel.as_posix(), destination_rel.as_posix())
            replacements[source_rel.as_posix()] = destination_rel.as_posix()
            replacements[original_rel.as_posix()] = destination_rel.as_posix()
            move_meta(source_rel, destination_rel, replacements)
            replacements[f"{original_rel.as_posix()}.meta"] = f"{destination_rel.as_posix()}.meta"

        if old_prefabs_dir.exists():
            for path in sorted(item for item in old_prefabs_dir.rglob("*") if item.is_file()):
                git("rm", "-f", path.relative_to(ROOT).as_posix())
            shutil.rmtree(old_prefabs_dir)

        if not list(prefab_dir.glob("*.prefab")):
            (prefab_dir / ".gitkeep").touch()

    products_root = ROOT / "Assets/GenWorks/Products"
    if products_root.exists():
        leftovers = list(products_root.iterdir())
        if leftovers:
            raise SystemExit("Unmigrated entries remain under Products: " + ", ".join(path.as_posix() for path in leftovers))
        products_root.rmdir()
    products_meta = ROOT / "Assets/GenWorks/Products.meta"
    if products_meta.exists():
        git("rm", "-f", products_meta.relative_to(ROOT).as_posix())

    replacements.update({
        "Assets/GenWorks/Products/<product-id>": "Assets/GenWorks/<product-id>",
        "Assets/GenWorks/Products/<product-slug>": "Assets/GenWorks/<product-slug>",
        "Assets/GenWorks/Products": "Assets/GenWorks",
    })
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

    asset_backed: list[dict] = []
    planned: list[dict] = []
    active_products: list[dict] = []

    for job_path in jobs:
        job = read_json(job_path)
        product_id = job_path.parent.name
        expected_root = f"Assets/GenWorks/{product_id}"
        if job.get("productRoot") != expected_root:
            raise SystemExit(f"noncanonical productRoot: {job_path}: {job.get('productRoot')}")

        product_root = ROOT / expected_root
        manifest = read_json(product_root / "ProductManifest.json")
        status = str(manifest.get("status", "UNKNOWN"))
        all_prefabs = sorted(product_root.rglob("*.prefab"))
        for prefab in all_prefabs:
            if prefab.parent != product_root / "Prefab":
                raise SystemExit(f"prefab outside canonical flat directory: {prefab}")

        configured_paths: list[str] = []
        for field in PREFAB_FIELDS:
            value = str(job.get(field, ""))
            pattern = rf"^Assets/GenWorks/{re.escape(product_id)}/Prefab/[^/]+\.prefab$"
            if not re.fullmatch(pattern, value):
                raise SystemExit(f"noncanonical {field}: {job_path}: {value}")
            configured_paths.append(value)

        if all_prefabs:
            missing = [value for value in configured_paths if not (ROOT / value).is_file()]
            if missing:
                raise SystemExit(f"asset-backed product is missing configured prefabs: {product_id}: {missing}")
            classification = "ASSET_BACKED"
        else:
            if status not in {"WORKING", "REJECTED"}:
                raise SystemExit(f"prefabless product cannot claim {status}: {product_id}")
            classification = "PLANNED_CONTRACT"

        entry = {
            "productId": product_id,
            "productName": manifest.get("productName", product_id),
            "status": status,
            "classification": classification,
            "productRoot": expected_root,
            "configuredPrefabPaths": configured_paths,
            "trackedPrefabs": [path.relative_to(ROOT).as_posix() for path in all_prefabs],
        }
        active_products.append(entry)
        (asset_backed if all_prefabs else planned).append(entry)

    legacy_catalog = []
    for snapshot_root in find_legacy_snapshot_roots():
        legacy_catalog.append({
            "snapshotId": snapshot_root.name,
            "status": "LEGACY_SNAPSHOT",
            "productRoot": snapshot_root.relative_to(ROOT).as_posix(),
            "trackedPrefabs": [
                path.relative_to(ROOT).as_posix()
                for path in sorted(snapshot_root.rglob("*.prefab"))
            ],
        })

    catalog = {
        "schemaVersion": 1,
        "canonicalPattern": "Assets/GenWorks/{slug}/Prefab/*.prefab",
        "configuredProductCount": len(active_products),
        "activeAssetBackedCount": len(asset_backed),
        "plannedContractCount": len(planned),
        "legacySnapshotCount": len(legacy_catalog),
        "assetBackedOutfitCount": len(asset_backed) + len(legacy_catalog),
        "knownOutfitConceptCount": len(active_products) + len(legacy_catalog),
        "activeProducts": active_products,
        "assetBackedProducts": asset_backed,
        "plannedProducts": planned,
        "legacySnapshots": legacy_catalog,
    }
    write_json(ROOT / "Assets/GenWorks/OutfitCatalog.json", catalog)

    residuals: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path.suffix.lower() in BINARY_SUFFIXES:
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
