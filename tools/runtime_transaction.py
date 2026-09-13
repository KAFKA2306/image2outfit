#!/usr/bin/env python3
"""Crash-recoverable transactions for runtime and canonical product state."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from contract_io import read_json, write_json


@dataclass
class DirectoryTransaction:
    """Protect one derived runtime directory by moving its last-good state aside."""

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
                    raise RuntimeError(f"ambiguous prepared transaction: {self.target}")
            elif self.backup.exists():
                raise RuntimeError(f"unexpected backup for new target: {self.backup}")
        elif phase in {"PROTECTED", "ROLLING_BACK"}:
            if self.target.exists():
                shutil.rmtree(self.target)
            if had_original:
                if not self.backup.exists():
                    raise RuntimeError(f"last-good backup is missing: {self.backup}")
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


@dataclass
class ReceiptBoundDirectoryTransaction(DirectoryTransaction):
    """Commit a release directory and its receipt as one recoverable result."""

    receipt: Path

    @property
    def receipt_backup(self) -> Path:
        return self.receipt.parent / f".{self.receipt.name}.last-good"

    @property
    def receipt_staging(self) -> Path:
        return self.receipt.parent / f".{self.receipt.name}.pending"

    def _write_pair_journal(
        self, phase: str, had_original: bool, had_receipt: bool
    ) -> None:
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.receipt.parent.mkdir(parents=True, exist_ok=True)
        self.journal.write_text(
            json.dumps(
                {
                    "schemaVersion": 2,
                    "phase": phase,
                    "target": self.target.name,
                    "backup": self.backup.name,
                    "hadOriginal": had_original,
                    "receipt": str(self.receipt),
                    "receiptBackup": str(self.receipt_backup),
                    "receiptStaging": str(self.receipt_staging),
                    "hadReceipt": had_receipt,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _restore_file(path: Path, backup: Path, had_original: bool) -> None:
        path.unlink(missing_ok=True)
        if had_original:
            if not backup.exists():
                raise RuntimeError(f"last-good receipt is missing: {backup}")
            backup.replace(path)
        else:
            backup.unlink(missing_ok=True)

    def _rollback_pair(self, had_original: bool, had_receipt: bool) -> None:
        if self.target.exists():
            shutil.rmtree(self.target)
        if had_original:
            if not self.backup.exists():
                raise RuntimeError(f"last-good backup is missing: {self.backup}")
            self.backup.replace(self.target)
        elif self.backup.exists():
            shutil.rmtree(self.backup)
        self._restore_file(self.receipt, self.receipt_backup, had_receipt)
        self.receipt_staging.unlink(missing_ok=True)

    def recover(self) -> None:
        if not self.journal.exists():
            if (
                self.backup.exists()
                or self.receipt_backup.exists()
                or self.receipt_staging.exists()
            ):
                raise RuntimeError("orphaned release-pair transaction state")
            return

        try:
            state = json.loads(self.journal.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"invalid transaction journal: {self.journal}: {exc}"
            ) from exc

        phase = state.get("phase")
        had_original = state.get("hadOriginal") is True
        had_receipt = state.get("hadReceipt") is True
        if phase == "PREPARED":
            if self.backup.exists() and not self.target.exists():
                self.backup.replace(self.target)
            if self.receipt_backup.exists() and not self.receipt.exists():
                self.receipt_backup.replace(self.receipt)
            self.receipt_staging.unlink(missing_ok=True)
        elif phase in {"PROTECTED", "ROLLING_BACK", "COMMITTING"}:
            self._rollback_pair(had_original, had_receipt)
        elif phase == "COMMITTED":
            if not self.target.exists() or not self.receipt.exists():
                raise RuntimeError("committed release pair is incomplete")
            if self.backup.exists():
                shutil.rmtree(self.backup)
            self.receipt_backup.unlink(missing_ok=True)
            self.receipt_staging.unlink(missing_ok=True)
        else:
            raise RuntimeError(f"unknown transaction phase: {phase!r}")
        self.journal.unlink(missing_ok=True)

    def begin(self) -> bool:
        self.recover()
        had_original = self.target.exists()
        had_receipt = self.receipt.exists()
        self._write_pair_journal("PREPARED", had_original, had_receipt)
        if had_original:
            self.target.replace(self.backup)
        if had_receipt:
            self.receipt.replace(self.receipt_backup)
        self._write_pair_journal("PROTECTED", had_original, had_receipt)
        return had_original

    def rollback(self, had_original: bool) -> None:
        state = json.loads(self.journal.read_text(encoding="utf-8"))
        had_receipt = state.get("hadReceipt") is True
        self._write_pair_journal("ROLLING_BACK", had_original, had_receipt)
        self._rollback_pair(had_original, had_receipt)
        self.journal.unlink(missing_ok=True)

    def commit(self, had_original: bool) -> None:
        state = json.loads(self.journal.read_text(encoding="utf-8"))
        had_receipt = state.get("hadReceipt") is True
        if not self.target.exists() or not self.receipt_staging.is_file():
            self.rollback(had_original)
            raise RuntimeError("release payload and staged receipt are both required")
        self._write_pair_journal("COMMITTING", had_original, had_receipt)
        self.receipt_staging.replace(self.receipt)
        # Durable logical commit point. Cleanup happens only after this marker.
        self._write_pair_journal("COMMITTED", had_original, had_receipt)
        if self.backup.exists():
            shutil.rmtree(self.backup)
        self.receipt_backup.unlink(missing_ok=True)
        self.journal.unlink(missing_ok=True)


@dataclass
class WorkspaceSnapshot:
    """Protect one canonical product workspace by copying its last-good state."""

    target: Path

    @property
    def backup(self) -> Path:
        return self.target.parent / f".{self.target.name}.last-good-workspace"

    @property
    def journal(self) -> Path:
        return self.target.parent / f".{self.target.name}.workspace-transaction.json"

    def _write_journal(self, phase: str, had_original: bool) -> None:
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
        self._write_journal("SNAPSHOTTED", had_original)
        return had_original

    def rollback(self, had_original: bool) -> None:
        self._write_journal("ROLLING_BACK", had_original)
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
        self._write_journal("COMMITTING", had_original)
        if self.backup.exists():
            shutil.rmtree(self.backup)
        self.journal.unlink(missing_ok=True)
