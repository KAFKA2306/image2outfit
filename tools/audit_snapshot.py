from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def files(root: Path) -> dict[str, Path]:
    return {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file()
    }


def read_source_hashes(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        digest, relative = line.split(maxsplit=1)
        if relative in result:
            raise ValueError(f"duplicate source hash: {relative}")
        result[relative] = digest
    return result


def verify_manifest(root: Path) -> None:
    actual_files = files(root)
    expected = read_source_hashes(root / "SOURCE_HASHES.txt")
    actual = {
        relative: sha256(path)
        for relative, path in actual_files.items()
        if relative != "SOURCE_HASHES.txt"
    }
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(
            relative
            for relative in set(actual) & set(expected)
            if actual[relative] != expected[relative]
        )
        raise AssertionError(
            f"source hash manifest mismatch; missing={missing}, extra={extra}, changed={changed}"
        )


def verify_archive(root: Path) -> None:
    archive = root / "HAOLAN_CowHoodKnitSet_v1.zip"
    with zipfile.ZipFile(archive) as handle:
        if handle.testzip() is not None:
            raise AssertionError("candidate archive contains corrupt data")


def verify_regeneration(root: Path, source: Path) -> None:
    with tempfile.TemporaryDirectory() as directory:
        generated = [Path(directory) / "first", Path(directory) / "second"]
        for output in generated:
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "haolan_cow_hood_generator.py"),
                    "--source",
                    str(source),
                    "--out",
                    str(output),
                ],
                check=True,
            )
        first = files(generated[0])
        second = files(generated[1])
        if set(first) != set(second):
            raise AssertionError("generator output file sets are not reproducible")
        nondeterministic = sorted(
            relative
            for relative in first
            if first[relative].read_bytes() != second[relative].read_bytes()
        )
        if nondeterministic:
            raise AssertionError(
                f"generator output is nondeterministic: {nondeterministic}"
            )
        expected = {
            relative: path
            for relative, path in first.items()
            if relative != "SOURCE_HASHES.txt"
        }
        actual = {
            relative: path
            for relative, path in files(root).items()
            if relative != "SOURCE_HASHES.txt"
        }
        if set(expected) - set(actual):
            raise AssertionError(
                f"regenerated files missing from candidate: {sorted(set(expected) - set(actual))}"
            )
        changed = sorted(
            relative
            for relative in expected
            if expected[relative].read_bytes() != actual[relative].read_bytes()
        )
        if changed:
            raise AssertionError(f"regenerated candidate differs: {changed}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--source", required=True)
    options = parser.parse_args()
    candidate = (ROOT / options.candidate).resolve()
    source = (ROOT / options.source).resolve()
    audit = json.loads((candidate / "audit.json").read_text(encoding="utf-8-sig"))
    if audit["decision"] != "NO-GO":
        raise AssertionError("candidate must remain NO-GO until runtime gates pass")
    verify_manifest(candidate)
    verify_archive(candidate)
    verify_regeneration(candidate, source)
    print(f"PASS reproducibility audit: {candidate.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
