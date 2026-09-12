#!/usr/bin/env python3
"""Fail-closed repository write boundary for external pipeline stage commands."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from runtime_transaction import WorkspaceSnapshot


class UndeclaredOutputWriteError(RuntimeError):
    """Raised after an external stage mutates paths outside its declared outputs."""

    failure_code = "UNDECLARED_OUTPUT_WRITE"

    def __init__(self, affected_paths: Iterable[str]) -> None:
        self.affected_paths = tuple(sorted(set(affected_paths)))
        detail = ", ".join(self.affected_paths)
        super().__init__(f"{self.failure_code}: {detail}")


@dataclass(frozen=True, slots=True)
class _PathSnapshot:
    exists: bool
    kind: str = ""
    payload: bytes = b""
    mode: int = 0

    @classmethod
    def capture(cls, path: Path) -> _PathSnapshot:
        if path.is_symlink():
            return cls(
                True,
                "symlink",
                os.readlink(path).encode("utf-8", errors="surrogateescape"),
                stat.S_IMODE(path.lstat().st_mode),
            )
        if not path.exists():
            return cls(False)
        if path.is_file():
            return cls(True, "file", path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        return cls(True, "other", b"", stat.S_IMODE(path.stat().st_mode))

    def signature(self) -> tuple[bool, str, str, int]:
        digest = hashlib.sha256(self.payload).hexdigest() if self.exists else ""
        return self.exists, self.kind, digest, self.mode

    def restore(self, path: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.exists() and not self.exists:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        if not self.exists:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.kind == "symlink":
            target = self.payload.decode("utf-8", errors="surrogateescape")
            path.symlink_to(target)
        elif self.kind == "file":
            path.write_bytes(self.payload)
            path.chmod(self.mode)
        elif not path.exists():
            path.mkdir(parents=True, exist_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_state(root: Path) -> dict[str, tuple[str, str, int]]:
    if not root.exists():
        return {}
    state: dict[str, tuple[str, str, int]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            state[relative] = ("symlink", os.readlink(path), stat.S_IMODE(path.lstat().st_mode))
        elif path.is_file():
            state[relative] = ("file", _sha256(path), stat.S_IMODE(path.stat().st_mode))
    return state


class RepositoryWriteBoundary:
    """Detect and roll back final filesystem mutations not owned by one stage."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.products_root = self.root / ".image2outfit" / "products"
        self._products_snapshot: WorkspaceSnapshot | None = None
        self._products_had_original = False
        self._products_before: dict[str, tuple[str, str, int]] = {}
        self._dirty_before: set[str] = set()
        self._dirty_snapshots: dict[str, _PathSnapshot] = {}
        self._untracked_before: set[str] = set()
        self._untracked_snapshots: dict[str, _PathSnapshot] = {}
        self._begun = False

    def _git_paths(self, *args: str) -> set[str]:
        result = subprocess.run(
            ["git", *args, "-z"],
            cwd=self.root,
            check=True,
            capture_output=True,
        )
        return {
            item.decode("utf-8", errors="surrogateescape")
            for item in result.stdout.split(b"\0")
            if item
        }

    def _dirty_paths(self) -> set[str]:
        return self._git_paths("diff", "--name-only") | self._git_paths(
            "diff", "--cached", "--name-only"
        )

    def _untracked_paths(self) -> set[str]:
        return self._git_paths("ls-files", "--others", "--exclude-standard")

    def begin(self) -> None:
        if self._begun:
            raise RuntimeError("repository write boundary already started")
        self._dirty_before = self._dirty_paths()
        self._dirty_snapshots = {
            name: _PathSnapshot.capture(self.root / name) for name in self._dirty_before
        }
        self._untracked_before = self._untracked_paths()
        self._untracked_snapshots = {
            name: _PathSnapshot.capture(self.root / name)
            for name in self._untracked_before
        }
        if self.products_root.exists():
            self._products_snapshot = WorkspaceSnapshot(self.products_root)
            self._products_had_original = self._products_snapshot.begin()
            self._products_before = _tree_state(self._products_snapshot.backup)
        else:
            self._products_before = {}
        self._begun = True

    def _relative_allowed(self, path: Path) -> str:
        resolved = path.resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise ValueError(f"allowed stage output escapes repository: {path}")
        return resolved.relative_to(self.root).as_posix()

    def _changed_git_paths(self) -> set[str]:
        dirty_after = self._dirty_paths()
        untracked_after = self._untracked_paths()
        changed: set[str] = set()
        for name in self._dirty_before | dirty_after:
            if name not in self._dirty_before:
                changed.add(name)
                continue
            before = self._dirty_snapshots[name].signature()
            after = _PathSnapshot.capture(self.root / name).signature()
            if before != after:
                changed.add(name)
        for name in self._untracked_before | untracked_after:
            if name.startswith(".image2outfit/products/"):
                continue
            if name not in self._untracked_before:
                changed.add(name)
                continue
            before = self._untracked_snapshots[name].signature()
            after = _PathSnapshot.capture(self.root / name).signature()
            if before != after:
                changed.add(name)
        return changed

    def _changed_product_paths(self) -> set[str]:
        after = _tree_state(self.products_root)
        changed = {
            name
            for name in self._products_before.keys() | after.keys()
            if self._products_before.get(name) != after.get(name)
        }
        return {f".image2outfit/products/{name}" for name in changed}

    def changed_paths(self) -> tuple[str, ...]:
        if not self._begun:
            raise RuntimeError("repository write boundary has not started")
        return tuple(sorted(self._changed_git_paths() | self._changed_product_paths()))

    def _restore_git(self) -> None:
        changed = self._changed_git_paths()
        for name in sorted(changed):
            path = self.root / name
            if name in self._dirty_snapshots:
                self._dirty_snapshots[name].restore(path)
                continue
            if name in self._untracked_snapshots:
                self._untracked_snapshots[name].restore(path)
                continue
            tracked = subprocess.run(
                ["git", "ls-files", "--error-unmatch", "--", name],
                cwd=self.root,
                check=False,
                capture_output=True,
            ).returncode == 0
            if tracked:
                subprocess.run(
                    ["git", "restore", "--worktree", "--source=HEAD", "--", name],
                    cwd=self.root,
                    check=True,
                    capture_output=True,
                )
            elif path.is_symlink() or path.is_file():
                path.unlink()
            elif path.exists():
                shutil.rmtree(path)

    def rollback(self) -> None:
        if not self._begun:
            return
        self._restore_git()
        if self._products_snapshot is not None:
            self._products_snapshot.rollback(self._products_had_original)
        elif self.products_root.exists():
            shutil.rmtree(self.products_root)
        self._begun = False

    def commit(self) -> None:
        if not self._begun:
            raise RuntimeError("repository write boundary has not started")
        if self._products_snapshot is not None:
            self._products_snapshot.commit(self._products_had_original)
        self._begun = False

    def verify_and_commit(self, allowed_paths: Iterable[Path]) -> tuple[str, ...]:
        allowed = {self._relative_allowed(path) for path in allowed_paths}
        changed = set(self.changed_paths())
        undeclared = tuple(sorted(changed - allowed))
        if undeclared:
            self.rollback()
            raise UndeclaredOutputWriteError(undeclared)
        self.commit()
        return tuple(sorted(changed))
