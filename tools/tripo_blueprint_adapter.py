#!/usr/bin/env python3
"""Run one blueprint-frozen Tripo Smart Mesh experiment method."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image2outfit.blueprint import BlueprintRole, digest_blueprint, validate_blueprint  # noqa: E402
from image2outfit.tripo_adapter import TripoClient, TripoError  # noqa: E402


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _inside_repo(path_text: str) -> Path:
    path = (ROOT / path_text).resolve()
    if path != ROOT.resolve() and ROOT.resolve() not in path.parents:
        raise ValueError("path must stay inside repository")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _download(url: str, destination: Path) -> str:
    if not url.startswith("https://"):
        raise ValueError("Tripo output URL must use https")
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "image2outfit/1"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            with destination.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise TripoError(f"Tripo model download failed: {exc}") from exc
    if not destination.is_file() or destination.stat().st_size == 0:
        raise TripoError("Tripo model download produced an empty file")
    return _sha256(destination)


def run(request_path: Path, result_path: Path) -> int:
    try:
        request = _read_json(request_path)
        if request.get("schemaVersion") != 1:
            raise ValueError("request schemaVersion must be 1")
        product_id = request.get("productId")
        if not isinstance(product_id, str) or not product_id:
            raise ValueError("productId is required")

        blueprint_ref = request.get("blueprint")
        if not isinstance(blueprint_ref, dict):
            raise ValueError("blueprint binding is required")
        blueprint_path = _inside_repo(str(blueprint_ref.get("path") or ""))
        expected_blueprint_sha = blueprint_ref.get("sha256")
        if not isinstance(expected_blueprint_sha, str) or len(expected_blueprint_sha) != 64:
            raise ValueError("blueprint.sha256 is required")
        actual_blueprint_sha = _sha256(blueprint_path)
        if actual_blueprint_sha != expected_blueprint_sha:
            raise ValueError("blueprint file hash mismatch")
        blueprint = _read_json(blueprint_path)
        validation = validate_blueprint(blueprint)
        if not validation["passed"]:
            raise ValueError("invalid blueprint: " + "; ".join(validation["errors"]))
        if blueprint.get("productId") != product_id:
            raise ValueError("blueprint productId mismatch")
        if blueprint.get("role") != BlueprintRole.MESH_DRAFT.value:
            raise ValueError("Tripo Smart Mesh experiment requires mesh-draft blueprint")

        views = request.get("views")
        if not isinstance(views, dict):
            raise ValueError("views object is required")
        face_limit = request.get("faceLimit", 8000)
        if not isinstance(face_limit, int):
            raise ValueError("faceLimit must be an integer")
        api_key = os.environ.get("TRIPO_API_KEY", "")
        if not api_key:
            raise ValueError("TRIPO_API_KEY is required")

        generated = TripoClient(api_key).generate_smart_mesh(
            views,
            face_limit=face_limit,
            timeout_seconds=float(request.get("timeoutSeconds", 600)),
        )
        output = generated["smartMesh"]["output"]
        model_url = next(
            (
                output.get(name)
                for name in ("pbr_model", "model", "base_model")
                if isinstance(output.get(name), str) and output[name]
            ),
            None,
        )
        if model_url is None:
            raise TripoError("Smart Mesh output contains no documented model URL")
        model_path = _inside_repo(
            str(request.get("outputModelPath") or ".image2outfit/tripo/smart-mesh.glb")
        )
        model_sha = _download(model_url, model_path)

        result = {
            "schemaVersion": 1,
            "status": "PASS",
            "productId": product_id,
            "blueprint": {
                "path": blueprint_path.relative_to(ROOT).as_posix(),
                "fileSha256": actual_blueprint_sha,
                "contentDigest": digest_blueprint(blueprint),
                "revision": blueprint["revision"],
            },
            "provider": generated,
            "artifact": {
                "path": model_path.relative_to(ROOT).as_posix(),
                "sha256": model_sha,
                "bytes": model_path.stat().st_size,
            },
        }
        _write(result_path, result)
        return 0
    except (OSError, ValueError, json.JSONDecodeError, TripoError) as exc:
        _write(
            result_path,
            {
                "schemaVersion": 1,
                "status": "FAIL",
                "errorType": type(exc).__name__,
                "error": str(exc),
            },
        )
        print(f"tripo-blueprint: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--result", required=True)
    return parser


def main() -> int:
    options = build_parser().parse_args()
    return run(_inside_repo(options.request), _inside_repo(options.result))


if __name__ == "__main__":
    raise SystemExit(main())
