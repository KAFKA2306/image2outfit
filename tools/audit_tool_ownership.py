#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
SCRIPT_FIELDS = {"buildScript", "hostedPoseScript", "productBuildScript"}
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
    paths = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        relative = raw.decode("utf-8", errors="strict")
        if relative.startswith(IGNORED_PREFIXES):
            continue
        paths.append(root / relative)
    return paths


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


def _imports(path: Path, text: str) -> set[str]:
    if path.suffix != ".py":
        return set()
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _semantic_hash(text: str) -> str | None:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    payload = ast.dump(tree, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _job_script_references(files: list[Path], root: Path) -> dict[str, list[dict[str, str]]]:
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


def audit(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    tracked = _tracked_files(root)
    texts: dict[Path, str] = {}
    imports: dict[Path, set[str]] = {}
    for path in tracked:
        text = _read_text(path)
        if text is None:
            continue
        texts[path] = text
        imports[path] = _imports(path, text)

    scripts = sorted(
        path for path in tracked if path.is_file() and path.parent == root / "tools" and path.suffix == ".py"
    )
    job_refs = _job_script_references(tracked, root)
    raw_groups: dict[str, list[str]] = defaultdict(list)
    semantic_groups: dict[str, list[str]] = defaultdict(list)
    inventory: list[dict[str, Any]] = []

    for script in scripts:
        relative = script.relative_to(root).as_posix()
        stem = script.stem
        module_names = {stem, f"tools.{stem}"}
        exact_references: list[str] = []
        module_references: list[str] = []
        basename_references: list[str] = []

        for source, text in texts.items():
            if source == script:
                continue
            source_relative = source.relative_to(root).as_posix()
            if relative in text:
                exact_references.append(source_relative)
            if source.name != script.name and script.name in text:
                basename_references.append(source_relative)
            if imports.get(source, set()) & module_names:
                module_references.append(source_relative)

        content = texts.get(script, "")
        raw_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        raw_groups[raw_hash].append(relative)
        semantic_hash = _semantic_hash(content)
        if semantic_hash:
            semantic_groups[semantic_hash].append(relative)

        job_owners = job_refs.get(relative, [])
        reference_set = sorted(set(exact_references + module_references))
        categories = {
            "taskfile": any(value == "Taskfile.yml" for value in exact_references),
            "workflow": any(value.startswith(".github/workflows/") for value in exact_references),
            "productJob": bool(job_owners),
            "test": any(value.startswith("tests/") for value in reference_set),
            "documentation": any(value in {"README.md", "AGENTS.md"} for value in exact_references),
            "internalImport": any(value.startswith("tools/") for value in module_references),
        }
        inventory.append(
            {
                "path": relative,
                "lineCount": len(content.splitlines()),
                "references": reference_set,
                "basenameMentions": sorted(set(basename_references) - set(reference_set)),
                "jobOwners": job_owners,
                "categories": categories,
                "unreferenced": not reference_set and not job_owners,
            }
        )

    duplicate_groups = [
        values for values in raw_groups.values() if len(values) > 1
    ]
    semantic_duplicate_groups = [
        values for values in semantic_groups.values() if len(values) > 1
    ]
    unreferenced = [item["path"] for item in inventory if item["unreferenced"]]
    product_scripts = [item for item in inventory if item["jobOwners"]]
    generic_scripts = [item for item in inventory if not item["jobOwners"]]

    return {
        "schemaVersion": 1,
        "passed": not unreferenced and not duplicate_groups and not semantic_duplicate_groups,
        "scriptCount": len(inventory),
        "genericScriptCount": len(generic_scripts),
        "productScriptCount": len(product_scripts),
        "unreferencedCount": len(unreferenced),
        "unreferenced": unreferenced,
        "duplicateGroups": duplicate_groups,
        "semanticDuplicateGroups": semantic_duplicate_groups,
        "inventory": inventory,
    }


def main() -> int:
    result = audit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
