#!/usr/bin/env python3
"""Preflight canonical research fixtures before handing them to Dagu.

A fixture is queueable only when its tracked job, source identity, request, and
canonical stage bindings form an executable repository contract. The preflight
never invents private-source hashes or stage requests to make a product READY.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from image2outfit.identity import load_reference_identity  # noqa: E402
from image2outfit.pipeline import PIPELINE_STAGES  # noqa: E402

FIXTURE_CONFIG = Path("config/pipeline/research-benchmark-fixtures.v1.json")
REQUEST_ROOT = Path("config/pipeline/requests")
QUEUE_NAME = "product-execution"
_REFERENCE_DRIVERS = {
    "tools/run_ingest_reference_stage.py",
    "tools/run_reference_product_stage.py",
}
_REFERENCE_PIPELINE_PATH_KEYS = (
    "referenceAuditPath",
    "decompositionPath",
    "patternContractPath",
    "stitchGraphPath",
)
_REFERENCE_PIPELINE_CONFIG_KEYS = (*_REFERENCE_PIPELINE_PATH_KEYS, "visualReviewPath")


def _read_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object: {path}")
    return value


def _relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _identity_path(job: Mapping[str, Any], product_id: str) -> Path:
    garment_pipeline = job.get("garmentPipeline")
    configured = (
        garment_pipeline.get("identityManifestPath")
        if isinstance(garment_pipeline, Mapping)
        else None
    )
    if isinstance(configured, str) and configured:
        return ROOT / configured
    return ROOT / "config" / "products" / product_id / "reference-identity.json"


def _reference_driver_blockers(job: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    garment_pipeline = job.get("garmentPipeline")
    if not isinstance(garment_pipeline, Mapping):
        return ["missing-reference-stage-contract"]

    for key in _REFERENCE_PIPELINE_CONFIG_KEYS:
        value = garment_pipeline.get(key)
        if not isinstance(value, str) or not value:
            blockers.append(f"missing-reference-stage-config:{key}")
    for key in _REFERENCE_PIPELINE_PATH_KEYS:
        value = garment_pipeline.get(key)
        if isinstance(value, str) and value and not (ROOT / value).is_file():
            blockers.append(f"missing-reference-stage-input:{key}")

    for key in (
        "productRoot",
        "productManifestPath",
        "buildScript",
        "blendPath",
        "fbxAssetPath",
        "prefabAssetPath",
        "integratedPrefabAssetPath",
    ):
        if not isinstance(job.get(key), str) or not job[key]:
            blockers.append(f"missing-job-execution-field:{key}")
    build_script = job.get("buildScript")
    if (
        isinstance(build_script, str)
        and build_script
        and not (ROOT / build_script).is_file()
    ):
        blockers.append("missing-build-script")
    preview_paths = job.get("previewPaths")
    if not isinstance(preview_paths, Mapping) or not preview_paths:
        blockers.append("missing-preview-contract")
    return blockers


def request_contract_blockers(
    job: Mapping[str, Any], request: Mapping[str, Any]
) -> list[str]:
    blockers: list[str] = []
    product_id = str(job.get("id", ""))
    for field in ("targetAvatar", "sourceReference"):
        if not isinstance(request.get(field), str) or not request[field]:
            blockers.append(f"missing-request-field:{field}")
    revision = request.get("revisionId")
    if not isinstance(revision, str) or not revision:
        blockers.append("missing-request-field:revisionId")
    elif isinstance(job.get("buildRevision"), str) and revision != job["buildRevision"]:
        blockers.append("request-build-revision-mismatch")

    bindings = request.get("stageBindings")
    if not isinstance(bindings, Mapping):
        return [*blockers, "missing-stage-bindings"]

    canonical = [stage.value for stage in PIPELINE_STAGES]
    missing = [stage for stage in canonical if stage not in bindings]
    if missing:
        blockers.extend(f"missing-stage-binding:{stage}" for stage in missing)

    uses_reference_driver = False
    for stage in canonical:
        raw = bindings.get(stage)
        if raw is None:
            continue
        if not isinstance(raw, Mapping):
            blockers.append(f"invalid-stage-binding:{stage}")
            continue
        command = raw.get("command")
        result_path = raw.get("resultPath")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(argument, str) and argument for argument in command)
        ):
            blockers.append(f"invalid-stage-command:{stage}")
            continue
        if not isinstance(result_path, str) or not result_path:
            blockers.append(f"missing-stage-result-path:{stage}")
        elif not result_path.startswith(".image2outfit/products/"):
            blockers.append(f"noncanonical-stage-result-path:{stage}")

        for argument in command:
            if argument in _REFERENCE_DRIVERS:
                uses_reference_driver = True
            if argument.startswith("tools/") and argument.endswith(".py"):
                if not (ROOT / argument).is_file():
                    blockers.append(f"missing-stage-driver:{stage}:{argument}")
        if "--stage" in command:
            index = command.index("--stage")
            if index + 1 >= len(command) or command[index + 1] != stage:
                blockers.append(f"stage-command-identity-mismatch:{stage}")
        if "--job" in command:
            index = command.index("--job")
            if index + 1 >= len(command):
                blockers.append(f"missing-stage-job-argument:{stage}")
            else:
                expected_job = f"config/products/{product_id}/job.json"
                if command[index + 1] != expected_job:
                    blockers.append(f"stage-job-identity-mismatch:{stage}")

    if uses_reference_driver:
        blockers.extend(_reference_driver_blockers(job))
    return list(dict.fromkeys(blockers))


def build_preflight() -> dict[str, Any]:
    fixture_path = ROOT / FIXTURE_CONFIG
    config = _read_object(fixture_path, "fixture config")
    fixtures = config.get("fixtures")
    if not isinstance(fixtures, list):
        raise ValueError("fixture config fixtures must be a list")

    entries: list[dict[str, Any]] = []
    queue_candidates: list[dict[str, str]] = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise ValueError("fixture entries must be JSON objects")
        fixture_id = str(fixture["fixtureId"])
        product_id = str(fixture["productId"])
        job_path = ROOT / str(fixture["jobPath"])
        blockers: list[str] = []

        if not job_path.is_file():
            blockers.append("missing-product-job")
            job: dict[str, Any] = {}
        else:
            job = _read_object(job_path, "product job")
            if job.get("id") != product_id:
                blockers.append("product-job-identity-mismatch")

        request_path = ROOT / REQUEST_ROOT / f"{product_id}.json"
        request: dict[str, Any] | None = None
        if not request_path.is_file():
            blockers.append("missing-canonical-request")
        else:
            request = _read_object(request_path, "pipeline request")
            if request.get("schemaVersion") != 1:
                blockers.append("unsupported-request-schema")
            if request.get("productId") != product_id:
                blockers.append("request-product-identity-mismatch")
            if job:
                blockers.extend(request_contract_blockers(job, request))

        identity_path = _identity_path(job, product_id)
        identity = None
        if not identity_path.is_file():
            blockers.append("missing-reference-identity")
        else:
            try:
                identity = load_reference_identity(identity_path)
            except (KeyError, TypeError, ValueError) as exc:
                blockers.append(f"invalid-reference-identity:{type(exc).__name__}")
            else:
                if identity.product_id != product_id:
                    blockers.append("reference-identity-product-mismatch")

        if request is not None and identity is not None:
            if request.get("sourceReference") != identity.source_reference:
                blockers.append("reference-identity-source-mismatch")

        blockers = list(dict.fromkeys(blockers))
        status = "READY" if not blockers else "BLOCKED"
        entry = {
            "fixtureId": fixture_id,
            "productId": product_id,
            "jobPath": _relative(job_path),
            "requestPath": _relative(request_path) if request_path.is_file() else None,
            "referenceIdentityPath": (
                _relative(identity_path) if identity_path.is_file() else None
            ),
            "status": status,
            "blockers": blockers,
        }
        entries.append(entry)
        if status == "READY":
            queue_candidates.append(
                {
                    "fixtureId": fixture_id,
                    "productId": product_id,
                    "request": _relative(request_path),
                }
            )

    return {
        "schemaVersion": 2,
        "fixtureConfig": FIXTURE_CONFIG.as_posix(),
        "queue": QUEUE_NAME,
        "schedulerOwnsCompletion": False,
        "readinessMeans": "tracked-source-identity-and-executable-stage-contract",
        "entries": entries,
        "readyCount": len(queue_candidates),
        "blockedCount": len(entries) - len(queue_candidates),
        "queueCandidates": queue_candidates,
    }


def main() -> int:
    print(json.dumps(build_preflight(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
