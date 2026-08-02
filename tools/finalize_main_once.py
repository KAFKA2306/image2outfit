#!/usr/bin/env python3
"""Fold pending product contracts and execute the one-time canonical migration."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BINARY_SUFFIXES = {
    ".blend", ".fbx", ".png", ".jpg", ".jpeg", ".webp", ".zip",
    ".glb", ".obj", ".dll", ".so", ".a", ".exe", ".xz", ".tar",
    ".woff", ".woff2",
}


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def fold_lace_contract() -> None:
    path = ROOT / "config/products/siroino-lace-halter-large/job.json"
    job = json.loads(path.read_text(encoding="utf-8-sig"))
    root = "Assets/GenWorks/Products/siroino-lace-halter-large"
    job.pop("renderLoopRevision", None)
    job.update(
        {
            "productName": "Lace Halter Sheer Dress for Siroino _Large",
            "buildRevision": "v1-large-lace-pass-2-final",
            "integratedPrefabAssetPath": f"{root}/Prefabs/Integrated/Siroino_Large/Siroino_Large_LaceHalter.prefab",
            "targetAvatarAssetPath": "Assets/_Local/Resolved/Siroino_Large.prefab",
            "targetSourcePath": "Assets/_Local/Resolved/SiroinoSotai_PC.fbx",
            "targetResolution": {
                "strategy": "repository-search",
                "profile": "Siroino _Large",
                "normalSizeFallbackAllowed": False,
                "searchRoots": ["Assets"],
                "excludePrefixes": ["Assets/GenWorks", "Assets/_Local/Jobs"],
                "prefab": {
                    "extensions": [".prefab"],
                    "includeRegex": "(?i)(siroino|sotai)",
                    "profileRegex": r"(?i)(^|[_\\/ .-])_?large([_\\/ .-]|$)",
                    "contentRegex": r"(?i)(^|[^A-Za-z])_?Large([^A-Za-z]|$)",
                    "preferredRegex": "(?i)(SiroinoSotai.*_Large|_Large.*SiroinoSotai)",
                },
                "source": {
                    "extensions": [".fbx"],
                    "includeRegex": "(?i)(siroino|sotai)",
                    "profileRegex": r"(?i)(^|[_\\/ .-])_?large([_\\/ .-]|$)",
                    "fallbackNameRegex": r"(?i)^SiroinoSotai_PC\.fbx$",
                    "preferredRegex": "(?i)(SiroinoSotai.*Large|Large.*SiroinoSotai)",
                },
            },
            "bodyShapeProfile": {
                "All_L": 1.0,
                "Chest_L": 1.0,
                "Hips_01_L": 1.0,
                "UpperLeg_L": 1.0,
                "Breasts_L": 0.65,
            },
        }
    )
    additions = [
        f"{root}/MaterialVariants.json",
        f"{root}/Evidence/improvement-loop.json",
        f"{root}/Models/SiroinoLaceHalterLarge.fbx.meta",
        f"{root}/Prefabs/Outfit/SiroinoLaceHalterLarge.prefab.meta",
        f"{root}/Previews/Poses/neutral.png",
        f"{root}/Previews/Poses/arms-up.png",
        f"{root}/Previews/Poses/arm-cross.png",
        f"{root}/Previews/Poses/crouch.png",
        f"{root}/Previews/Poses/sit.png",
        f"{root}/Previews/Poses/twist.png",
        f"{root}/Prefabs/Integrated/Siroino_Large/Siroino_Large_LaceHalter.prefab",
        f"{root}/Prefabs/Integrated/Siroino_Large/Siroino_Large_LaceHalter.prefab.meta",
    ]
    old_integrated = f"{root}/Prefabs/Integrated/SiroinoSotai/SiroinoSotai_LaceHalterLarge.prefab"
    delivery = [value for value in job.get("deliveryAssets", []) if value != old_integrated]
    for value in additions:
        if value not in delivery:
            delivery.append(value)
    job["deliveryAssets"] = delivery
    path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_prefab_directory_references() -> None:
    pattern = re.compile(r"(Assets/GenWorks/(?:Products/)?[^/\\\s\"']+)/Prefabs/")
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path.suffix.lower() in BINARY_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        updated = pattern.sub(lambda match: f"{match.group(1)}/Prefab/", text)
        if updated != text:
            path.write_text(updated, encoding="utf-8", newline="")


def patch_migrator() -> None:
    path = ROOT / "tools/migrate_genworks_layout_once.py"
    text = path.read_text(encoding="utf-8")
    old = '''        if all_prefabs:
            missing = [value for value in configured_paths if not (ROOT / value).is_file()]
            if missing:
                raise SystemExit(f"asset-backed product is missing configured prefabs: {product_id}: {missing}")
            classification = "ASSET_BACKED"
        else:
            if status not in {"WORKING", "REJECTED"}:
                raise SystemExit(f"prefabless product cannot claim {status}: {product_id}")
            classification = "PLANNED_CONTRACT"
'''
    new = '''        if all_prefabs:
            missing = [value for value in configured_paths if not (ROOT / value).is_file()]
            if missing:
                if status not in {"WORKING", "REJECTED"}:
                    raise SystemExit(f"asset-backed product is missing configured prefabs: {product_id}: {missing}")
                classification = "PARTIAL_CHECKPOINT"
            else:
                classification = "ASSET_BACKED"
        else:
            if status not in {"WORKING", "REJECTED"}:
                raise SystemExit(f"prefabless product cannot claim {status}: {product_id}")
            classification = "PLANNED_CONTRACT"
'''
    if old not in text:
        raise SystemExit("migration classification anchor not found")
    text = text.replace(old, new, 1)
    text = text.replace(
        "        (asset_backed if all_prefabs else planned).append(entry)\n",
        "        (asset_backed if classification == 'ASSET_BACKED' else planned).append(entry)\n",
        1,
    )
    path.write_text(text, encoding="utf-8")


def main() -> int:
    fold_lace_contract()
    normalize_prefab_directory_references()
    patch_migrator()
    run(sys.executable, "tools/migrate_genworks_layout_once.py")
    for job_path in sorted((ROOT / "config/products").glob("*/job.json")):
        run(
            sys.executable,
            "tools/update_product_hashes.py",
            "--root",
            f"Assets/GenWorks/{job_path.parent.name}",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
