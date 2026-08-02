#!/usr/bin/env python3
"""Reject unowned, duplicate, opaque, or excessively layered repository tools."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_FIELDS = {"buildScript", "hostedPoseScript", "productBuildScript"}
RESOURCE_SUFFIXES = {".b85", ".txt"}
MAX_PRODUCT_IMPORT_DEPTH = 3
IGNORED_PREFIXES = (
    ".git/",
    ".venv/",
    "Artifacts/",
    "Candidates/",
    "Release/",
    "Assets/_Local/",
)


def _tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [
        root / value
        for raw in result.stdout.split(b"\0")
        if raw
        for value in [raw.decode("utf-8", errors="strict")]
        if not value.startswith(IGNORED_PREFIXES)
    ]


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


def _tree(text: str, path: Path | None = None) -> ast.AST | None:
    try:
        return ast.parse(text, filename=str(path) if path else "<tool>")
    except SyntaxError:
        return None


def _imports(text: str, path: Path) -> set[str]:
    tree = _tree(text, path)
    if tree is None:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _semantic_hash(text: str) -> str | None:
    tree = _tree(text)
    if tree is None:
        return None
    payload = ast.dump(tree, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_exec_compile(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "exec"
        and bool(node.args)
        and isinstance(node.args[0], ast.Call)
        and isinstance(node.args[0].func, ast.Name)
        and node.args[0].func.id == "compile"
    )


def _opaque_loader(text: str, path: Path) -> bool:
    tree = _tree(text, path)
    if tree is None:
        return False
    imports = _imports(text, path)
    return "base64" in imports and "zlib" in imports and any(
        _is_exec_compile(node) for node in ast.walk(tree)
    )


def _job_script_references(
    files: list[Path], root: Path
) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = defaultdict(list)
    for path in files:
        relative = path.relative_to(root).as_posix()
        if not relative.startswith("config/products/") or path.name != "job.json":
            continue
        text = _read_text(path)
        if text is None:
            continue
        try:
            job = json.loads(text)
        except json.JSONDecodeError:
            continue
        product_id = str(job.get("id") or path.parent.name)
        for field in SCRIPT_FIELDS:
            value = job.get(field)
            if isinstance(value, str) and value.startswith("tools/"):
                result[value].append({"productId": product_id, "field": field})
    return dict(result)


def _import_graph(
    scripts: list[Path], texts: dict[Path, str], root: Path
) -> dict[str, set[str]]:
    modules = {path.stem: path.relative_to(root).as_posix() for path in scripts}
    graph: dict[str, set[str]] = {}
    for script in scripts:
        source = script.relative_to(root).as_posix()
        graph[source] = {
            modules[name]
            for name in _imports(texts.get(script, ""), script)
            if name in modules
        }
    return graph


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
                continue
            visit(child, [*trail, child])

    visit(start, [start])
    return len(best) - 1, best, cycle


def _resource_references(
    resource: Path,
    texts: dict[Path, str],
    root: Path,
) -> list[str]:
    tools_root = root / "tools"
    relative = resource.relative_to(root).as_posix()
    tools_relative = resource.relative_to(tools_root).as_posix()
    parent_parts = resource.parent.relative_to(tools_root).parts
    references: list[str] = []
    for source, text in texts.items():
        if source == resource:
            continue
        direct = relative in text or tools_relative in text or resource.name in text
        directory_expression = bool(parent_parts) and all(part in text for part in parent_parts)
        if direct or directory_expression:
            references.append(source.relative_to(root).as_posix())
    return sorted(set(references))


def audit(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    tracked = _tracked_files(root)
    texts = {
        path: text
        for path in tracked
        if (text := _read_text(path)) is not None
    }
    scripts = sorted(
        path
        for path in tracked
        if path.is_file() and path.parent == root / "tools" and path.suffix == ".py"
    )
    resources = sorted(
        path
        for path in tracked
        if path.is_file()
        and root / "tools" in path.parents
        and path.suffix.lower() in RESOURCE_SUFFIXES
    )
    job_refs = _job_script_references(tracked, root)
    graph = _import_graph(scripts, texts, root)

    raw_groups: dict[str, list[str]] = defaultdict(list)
    semantic_groups: dict[str, list[str]] = defaultdict(list)
    inventory: list[dict[str, Any]] = []
    for script in scripts:
        relative = script.relative_to(root).as_posix()
        content = texts.get(script, "")
        stem = script.stem
        module_names = {stem, f"tools.{stem}"}
        exact_references: list[str] = []
        module_references: list[str] = []
        basename_mentions: list[str] = []
        for source, text in texts.items():
            if source == script:
                continue
            source_relative = source.relative_to(root).as_posix()
            if relative in text:
                exact_references.append(source_relative)
            if source.name != script.name and script.name in text:
                basename_mentions.append(source_relative)
            if _imports(text, source) & module_names:
                module_references.append(source_relative)

        raw_groups[hashlib.sha256(content.encode("utf-8")).hexdigest()].append(relative)
        semantic = _semantic_hash(content)
        if semantic:
            semantic_groups[semantic].append(relative)

        job_owners = job_refs.get(relative, [])
        references = sorted(set(exact_references + module_references))
        opaque = _opaque_loader(content, script)
        inventory.append(
            {
                "path": relative,
                "lineCount": len(content.splitlines()),
                "references": references,
                "basenameMentions": sorted(set(basename_mentions) - set(references)),
                "jobOwners": job_owners,
                "imports": sorted(graph.get(relative, set())),
                "categories": {
                    "taskfile": "Taskfile.yml" in exact_references,
                    "workflow": any(value.startswith(".github/workflows/") for value in exact_references),
                    "productJob": bool(job_owners),
                    "test": any(value.startswith("tests/") for value in references),
                    "documentation": any(value in {"README.md", "AGENTS.md"} for value in exact_references),
                    "internalImport": any(value.startswith("tools/") for value in module_references),
                    "opaqueLoader": opaque,
                },
                "unreferenced": not references and not job_owners,
                "invalidOpaqueLoader": opaque and not job_owners,
            }
        )

    duplicate_groups = [values for values in raw_groups.values() if len(values) > 1]
    semantic_duplicate_groups = [values for values in semantic_groups.values() if len(values) > 1]
    unreferenced = [item["path"] for item in inventory if item["unreferenced"]]
    invalid_opaque_loaders = [item["path"] for item in inventory if item["invalidOpaqueLoader"]]

    resource_hashes: dict[str, list[str]] = defaultdict(list)
    resource_inventory: list[dict[str, Any]] = []
    for resource in resources:
        relative = resource.relative_to(root).as_posix()
        references = _resource_references(resource, texts, root)
        resource_hashes[hashlib.sha256(resource.read_bytes()).hexdigest()].append(relative)
        resource_inventory.append(
            {
                "path": relative,
                "bytes": resource.stat().st_size,
                "references": references,
                "unreferenced": not references,
            }
        )
    unreferenced_resources = [item["path"] for item in resource_inventory if item["unreferenced"]]
    duplicate_resource_groups = [values for values in resource_hashes.values() if len(values) > 1]

    product_import_chains: list[dict[str, Any]] = []
    excessive_chains: list[dict[str, Any]] = []
    import_cycles: list[dict[str, Any]] = []
    for entrypoint, owners in sorted(job_refs.items()):
        depth, chain, cycle = _longest_chain(entrypoint, graph)
        item = {
            "entrypoint": entrypoint,
            "owners": owners,
            "depth": depth,
            "chain": chain,
            "cycle": cycle,
        }
        product_import_chains.append(item)
        if depth > MAX_PRODUCT_IMPORT_DEPTH:
            excessive_chains.append(item)
        if cycle:
            import_cycles.append(item)

    versioned_non_product = [
        item["path"]
        for item in inventory
        if re.search(r"(?:^|_)(?:v|rev)\d+(?:_|$)", Path(item["path"]).stem)
        and not item["jobOwners"]
    ]
    failures = (
        unreferenced,
        duplicate_groups,
        semantic_duplicate_groups,
        invalid_opaque_loaders,
        unreferenced_resources,
        duplicate_resource_groups,
        excessive_chains,
        import_cycles,
        versioned_non_product,
    )
    return {
        "schemaVersion": 2,
        "passed": not any(failures),
        "scriptCount": len(inventory),
        "genericScriptCount": sum(not item["jobOwners"] for item in inventory),
        "productScriptCount": sum(bool(item["jobOwners"]) for item in inventory),
        "resourceCount": len(resource_inventory),
        "unreferencedCount": len(unreferenced),
        "unreferenced": unreferenced,
        "duplicateGroups": duplicate_groups,
        "semanticDuplicateGroups": semantic_duplicate_groups,
        "invalidOpaqueLoaders": invalid_opaque_loaders,
        "unreferencedResources": unreferenced_resources,
        "duplicateResourceGroups": duplicate_resource_groups,
        "maximumProductImportDepth": MAX_PRODUCT_IMPORT_DEPTH,
        "excessiveProductImportChains": excessive_chains,
        "productImportCycles": import_cycles,
        "versionedNonProductScripts": versioned_non_product,
        "productImportChains": product_import_chains,
        "inventory": inventory,
        "resourceInventory": resource_inventory,
    }


def main() -> int:
    result = audit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
