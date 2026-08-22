#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import urllib.request

API = "https://api.github.com"


def request(method: str, url: str, token: str) -> object | None:
    req = urllib.request.Request(
        url,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req) as response:
        if response.status == 204:
            return None
        return json.load(response)


def is_previous(name: str, stable_name: str) -> bool:
    return name == stable_name


def list_artifacts(repository: str, token: str) -> list[dict[str, object]]:
    owner, repo = repository.split("/", 1)
    artifacts: list[dict[str, object]] = []
    page = 1
    while True:
        payload = request(
            "GET",
            f"{API}/repos/{owner}/{repo}/actions/artifacts?per_page=100&page={page}",
            token,
        )
        assert isinstance(payload, dict)
        batch = payload.get("artifacts", [])
        assert isinstance(batch, list)
        artifacts.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < 100:
            return artifacts
        page += 1


def delete_previous(stable_name: str, repository: str, token: str) -> int:
    owner, repo = repository.split("/", 1)
    previous = [
        artifact
        for artifact in list_artifacts(repository, token)
        if is_previous(str(artifact.get("name", "")), stable_name)
    ]
    for artifact in previous:
        request(
            "DELETE",
            f"{API}/repos/{owner}/{repo}/actions/artifacts/{artifact['id']}",
            token,
        )
    return len(previous)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    args = parser.parse_args()
    token = os.environ.get("GH_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or "/" not in repository:
        raise SystemExit("GH_TOKEN and GITHUB_REPOSITORY are required")
    deleted = delete_previous(args.name, repository, token)
    print(f"Deleted {deleted} previous artifact(s) for {args.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
