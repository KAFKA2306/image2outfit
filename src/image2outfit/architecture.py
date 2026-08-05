"""Repository-boundary audit for crystallized core logic and executable tools."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

FORBIDDEN_SRC_IMPORT_ROOTS = frozenset({"tools", "bpy", "bmesh", "mathutils"})


@dataclass(frozen=True, slots=True)
class BoundaryViolation:
    path: str
    imported_module: str
    line: int


def _imports(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append((node.module, node.lineno))
    return imports


def audit_src_boundaries(root: Path) -> tuple[BoundaryViolation, ...]:
    src_root = root / "src"
    violations: list[BoundaryViolation] = []
    for path in sorted(src_root.rglob("*.py")):
        for module, line in _imports(path):
            root_module = module.split(".", 1)[0]
            if root_module in FORBIDDEN_SRC_IMPORT_ROOTS:
                violations.append(
                    BoundaryViolation(
                        path=path.relative_to(root).as_posix(),
                        imported_module=module,
                        line=line,
                    )
                )
    return tuple(violations)
