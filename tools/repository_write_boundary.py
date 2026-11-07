#!/usr/bin/env python3
"""Fail-closed repository write boundary for external pipeline stage commands."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import tempfile
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
    digest: str = ""
    mode: int = 0
    backup_path: Path | None = None
    symlink_target: str = ""

    @classmethod
    def capture(cls, path: Path, *, backup_path: Path | None = None) -> _PathSnapshot:
        if path.is_symlink():
            target = os.readlink(path)
            encoded = target.encode("utf-8", errors="surrogateescape")
            return cls(
                True,
                "symlink",
                hashlib.sha256(encoded).hexdigest(),
                stat.S_IMODE(path.lstat().st_mode),
                symlink_target=target,
            )
        if not path.exists():
            return cls(False)
        if path.is_file():
            mode = stat.S_IMODE(path.stat().st_mode)
            digest = hashlib.sha256()
            if backup_path is None:
                content_digest = _sha256(path)
            else:
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("rb") as source, backup_path.open("xb") as backup:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(block)
                        backup.write(block)
                backup_path.chmod(mode)
                content_digest = digest.hexdigest()
            return cls(
                True,
                "file",
                content_digest,
                mode,
                backup_path=backup_path,
            )
        return cls(True, "other", mode=stat.S_IMODE(path.stat().st_mode))

    def signature(self) -> tuple[bool, str, str, int]:
        return self.exists, self.kind, self.digest, self.mode

    def restore(self, path: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.exists() and (not self.exists or self.kind in {"file", "symlink"}):
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        if not self.exists:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.kind == "symlink":
            path.symlink_to(self.symlink_target)
        elif self.kind == "file":
            if self.backup_path is None or not self.backup_path.is_file():
                raise RuntimeError(f"file snapshot is missing for {path}")
            shutil.copyfile(self.backup_path, path)
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
            state[relative] = (
                "symlink",
                os.readlink(path),
                stat.S_IMODE(path.lstat().st_mode),
            )
        elif path.is_file():
            state[relative] = (
                "file",
                _sha256(path),
                stat.S_IMODE(path.stat().st_mode),
            )
    return state


class RepositoryWriteBoundary:
    """Detect and roll back final filesystem mutations not owned by one stage."""

    def __init__(
        self,
        root: Path,
        *,
        product_id: str | None = None,
        product_workspace_output: bool = False,
    ) -> None:
        self.root = root.resolve()
        self.products_root = self.root / ".image2outfit" / "products"
        if product_id is not None and not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]*", product_id
        ):
            raise ValueError(f"invalid product id for write boundary: {product_id!r}")
        self.product_id = product_id
        self.product_runtime = (
            self.products_root / product_id if product_id is not None else None
        )
        self.product_assets = (
            self.root / "Assets" / "GenWorks" / product_id
            if product_id is not None and product_workspace_output
            else None
        )
        for output_root in (self.product_runtime, self.product_assets):
            if output_root is None:
                continue
            resolved = output_root.resolve()
            if resolved != output_root or (
                resolved != self.root and self.root not in resolved.parents
            ):
                raise ValueError(
                    f"product output root must be a real directory inside repository: "
                    f"{output_root}"
                )
        self._scope_snapshots: list[tuple[WorkspaceSnapshot, bool]] = []
        self._scope_before: dict[str, dict[str, tuple[str, str, int]]] = {}
        self._dirty_before: set[str] = set()
        self._dirty_snapshots: dict[str, _PathSnapshot] = {}
        self._untracked_before: set[str] = set()
        self._untracked_snapshots: dict[str, _PathSnapshot] = {}
        self._untracked_metadata_before: dict[
            str, tuple[str, int, int, int, int, int]
        ] = {}
        self._snapshot_temp: tempfile.TemporaryDirectory | None = None
        self._begun = False

    @staticmethod
    def _metadata_signature(path: Path) -> tuple[str, int, int, int, int, int]:
        try:
            stat_result = path.lstat()
        except FileNotFoundError:
            return "missing", 0, 0, 0, 0, 0
        if stat.S_ISLNK(stat_result.st_mode):
            kind = "symlink:" + os.readlink(path)
        elif getattr(stat_result, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            # WSL links are opaque Windows reparse points. Observe the entry,
            # never traverse an unrelated target which Windows cannot open.
            kind = f"reparse:{getattr(stat_result, 'st_reparse_tag', 0):x}"
        elif stat.S_ISREG(stat_result.st_mode):
            kind = "file"
        elif stat.S_ISDIR(stat_result.st_mode):
            kind = "directory"
        else:
            kind = "other"
        return (
            kind,
            int(getattr(stat_result, "st_size", 0)),
            int(getattr(stat_result, "st_mtime_ns", 0)),
            int(getattr(stat_result, "st_ctime_ns", 0)),
            int(getattr(stat_result, "st_ino", 0)),
            stat.S_IMODE(stat_result.st_mode),
        )

    def _is_scoped_output(self, path: Path) -> bool:
        lexical = path.absolute()
        roots = [root for root in (self.product_runtime, self.product_assets) if root]
        if not any(lexical == root or root in lexical.parents for root in roots):
            return False
        resolved = path.resolve()
        roots = [root for root in (self.product_runtime, self.product_assets) if root]
        return any(
            resolved == root.resolve() or root.resolve() in resolved.parents
            for root in roots
        )

    def _scoped_snapshots(self) -> list[WorkspaceSnapshot]:
        if self.product_id is None or self.product_runtime is None:
            return []
        transaction_key = hashlib.sha256(
            self.product_id.encode("utf-8")
        ).hexdigest()[:10]
        transaction_root = self.root / ".image2outfit"
        runtime_backup = transaction_root / f".pwb-{transaction_key}"
        runtime_journal = self.products_root / f".{self.product_id}.pwb.json"
        snapshots = [
            WorkspaceSnapshot(
                self.product_runtime,
                backup_path_override=runtime_backup,
                journal_path_override=runtime_journal,
            )
        ]
        if self.product_assets is not None:
            snapshots.append(
                WorkspaceSnapshot(
                    self.product_assets,
                    backup_path_override=transaction_root / f".awb-{transaction_key}",
                    journal_path_override=(
                        transaction_root / f".awb-{transaction_key}.json"
                    ),
                )
            )
        return snapshots

    def _capture_paths(
        self, names: set[str], namespace: str
    ) -> dict[str, _PathSnapshot]:
        if self._snapshot_temp is None:
            raise RuntimeError("snapshot storage has not been initialized")
        snapshot_root = Path(self._snapshot_temp.name) / namespace
        snapshots: dict[str, _PathSnapshot] = {}
        for index, name in enumerate(sorted(names)):
            snapshots[name] = _PathSnapshot.capture(
                self.root / name,
                backup_path=snapshot_root / f"{index:08d}.snapshot",
            )
        return snapshots

    def _cleanup_snapshots(self) -> None:
        if self._snapshot_temp is not None:
            self._snapshot_temp.cleanup()
            self._snapshot_temp = None

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
        snapshot_parent = self.root / ".image2outfit"
        snapshot_parent.mkdir(parents=True, exist_ok=True)
        self._snapshot_temp = tempfile.TemporaryDirectory(
            prefix="repository-write-boundary-", dir=snapshot_parent
        )
        try:
            self._dirty_before = self._dirty_paths()
            self._dirty_snapshots = self._capture_paths(self._dirty_before, "dirty")
            self._untracked_before = self._untracked_paths()
            if self.product_id is None:
                self._untracked_snapshots = self._capture_paths(
                    self._untracked_before, "untracked"
                )
            else:
                # The pipeline executors are product-bound: runtime artifacts go
                # under this product's runtime tree, and only build/finalize may
                # write to its Assets/GenWorks workspace. Keep lightweight
                # metadata for unrelated untracked inputs without duplicating
                # benchmark payloads; the scoped workspaces receive full backups.
                self._untracked_metadata_before = {
                    name: self._metadata_signature(self.root / name)
                    for name in self._untracked_before
                    if not self._is_scoped_output(self.root / name)
                }
            if self.product_id is not None:
                for snapshot in self._scoped_snapshots():
                    had_original = snapshot.begin()
                    self._scope_snapshots.append((snapshot, had_original))
                    scope_name = snapshot.target.relative_to(self.root).as_posix()
                    self._scope_before[scope_name] = (
                        _tree_state(snapshot.backup) if had_original else {}
                    )
            elif self.products_root.exists():
                # The products tree contains deeply nested OSS evidence. Keep
                # this sibling backup short so Windows path limits do not make
                # the snapshot itself longer than the protected files.
                snapshot = WorkspaceSnapshot(
                    self.products_root, backup_name=".pwb"
                )
                had_original = snapshot.begin()
                self._scope_snapshots.append((snapshot, had_original))
                self._scope_before[self.products_root.relative_to(self.root).as_posix()] = (
                    _tree_state(snapshot.backup) if had_original else {}
                )
            else:
                self._scope_before = {}
            self._begun = True
        except Exception:
            for snapshot, had_original in reversed(self._scope_snapshots):
                try:
                    snapshot.rollback(had_original)
                except Exception:
                    pass
            self._scope_snapshots.clear()
            self._cleanup_snapshots()
            raise

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
            path = self.root / name
            if self.product_id is None and name.startswith(".image2outfit/products/"):
                continue
            if self.product_id is not None and self._is_scoped_output(path):
                continue
            if name not in self._untracked_before:
                changed.add(name)
                continue
            before_snapshot = self._untracked_snapshots.get(name)
            before = (
                before_snapshot.signature()
                if before_snapshot is not None
                else self._untracked_metadata_before.get(name)
            )
            after = (
                _PathSnapshot.capture(path).signature()
                if before_snapshot is not None
                else self._metadata_signature(path)
            )
            if before != after:
                changed.add(name)
        return changed

    def _changed_product_paths(self) -> set[str]:
        changed_paths: set[str] = set()
        for snapshot, _ in self._scope_snapshots:
            scope_name = snapshot.target.relative_to(self.root).as_posix()
            before = self._scope_before.get(scope_name, {})
            after = _tree_state(snapshot.target)
            changed = {
                name
                for name in before.keys() | after.keys()
                if before.get(name) != after.get(name)
            }
            changed_paths.update(f"{scope_name}/{name}" for name in changed)
        return changed_paths

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
            tracked = (
                subprocess.run(
                    ["git", "ls-files", "--error-unmatch", "--", name],
                    cwd=self.root,
                    check=False,
                    capture_output=True,
                ).returncode
                == 0
            )
            if tracked:
                subprocess.run(
                    ["git", "restore", "--worktree", "--source=HEAD", "--", name],
                    cwd=self.root,
                    check=True,
                    capture_output=True,
                )
            else:
                # No content backup exists for unrelated untracked data. Never
                # delete or overwrite it during rollback; report that recovery
                # needs attention instead.
                raise RuntimeError(
                    "cannot safely roll back an untracked path outside the declared "
                    f"product workspace: {name}"
                )

    def rollback(self) -> None:
        if not self._begun:
            return
        restore_error: Exception | None = None
        try:
            self._restore_git()
        except Exception as exc:
            restore_error = exc
        for snapshot, had_original in reversed(self._scope_snapshots):
            try:
                snapshot.rollback(had_original)
            except Exception as exc:
                if restore_error is None:
                    restore_error = exc
        self._begun = False
        self._cleanup_snapshots()
        if restore_error is not None:
            raise RuntimeError(
                "repository write-boundary rollback was incomplete: "
                f"{restore_error}"
            ) from restore_error

    def commit(self) -> None:
        if not self._begun:
            raise RuntimeError("repository write boundary has not started")
        for snapshot, had_original in self._scope_snapshots:
            snapshot.commit(had_original)
        self._begun = False
        self._cleanup_snapshots()

    def verify_and_commit(self, allowed_paths: Iterable[Path]) -> tuple[str, ...]:
        allowed = {self._relative_allowed(path) for path in allowed_paths}
        changed = set(self.changed_paths())
        undeclared = tuple(sorted(changed - allowed))
        if undeclared:
            self.rollback()
            raise UndeclaredOutputWriteError(undeclared)
        self.commit()
        return tuple(sorted(changed))
