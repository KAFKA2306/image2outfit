#!/usr/bin/env python3
"""Audit the canonical Assets/GenWorks product layout."""
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "genworks-layout.json"


@dataclass
class Finding:
    level: str
    code: str
    path: str
    message: str


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def tracked_files(root: Path) -> list[Path]:
    try:
        output = subprocess.check_output(
            ["git", "ls-files", "-z"], cwd=root, stderr=subprocess.DEVNULL
        )
    except (OSError, subprocess.CalledProcessError):
        return [path for path in (root / "Assets").rglob("*") if path.is_file()]
    return [root / item.decode("utf-8") for item in output.split(b"\0") if item]


def load_manifests(
    root: Path, config: dict[str, Any]
) -> list[tuple[Path, dict[str, Any]]]:
    product_root = root / config["productRoot"]
    manifest_name = config["manifestName"]
    manifests: list[tuple[Path, dict[str, Any]]] = []
    if not product_root.exists():
        return manifests
    for path in sorted(product_root.glob(f"*/{manifest_name}")):
        try:
            manifests.append((path, read_json(path)))
        except (OSError, json.JSONDecodeError):
            manifests.append((path, {}))
    return manifests


def audit(root: Path = ROOT, config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    config = read_json(config_path)
    findings: list[Finding] = []
    canonical_root = root / config["canonicalRoot"]
    product_root = root / config["productRoot"]
    required_product_dirs = tuple(config["requiredProductDirectories"])

    if not canonical_root.is_dir():
        findings.append(
            Finding(
                "error",
                "missing-root",
                config["canonicalRoot"],
                "canonical GenWorks root is missing",
            )
        )
    if not product_root.is_dir():
        findings.append(
            Finding(
                "error",
                "missing-products",
                config["productRoot"],
                "product catalog root is missing",
            )
        )

    seen_ids: set[str] = set()
    manifests = load_manifests(root, config)
    for manifest_path, data in manifests:
        manifest_rel = relative(manifest_path, root)
        product_dir = manifest_path.parent
        product_id = str(data.get("productId", ""))
        expected_root = relative(product_dir, root)
        if data.get("schemaVersion") != 1:
            findings.append(
                Finding(
                    "error",
                    "manifest-schema",
                    manifest_rel,
                    "ProductManifest schemaVersion must be 1",
                )
            )
        if not product_id:
            findings.append(
                Finding(
                    "error",
                    "missing-product-id",
                    manifest_rel,
                    "productId is required",
                )
            )
        elif product_id in seen_ids:
            findings.append(
                Finding(
                    "error",
                    "duplicate-product-id",
                    manifest_rel,
                    f"duplicate productId: {product_id}",
                )
            )
        else:
            seen_ids.add(product_id)
        if data.get("productRoot") != expected_root:
            findings.append(
                Finding(
                    "error",
                    "root-mismatch",
                    manifest_rel,
                    f"productRoot must be {expected_root}",
                )
            )
        for directory in required_product_dirs:
            if not (product_dir / directory).exists():
                findings.append(
                    Finding(
                        "warning",
                        "missing-product-dir",
                        f"{expected_root}/{directory}",
                        "recommended product directory is missing",
                    )
                )
        for field in config["assetPathFields"]:
            value = data.get(field)
            if not value:
                continue
            candidate = root / str(value)
            if not candidate.exists():
                findings.append(
                    Finding(
                        "warning",
                        "missing-asset",
                        str(value),
                        f"manifest field {field} points to a missing asset",
                    )
                )
            elif (
                product_dir not in candidate.resolve().parents
                and candidate.resolve() != product_dir.resolve()
            ):
                findings.append(
                    Finding(
                        "error",
                        "asset-outside-product",
                        str(value),
                        f"manifest field {field} must stay inside its product root",
                    )
                )

    allowed_external = tuple(config["allowedExternalAssetRoots"])
    production_extensions = {
        value.lower() for value in config["productionExtensions"]
    }
    for file in tracked_files(root):
        try:
            rel = relative(file, root)
        except ValueError:
            continue
        if not rel.startswith("Assets/") or file.suffix.lower() not in production_extensions:
            continue
        if rel.startswith(config["canonicalRoot"] + "/"):
            continue
        if any(
            rel == prefix or rel.startswith(prefix + "/")
            for prefix in allowed_external
        ):
            continue
        findings.append(
            Finding(
                "warning",
                "legacy-production-asset",
                rel,
                "production-like asset remains outside Assets/GenWorks; migrate it or classify it as vendor/local",
            )
        )

    errors = [item for item in findings if item.level == "error"]
    return {
        "schemaVersion": 1,
        "passed": not errors,
        "canonicalRoot": config["canonicalRoot"],
        "products": len(manifests),
        "errors": len(errors),
        "warnings": sum(item.level == "warning" for item in findings),
        "findings": [asdict(item) for item in findings],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--warnings-as-errors", action="store_true")
    args = parser.parse_args()
    result = audit(args.root.resolve(), args.config.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 2 if (
        not result["passed"] or (args.warnings_as_errors and result["warnings"])
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
