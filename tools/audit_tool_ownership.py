#!/usr/bin/env python3
"""Audit ownership, duplication, opaque loaders, resources, and import depth."""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_FIELDS = {"buildScript", "hostedPoseScript", "productBuildScript"}
RESOURCE_SUFFIXES = {".b85", ".txt"}
MAX_PRODUCT_IMPORT_DEPTH = 4
IGNORED_PREFIXES = (
    ".git/",
    ".venv/",
    "Artifacts/",
    "Candidates/",
    "Release/",
    "Assets/_Local/",
)


def _tracked(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
    )
    return [
        root / value
        for raw in result.stdout.split(b"\0")
        if raw
        for value in [raw.decode("utf-8")]
        if not value.startswith(IGNORED_PREFIXES)
    ]


def _text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


def _tree(text: str, path: Path | None = None) -> ast.AST | None:
    try:
        return ast.parse(text, filename=str(path or "<tool>"))
    except SyntaxError:
        return None


def _imports(text: str, path: Path) -> set[str]:
    tree = _tree(text, path)
    if tree is None:
        return set()
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def _semantic_hash(text: str) -> str | None:
    tree = _tree(text)
    if tree is None:
        return None
    payload = ast.dump(tree, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _opaque_loader(text: str, path: Path) -> bool:
    tree = _tree(text, path)
    imports = _imports(text, path)
    if tree is None or not {"base64", "zlib"}.issubset(imports):
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "exec" or not node.args:
            continue
        value = node.args[0]
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "compile"
        ):
            return True
    return False


def _job_owners(files: list[Path], root: Path) -> dict[str, list[dict[str, str]]]:
    owners: dict[str, list[dict[str, str]]] = defaultdict(list)
    for path in files:
        relative = path.relative_to(root).as_posix()
        if not relative.startswith("config/products/") or path.name != "job.json":
            continue
        try:
            job = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        product_id = str(job.get("id") or path.parent.name)
        for field in SCRIPT_FIELDS:
            value = job.get(field)
            if isinstance(value, str) and value.startswith("tools/"):
                owners[value].append({"productId": product_id, "field": field})
    return dict(owners)


def _longest_chain(
    start: str, graph: dict[str, set[str]]
) -> tuple[int, list[str], bool]:
    best = [start]
    cycle = False

    def visit(node: str, trail: list[str]) -> None:
        nonlocal best, cycle
        if len(trail) > len(best):
            best = trail
        for child in sorted(graph.get(node, set())):
            if child in trail:
                cycle = True
            else:
                visit(child, [*trail, child])

    visit(start, [start])
    return len(best) - 1, best, cycle


def audit(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    files = _tracked(root)
    texts = {path: value for path in files if (value := _text(path)) is not None}
    scripts = sorted(
        path
        for path in files
        if path.is_file() and path.parent == root / "tools" and path.suffix == ".py"
    )
    owners = _job_owners(files, root)
    modules = {path.stem: path.relative_to(root).as_posix() for path in scripts}
    graph = {
        path.relative_to(root).as_posix(): {
            modules[name]
            for name in _imports(texts.get(path, ""), path)
            if name in modules
        }
        for path in scripts
    }

    raw_groups: dict[str, list[str]] = defaultdict(list)
    semantic_groups: dict[str, list[str]] = defaultdict(list)
    inventory: list[dict[str, Any]] = []
    for script in scripts:
        relative = script.relative_to(root).as_posix()
        content = texts.get(script, "")
        references: set[str] = set()
        for source, text in texts.items():
            if source == script:
                continue
            source_relative = source.relative_to(root).as_posix()
            if relative in text or script.stem in _imports(text, source):
                references.add(source_relative)
        job_owners = owners.get(relative, [])
        raw_groups[hashlib.sha256(content.encode()).hexdigest()].append(relative)
        semantic = _semantic_hash(content)
        if semantic:
            semantic_groups[semantic].append(relative)
        opaque = _opaque_loader(content, script)
        inventory.append(
            {
                "path": relative,
                "lineCount": len(content.splitlines()),
                "references": sorted(references),
                "jobOwners": job_owners,
                "imports": sorted(graph[relative]),
                "unreferenced": not references and not job_owners,
                "invalidOpaqueLoader": opaque and not job_owners,
            }
        )

    resources = sorted(
        path
        for path in files
        if path.is_file()
        and root / "tools" in path.parents
        and path.suffix.lower() in RESOURCE_SUFFIXES
    )
    resource_inventory = []
    resource_hashes: dict[str, list[str]] = defaultdict(list)
    for resource in resources:
        relative = resource.relative_to(root).as_posix()
        tools_relative = resource.relative_to(root / "tools").as_posix()
        references = sorted(
            source.relative_to(root).as_posix()
            for source, text in texts.items()
            if source != resource
            and (
                relative in text
                or tools_relative in text
                or resource.name in text
                or all(
                    part in text
                    for part in resource.parent.relative_to(root / "tools").parts
                )
            )
        )
        resource_hashes[hashlib.sha256(resource.read_bytes()).hexdigest()].append(relative)
        resource_inventory.append(
            {"path": relative, "references": references, "unreferenced": not references}
        )

    product_chains = []
    excessive_chains = []
    cycles = []
    for entrypoint, entry_owners in sorted(owners.items()):
        depth, chain, cycle = _longest_chain(entrypoint, graph)
        item = {
            "entrypoint": entrypoint,
            "owners": entry_owners,
            "depth": depth,
            "chain": chain,
            "cycle": cycle,
        }
        product_chains.append(item)
        if depth > MAX_PRODUCT_IMPORT_DEPTH:
            excessive_chains.append(item)
        if cycle:
            cycles.append(item)

    result = {
        "schemaVersion": 1,
        "scriptCount": len(inventory),
        "unreferenced": [item["path"] for item in inventory if item["unreferenced"]],
        "duplicateGroups": [values for values in raw_groups.values() if len(values) > 1],
        "semanticDuplicateGroups": [
            values for values in semantic_groups.values() if len(values) > 1
        ],
        "invalidOpaqueLoaders": [
            item["path"] for item in inventory if item["invalidOpaqueLoader"]
        ],
        "unreferencedResources": [
            item["path"] for item in resource_inventory if item["unreferenced"]
        ],
        "duplicateResourceGroups": [
            values for values in resource_hashes.values() if len(values) > 1
        ],
        "maximumProductImportDepth": MAX_PRODUCT_IMPORT_DEPTH,
        "excessiveProductImportChains": excessive_chains,
        "productImportCycles": cycles,
        "productImportChains": product_chains,
        "inventory": inventory,
        "resourceInventory": resource_inventory,
    }
    result["passed"] = not any(
        result[field]
        for field in (
            "unreferenced",
            "duplicateGroups",
            "semanticDuplicateGroups",
            "invalidOpaqueLoaders",
            "unreferencedResources",
            "duplicateResourceGroups",
            "excessiveProductImportChains",
            "productImportCycles",
        )
    )
    return result


def main() -> int:
    result = audit()
    compact = {
        "schemaVersion": result["schemaVersion"],
        "passed": result["passed"],
        "scriptCount": result["scriptCount"],
        "unreferenced": result["unreferenced"],
        "duplicateGroups": result["duplicateGroups"],
        "semanticDuplicateGroups": result["semanticDuplicateGroups"],
        "invalidOpaqueLoaders": result["invalidOpaqueLoaders"],
        "unreferencedResources": result["unreferencedResources"],
        "duplicateResourceGroups": result["duplicateResourceGroups"],
        "maximumProductImportDepth": result["maximumProductImportDepth"],
        "excessiveProductImportChains": result["excessiveProductImportChains"],
        "productImportCycles": result["productImportCycles"],
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
