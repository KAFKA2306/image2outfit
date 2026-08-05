#!/usr/bin/env python3
"""Crash-recoverable snapshot of one canonical product workspace."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from contract_io import read_json, write_json


@dataclass
class WorkspaceSnapshot:
    target: Path

    @property
    def backup(self) -> Path:
        return self.target.parent / f".{self.target.name}.last-good-workspace"

    @property
    def journal(self) -> Path:
        return self.target.parent / f".{self.target.name}.workspace-transaction.json"

    def _write(self, phase: str, had_original: bool) -> None:
        write_json(
            self.journal,
            {
                "schemaVersion": 1,
                "phase": phase,
                "target": self.target.name,
                "backup": self.backup.name,
                "hadOriginal": had_original,
            },
        )

    def recover(self) -> None:
        if not self.journal.exists():
            if self.backup.exists():
                raise RuntimeError(f"orphaned workspace backup: {self.backup}")
            return
        state = read_json(self.journal)
        phase = state.get("phase")
        had_original = state.get("hadOriginal") is True
        if phase in {"SNAPSHOTTED", "ROLLING_BACK"}:
            if self.target.exists():
                shutil.rmtree(self.target)
            if had_original:
                if not self.backup.exists():
                    raise RuntimeError(f"workspace backup missing: {self.backup}")
                shutil.copytree(self.backup, self.target)
            if self.backup.exists():
                shutil.rmtree(self.backup)
        elif phase == "COMMITTING":
            if self.backup.exists():
                shutil.rmtree(self.backup)
        else:
            raise RuntimeError(f"unknown workspace transaction phase: {phase!r}")
        self.journal.unlink(missing_ok=True)

    def begin(self) -> bool:
        self.recover()
        had_original = self.target.exists()
        if self.backup.exists():
            raise RuntimeError(f"stale workspace backup exists: {self.backup}")
        if had_original:
            shutil.copytree(self.target, self.backup)
        self._write("SNAPSHOTTED", had_original)
        return had_original

    def rollback(self, had_original: bool) -> None:
        self._write("ROLLING_BACK", had_original)
        if self.target.exists():
            shutil.rmtree(self.target)
        if had_original:
            if not self.backup.exists():
                raise RuntimeError(f"workspace backup missing: {self.backup}")
            shutil.copytree(self.backup, self.target)
        if self.backup.exists():
            shutil.rmtree(self.backup)
        self.journal.unlink(missing_ok=True)

    def commit(self, had_original: bool) -> None:
        if not self.target.exists():
            self.rollback(had_original)
            raise RuntimeError(f"canonical workspace disappeared: {self.target}")
        self._write("COMMITTING", had_original)
        if self.backup.exists():
            shutil.rmtree(self.backup)
        self.journal.unlink(missing_ok=True)
