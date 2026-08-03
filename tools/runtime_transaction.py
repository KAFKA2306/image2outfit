#!/usr/bin/env python3
"""Transactional protection for derived runtime directories."""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DirectoryTransaction:
    target: Path

    @property
    def backup(self) -> Path:
        return self.target.parent / f".{self.target.name}.last-good"

    @property
    def journal(self) -> Path:
        return self.target.parent / f".{self.target.name}.transaction.json"

    def _write_journal(self, phase: str, had_original: bool) -> None:
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.journal.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "phase": phase,
                    "target": self.target.name,
                    "backup": self.backup.name,
                    "hadOriginal": had_original,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def recover(self) -> None:
        if not self.journal.exists():
            if self.backup.exists() and not self.target.exists():
                self.backup.replace(self.target)
            elif self.backup.exists() and self.target.exists():
                raise RuntimeError(
                    "ambiguous interrupted transaction: "
                    f"{self.target} and {self.backup} both exist"
                )
            return

        try:
            state = json.loads(self.journal.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"invalid transaction journal: {self.journal}: {exc}"
            ) from exc

        phase = state.get("phase")
        had_original = state.get("hadOriginal") is True
        if phase == "PREPARED":
            if had_original:
                if self.target.exists() and not self.backup.exists():
                    pass
                elif self.backup.exists() and not self.target.exists():
                    self.backup.replace(self.target)
                else:
                    raise RuntimeError(
                        f"ambiguous prepared transaction: {self.target}"
                    )
            elif self.backup.exists():
                raise RuntimeError(
                    f"unexpected backup for new target: {self.backup}"
                )
        elif phase in {"PROTECTED", "ROLLING_BACK"}:
            if self.target.exists():
                shutil.rmtree(self.target)
            if had_original:
                if not self.backup.exists():
                    raise RuntimeError(
                        f"last-good backup is missing: {self.backup}"
                    )
                self.backup.replace(self.target)
            elif self.backup.exists():
                shutil.rmtree(self.backup)
        elif phase == "COMMITTING":
            if not self.target.exists():
                raise RuntimeError(f"committed target is missing: {self.target}")
            if self.backup.exists():
                shutil.rmtree(self.backup)
        else:
            raise RuntimeError(f"unknown transaction phase: {phase!r}")
        self.journal.unlink(missing_ok=True)

    def begin(self) -> bool:
        self.recover()
        had_original = self.target.exists()
        self._write_journal("PREPARED", had_original)
        if had_original:
            if self.backup.exists():
                raise RuntimeError(f"stale last-good backup exists: {self.backup}")
            self.target.replace(self.backup)
        self._write_journal("PROTECTED", had_original)
        return had_original

    def rollback(self, had_original: bool) -> None:
        self._write_journal("ROLLING_BACK", had_original)
        if self.target.exists():
            shutil.rmtree(self.target)
        if had_original:
            if not self.backup.exists():
                raise RuntimeError(f"last-good backup is missing: {self.backup}")
            self.backup.replace(self.target)
        elif self.backup.exists():
            shutil.rmtree(self.backup)
        self.journal.unlink(missing_ok=True)

    def commit(self, had_original: bool) -> None:
        if not self.target.exists():
            self.rollback(had_original)
            raise RuntimeError(f"new transaction target is missing: {self.target}")
        self._write_journal("COMMITTING", had_original)
        if self.backup.exists():
            shutil.rmtree(self.backup)
        self.journal.unlink(missing_ok=True)
