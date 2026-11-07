"""Registered, time-boxed known failures for tests blocked by missing canonical evidence.

Entries live in tests/known-failures.json. A registered failure is reported
as a skip with its issue and reason, so only failures that are not registered
block a PR. Every entry expires; once it expires, the failure blocks again.
"""

from __future__ import annotations

import json
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "tests" / "known-failures.json"
KIND = "image2outfit-test-known-failures"
REQUIRED_FIELDS = ("id", "test", "subject", "match", "reason", "issue", "expires")


def load_entries(path: Path = REGISTRY) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("kind") != KIND or payload.get("schemaVersion") != 1:
        raise ValueError(f"unexpected known-failure registry header: {path}")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError(f"known-failure registry entries must be a list: {path}")
    return entries


def _test_name(testcase: unittest.TestCase) -> str:
    return f"{type(testcase).__name__}.{testcase._testMethodName}"


def find(
    testcase: unittest.TestCase,
    subject: str,
    message: str,
    *,
    today: date | None = None,
    entries: list[dict] | None = None,
) -> dict | None:
    """Return the active registry entry that explains this failure, if any."""
    current = today or date.today()
    name = _test_name(testcase)
    for entry in load_entries() if entries is None else entries:
        if (
            entry["test"] == name
            and entry["subject"] == subject
            and entry["match"] in message
            and date.fromisoformat(entry["expires"]) >= current
        ):
            return entry
    return None


@contextmanager
def tolerated(testcase: unittest.TestCase, subject: str) -> Iterator[None]:
    """Turn a registered failure for ``subject`` into a skip; any other failure still fails."""
    try:
        yield
    except Exception as exc:
        entry = find(testcase, subject, str(exc))
        if entry is None:
            raise
        raise unittest.SkipTest(
            f"known failure {entry['id']} ({entry['issue']}): {entry['reason']}"
        ) from exc


def require_known_or_pass(
    testcase: unittest.TestCase, subject: str, errors: list[str]
) -> None:
    """Pass when there are no errors; skip when every error is registered; fail otherwise."""
    if not errors:
        return
    unknown = [error for error in errors if find(testcase, subject, error) is None]
    if unknown:
        testcase.fail(f"unregistered failures for {subject}: {unknown}")
    ids = sorted({find(testcase, subject, error)["id"] for error in errors})
    testcase.skipTest(f"known failures {', '.join(ids)} for {subject}")
