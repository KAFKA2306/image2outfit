#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import customer_quality
import release_gate as legacy


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
                    f"ambiguous interrupted transaction: {self.target} and {self.backup} both exist"
                )
            return

        try:
            state = json.loads(self.journal.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"invalid transaction journal: {self.journal}: {exc}") from exc

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


def _augment_audit(artifact: Path, values: dict[str, Any]) -> None:
    audit_path = artifact / "audit.json"
    audit = legacy.read(audit_path)
    audit.setdefault("schemaVersion", 2)
    audit["stateProtection"] = values
    legacy.write(audit_path, audit)


def _run_candidate(job_path: Path, job: dict[str, Any], policy: dict[str, Any]) -> int:
    candidate = legacy.path(job["candidateDir"])
    release = legacy.path(job["releaseDir"])
    artifact = legacy.path(job["artifactDir"])
    candidate_tx = DirectoryTransaction(candidate)
    release_tx = DirectoryTransaction(release)
    candidate_had_original = candidate_tx.begin()
    release_started = False
    release_had_original = False

    try:
        release_had_original = release_tx.begin()
        release_started = True
        result = legacy.run_candidate(job_path, job, policy)
        release_tx.rollback(release_had_original)
        release_started = False
        if result == 0:
            candidate_tx.commit(candidate_had_original)
        else:
            candidate_tx.rollback(candidate_had_original)
        _augment_audit(
            artifact,
            {
                "candidateLastGoodProtected": True,
                "previousCandidateExisted": candidate_had_original,
                "previousCandidateRestored": result != 0 and candidate_had_original,
                "customerReleaseProtected": True,
                "previousReleaseExisted": release_had_original,
                "previousReleaseRestored": release_had_original,
            },
        )
        return result
    except Exception:
        if release_started:
            release_tx.rollback(release_had_original)
        candidate_tx.rollback(candidate_had_original)
        raise


def _strict_release_audit(
    job_path: Path,
    job: dict[str, Any],
    policy: dict[str, Any],
) -> tuple[dict[str, Any], list[str], str]:
    candidate = legacy.path(job["candidateDir"])
    candidate_manifest_path = candidate / "candidate-manifest.json"
    candidate_manifest = legacy.read(candidate_manifest_path)
    candidate_hash = (
        legacy.digest(candidate_manifest_path) if candidate_manifest_path.is_file() else ""
    )
    errors = legacy.verify_candidate(job_path, job, candidate, candidate_manifest)
    evidence = {
        kind: legacy.read(legacy.path(job["humanEvidence"][kind]))
        for kind in policy.get("requiredHumanEvidenceKinds", [])
    }
    quality, quality_errors = customer_quality.validate(
        job=job,
        policy=policy,
        candidate_manifest=candidate_manifest,
        candidate_hash=candidate_hash,
        evidence=evidence,
        resolve_repo_path=legacy.path,
        digest=legacy.digest,
    )
    errors.extend(quality_errors)
    return quality, errors, candidate_hash


def _run_release(job_path: Path, job: dict[str, Any], policy: dict[str, Any]) -> int:
    artifact = legacy.path(job["artifactDir"])
    release = legacy.path(job["releaseDir"])
    artifact.mkdir(parents=True, exist_ok=True)
    quality, errors, candidate_hash = _strict_release_audit(job_path, job, policy)
    legacy.write(
        artifact / "customer-quality.json",
        {
            "schemaVersion": 1,
            "phase": "customer-quality",
            "jobId": job["id"],
            "adapterId": job["adapterId"],
            "candidateManifestSha256": candidate_hash or None,
            "passed": not errors,
            "errors": errors,
            "evidence": quality,
        },
    )
    if errors:
        legacy.write(
            artifact / "audit.json",
            {
                "schemaVersion": 2,
                "phase": "release",
                "jobId": job["id"],
                "adapterId": job["adapterId"],
                "checkedAt": legacy.now(),
                "decision": "NO-GO",
                "releaseEligible": False,
                "errors": errors,
                "evidence": quality,
                "candidateManifestSha256": candidate_hash or None,
                "stateProtection": {
                    "customerReleaseProtected": True,
                    "previousReleasePreserved": release.exists(),
                },
            },
        )
        return 2

    release_tx = DirectoryTransaction(release)
    release_had_original = release_tx.begin()
    try:
        result = legacy.run_release(job_path, job, policy)
        if result == 0:
            release_tx.commit(release_had_original)
        else:
            release_tx.rollback(release_had_original)
        _augment_audit(
            artifact,
            {
                "customerReleaseProtected": True,
                "previousReleaseExisted": release_had_original,
                "previousReleaseRestored": result != 0 and release_had_original,
                "strictCustomerQualityPassed": True,
            },
        )
        return result
    except Exception:
        release_tx.rollback(release_had_original)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Transactional customer-quality entry point for image2outfit"
    )
    parser.add_argument("--mode", choices=("candidate", "release"), required=True)
    parser.add_argument("--job", required=True)
    options = parser.parse_args()
    try:
        job_path = Path(options.job).resolve()
        job, policy = legacy.load(job_path)
        if options.mode == "release":
            return _run_release(job_path, job, policy)
        return _run_candidate(job_path, job, policy)
    except Exception as exc:
        print(f"image2outfit production gate: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
