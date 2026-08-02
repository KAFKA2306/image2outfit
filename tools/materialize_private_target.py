#!/usr/bin/env python3
"""Materialize a tracked product job with private avatar paths resolved.

Product jobs declare search rules rather than hard-coded local paths. This keeps
licensed/private avatar packages outside Git while allowing the generic
self-hosted candidate workflow to resolve an exact target deterministically.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def repo_path(value: str) -> Path:
    path = (ROOT / value).resolve()
    if path != ROOT and ROOT not in path.parents:
        raise ValueError(f"path escapes repository: {value}")
    return path


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def compile_pattern(value: Any, field: str) -> re.Pattern[str] | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return re.compile(value)


def read_text_for_match(path: Path, limit: int = 8 * 1024 * 1024) -> str:
    if path.stat().st_size > limit:
        return ""
    try:
        return path.read_text(encoding="utf-8-sig", errors="ignore")
    except OSError:
        return ""


def candidate_files(
    search_roots: list[str],
    extensions: list[str],
    exclude_prefixes: list[str],
) -> list[Path]:
    excluded = [repo_path(value) for value in exclude_prefixes]
    normalized_extensions = {value.lower() for value in extensions}
    found: list[Path] = []
    for root_value in search_roots:
        root = repo_path(root_value)
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in normalized_extensions:
                continue
            resolved = path.resolve()
            if any(resolved == prefix or prefix in resolved.parents for prefix in excluded):
                continue
            found.append(resolved)
    return sorted(set(found), key=lambda value: relative(value).lower())


def path_matches(path: Path, pattern: re.Pattern[str] | None) -> bool:
    return pattern is None or pattern.search(relative(path)) is not None


def choose_prefab(
    paths: list[Path],
    spec: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    include = compile_pattern(spec.get("includeRegex"), "prefab.includeRegex")
    profile = compile_pattern(spec.get("profileRegex"), "prefab.profileRegex")
    content = compile_pattern(spec.get("contentRegex"), "prefab.contentRegex")
    preferred = compile_pattern(spec.get("preferredRegex"), "prefab.preferredRegex")
    candidates: list[tuple[int, str, Path, bool, bool]] = []
    for path in paths:
        if not path_matches(path, include):
            continue
        path_profile = path_matches(path, profile)
        content_profile = bool(content and content.search(read_text_for_match(path)))
        if profile is not None or content is not None:
            if not path_profile and not content_profile:
                continue
        value = relative(path)
        score = 0
        if preferred and preferred.search(value):
            score += 1000
        if path_profile:
            score += 300
        if content_profile:
            score += 200
        if "prefab" in value.lower():
            score += 20
        score -= len(value)
        candidates.append((score, value.lower(), path, path_profile, content_profile))
    if not candidates:
        raise FileNotFoundError("No private target prefab matched the declared profile")
    candidates.sort(key=lambda item: (-item[0], item[1]))
    _, _, selected, path_profile, content_profile = candidates[0]
    return selected, {
        "candidateCount": len(candidates),
        "matchedProfileInPath": path_profile,
        "matchedProfileInContent": content_profile,
    }


def choose_source(
    paths: list[Path],
    spec: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    include = compile_pattern(spec.get("includeRegex"), "source.includeRegex")
    profile = compile_pattern(spec.get("profileRegex"), "source.profileRegex")
    fallback = compile_pattern(spec.get("fallbackNameRegex"), "source.fallbackNameRegex")
    preferred = compile_pattern(spec.get("preferredRegex"), "source.preferredRegex")
    candidates: list[tuple[int, str, Path, bool, bool]] = []
    for path in paths:
        value = relative(path)
        if not path_matches(path, include):
            continue
        path_profile = path_matches(path, profile)
        fallback_match = bool(fallback and fallback.search(path.name))
        if profile is not None and not path_profile and not fallback_match:
            continue
        score = 0
        if preferred and preferred.search(value):
            score += 1000
        if path_profile:
            score += 400
        if fallback_match:
            score += 100
        score -= len(value)
        candidates.append((score, value.lower(), path, path_profile, fallback_match))
    if not candidates:
        raise FileNotFoundError("No private target source matched the declared rules")
    candidates.sort(key=lambda item: (-item[0], item[1]))
    _, _, selected, path_profile, fallback_match = candidates[0]
    return selected, {
        "candidateCount": len(candidates),
        "matchedProfileInPath": path_profile,
        "usedDeclaredFallback": fallback_match and not path_profile,
    }


def materialize(job_path: Path, output_path: Path) -> dict[str, Any]:
    job = json.loads(job_path.read_text(encoding="utf-8-sig"))
    resolution = job.get("targetResolution")
    if not isinstance(resolution, dict):
        raise ValueError("job.targetResolution is required for private target materialization")
    if resolution.get("strategy") != "repository-search":
        raise ValueError("unsupported targetResolution.strategy")

    search_roots = resolution.get("searchRoots", ["Assets"])
    exclude_prefixes = resolution.get(
        "excludePrefixes",
        ["Assets/GenWorks", "Assets/_Local/Jobs"],
    )
    if not isinstance(search_roots, list) or not all(isinstance(value, str) for value in search_roots):
        raise ValueError("targetResolution.searchRoots must be a string array")
    if not isinstance(exclude_prefixes, list) or not all(
        isinstance(value, str) for value in exclude_prefixes
    ):
        raise ValueError("targetResolution.excludePrefixes must be a string array")

    prefab_spec = resolution.get("prefab")
    source_spec = resolution.get("source")
    if not isinstance(prefab_spec, dict) or not isinstance(source_spec, dict):
        raise ValueError("targetResolution.prefab and source are required")

    prefab_paths = candidate_files(
        search_roots,
        prefab_spec.get("extensions", [".prefab"]),
        exclude_prefixes,
    )
    source_paths = candidate_files(
        search_roots,
        source_spec.get("extensions", [".fbx"]),
        exclude_prefixes,
    )
    prefab, prefab_evidence = choose_prefab(prefab_paths, prefab_spec)
    source, source_evidence = choose_source(source_paths, source_spec)

    profile = resolution.get("profile")
    if not isinstance(profile, str) or not profile:
        raise ValueError("targetResolution.profile is required")
    job["targetAvatarAssetPath"] = relative(prefab)
    job["targetSourcePath"] = relative(source)
    job["resolvedTarget"] = {
        "strategy": resolution["strategy"],
        "profile": profile,
        "prefab": relative(prefab),
        "source": relative(source),
        "prefabEvidence": prefab_evidence,
        "sourceEvidence": source_evidence,
        "normalSizeFallbackAllowed": bool(resolution.get("normalSizeFallbackAllowed", False)),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(job, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return job["resolvedTarget"]


def main() -> int:
    args = parse_args()
    job_path = repo_path(args.job)
    output_path = repo_path(args.output)
    if not job_path.is_file():
        raise FileNotFoundError(f"tracked job not found: {args.job}")
    evidence = materialize(job_path, output_path)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
