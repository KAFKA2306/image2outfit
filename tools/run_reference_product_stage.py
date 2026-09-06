#!/usr/bin/env python3
"""Execute one auditable stage for a tracked image-to-outfit product."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PIL import Image

from candidate_quality import (
    QUALITY_REJECT,
    candidate_status,
    geometry_quality,
    validate_visual_review,
    verify_inspected_images,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from image2outfit.garment_flow import (
    canonical_json_sha256,
    sha256_file,
    validate_pattern_contract,
    validate_reference_observations,
    validate_stitch_graph,
)

STAGES = (
    "ingest-reference",
    "normalize-view",
    "decompose-garment",
    "draft-patterns",
    "infer-stitches",
    "initialize-3d",
    "build-blender",
    "simulate-cloth",
    "skin-and-export",
    "render-evidence",
    "audit-geometry",
    "visual-review",
    "finalize-candidate",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    return parser.parse_args()


def read_object(path: Path, label: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return payload


def repo_path(value: str | Path, *, label: str) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise ValueError(f"{label} escapes repository: {value}")
    return resolved


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT)).replace("\\", "/")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def evidence(paths: list[Path]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"stage evidence file is missing: {relative(path)}")
        digest = sha256(path)
        if digest in seen:
            raise ValueError(f"duplicate evidence digest: {relative(path)}")
        seen.add(digest)
        records.append({"path": relative(path), "sha256": digest})
    return records


def emit(
    result_path: Path,
    *,
    stage: str,
    product_id: str,
    paths: list[Path],
    extra: Mapping[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "schemaVersion": 1,
        "stage": stage,
        "productId": product_id,
        "status": "PASS",
        "evidence": evidence(paths),
    }
    if extra:
        payload.update(extra)
    write_json(result_path, payload)


def runtime_root(product_id: str) -> Path:
    return ROOT / ".image2outfit" / "products" / product_id


def review_image_paths(job: Mapping[str, Any]) -> list[Path]:
    views = [
        repo_path(value, label="preview") for value in job["previewPaths"].values()
    ]
    poses = [
        repo_path(value, label="pose") for value in job.get("posePaths", {}).values()
    ]
    return [*views, *poses]


def stage_ingest(
    job: Mapping[str, Any], request: Mapping[str, Any], result: Path
) -> None:
    product_id = str(job["id"])
    audit_path = repo_path(job["garmentPipeline"]["referenceAuditPath"], label="audit")
    audit = read_object(audit_path, "reference audit")
    if audit.get("productId") != product_id:
        raise ValueError("reference audit product identity mismatch")
    expected_reference = (
        f"private-reference://sha256/{audit['source']['originalSha256']}"
    )
    if request.get("sourceReference") != expected_reference:
        raise ValueError("request sourceReference does not match reference audit")
    if (
        audit["source"]["sourceRetention"].get("repositoryContainsSourceImage")
        is not False
    ):
        raise ValueError("public repository must not retain the private source image")
    binding = write_json(
        runtime_root(product_id) / "reference" / "source-binding.json",
        {
            "schemaVersion": 1,
            "productId": product_id,
            "sourceReference": expected_reference,
            "originalSha256": audit["source"]["originalSha256"],
            "sourceImageAvailableInRepository": False,
            "modelIdentificationStatus": audit["modelIdentification"]["status"],
            "status": "PASS",
        },
    )
    emit(
        result,
        stage="ingest-reference",
        product_id=product_id,
        paths=[audit_path, binding],
        extra={
            "modelIdentificationStatus": audit["modelIdentification"]["status"],
            "originalSha256": audit["source"]["originalSha256"],
            "sourceImageAvailableInRepository": False,
        },
    )


def stage_normalize(job: Mapping[str, Any], result: Path) -> None:
    product_id = str(job["id"])
    audit = read_object(
        repo_path(job["garmentPipeline"]["referenceAuditPath"], label="audit"),
        "reference audit",
    )
    observations_path = repo_path(
        job["garmentPipeline"]["referenceObservationsPath"],
        label="reference observations",
    )
    observations = read_object(observations_path, "reference observations")
    source = audit["source"]
    source_sha = str(source["originalSha256"])
    source_size = (int(source["widthPx"]), int(source["heightPx"]))
    normalized = validate_reference_observations(
        observations,
        product_id=product_id,
        source_sha256=source_sha,
        source_size=source_size,
    )
    source_value = os.environ.get("IMAGE2OUTFIT_REFERENCE_IMAGE", "").strip()
    source_path = Path(source_value).expanduser().resolve() if source_value else None
    source_available = source_path is not None
    output_root = runtime_root(product_id) / "normalized"
    output_root.mkdir(parents=True, exist_ok=True)
    direct_outputs: list[Path] = []
    transforms: list[dict[str, Any]] = []
    if source_path is not None:
        if not source_path.is_file():
            raise FileNotFoundError(f"private reference image is missing: {source_path}")
        actual_sha = sha256_file(source_path)
        if actual_sha != source_sha:
            raise ValueError(
                "private reference image hash mismatch: "
                f"expected {source_sha}, found {actual_sha}"
            )
        with Image.open(source_path) as image:
            if image.size != source_size:
                raise ValueError("private reference image dimensions do not match audit")
            for record in normalized["records"]:
                left, top, right, bottom = record["sourceBoundingBoxPx"]
                crop = image.crop((left, top, right, bottom)).convert("RGB")
                output = output_root / f"{record['variantId']}-observed.png"
                crop.resize((768, 768), Image.Resampling.LANCZOS).save(output)
                direct_outputs.append(output)
                transforms.append(
                    {
                        "variantId": record["variantId"],
                        "operation": "crop-resize",
                        "sourceBoundingBoxPx": record["sourceBoundingBoxPx"],
                        "outputSizePx": [768, 768],
                        "inverse": {
                            "x": "sourceLeft + normalizedX * sourceWidth",
                            "y": "sourceTop + normalizedY * sourceHeight",
                        },
                    }
                )
    elif observations.get("verification", {}).get("verifiedFromDirectSource") is not True:
        raise ValueError(
            "private source is unavailable and observations are not direct-source verified"
        )
    report = write_json(
        output_root / "normalized-view.json",
        {
            "schemaVersion": 1,
            "productId": product_id,
            "status": "PASS",
            "artifactKind": "observation-coordinate-normalization",
            "sourceSha256": source_sha,
            "sourceImageAvailableThisRun": source_available,
            "measurementPerformedThisRun": source_available,
            "measurementMode": (
                "DIRECT_SOURCE" if source_available else "VERIFIED_OBSERVATION_REPLAY"
            ),
            "roundTripMaxErrorPx": normalized["roundTripMaxErrorPx"],
            "records": normalized["records"],
            "transforms": transforms,
            "derivedDesignHypotheses": observations.get("derivedDesignHypotheses", []),
            "unobservedViews": ["back", "left", "right"],
        },
    )
    emit(
        result,
        stage="normalize-view",
        product_id=product_id,
        paths=[observations_path, report, *direct_outputs],
        extra={
            "measurementMode": (
                "DIRECT_SOURCE" if source_available else "VERIFIED_OBSERVATION_REPLAY"
            ),
            "measurementPerformedThisRun": source_available,
            "roundTripMaxErrorPx": normalized["roundTripMaxErrorPx"],
            "sourceSha256": source_sha,
        },
    )

def validate_product_document(
    job: Mapping[str, Any], key: str, label: str
) -> tuple[Path, dict[str, Any]]:
    path = repo_path(job["garmentPipeline"][key], label=label)
    payload = read_object(path, label)
    if payload.get("schemaVersion") != 1 or payload.get("productId") != job["id"]:
        raise ValueError(f"{label} schema or product identity mismatch")
    return path, payload


def _require_stage_evidence(
    product_id: str,
    *,
    producer_stage: str,
    expected_path: Path,
) -> dict[str, Any]:
    stage_path = runtime_root(product_id) / "stages" / f"{producer_stage}.json"
    if not stage_path.is_file():
        raise FileNotFoundError(
            f"required producer result is missing: {relative(stage_path)}"
        )
    payload = read_object(stage_path, f"{producer_stage} stage result")
    if (
        payload.get("productId") != product_id
        or payload.get("stage") != producer_stage
        or payload.get("status") != "PASS"
    ):
        raise ValueError(f"{producer_stage} producer identity/status mismatch")
    expected_relative = relative(expected_path)
    expected_sha = sha256(expected_path)
    evidence_items = payload.get("evidence")
    if not isinstance(evidence_items, list):
        raise ValueError(f"{producer_stage} evidence must be a list")
    match = next(
        (
            item
            for item in evidence_items
            if isinstance(item, Mapping) and item.get("path") == expected_relative
        ),
        None,
    )
    if match is None or match.get("sha256") != expected_sha:
        raise ValueError(
            f"{producer_stage} did not produce current {expected_relative}"
        )
    return {"stage": producer_stage, "path": expected_relative, "sha256": expected_sha}


def stage_static(job: Mapping[str, Any], stage: str, key: str, result: Path) -> None:
    product_id = str(job["id"])
    path, payload = validate_product_document(job, key, stage)
    count_key = {
        "decompose-garment": "parts",
        "draft-patterns": "pieces",
        "infer-stitches": "stitches",
    }[stage]
    items = payload.get(count_key)
    if not isinstance(items, list) or not items:
        raise ValueError(f"{stage} requires a non-empty {count_key} list")
    dependencies: list[dict[str, Any]] = []
    if stage == "draft-patterns":
        pieces = validate_pattern_contract(payload, product_id=product_id)
        semantic = {
            "role": "patternSpecification",
            "type": "pattern-contract",
            "version": 1,
            "pieceIds": sorted(pieces),
        }
    elif stage == "infer-stitches":
        pattern_path, pattern = validate_product_document(
            job, "patternContractPath", "pattern contract"
        )
        dependencies.append(
            _require_stage_evidence(
                product_id,
                producer_stage="draft-patterns",
                expected_path=pattern_path,
            )
        )
        pieces = validate_pattern_contract(pattern, product_id=product_id)
        resolved = validate_stitch_graph(payload, product_id=product_id, pieces=pieces)
        semantic = {
            "role": "stitchGraph",
            "type": "edge-pairing-contract",
            "version": 1,
            "resolvedStitchCount": len(resolved),
        }
    else:
        semantic = {
            "role": "garmentPartGraph",
            "type": "garment-decomposition",
            "version": 1,
        }
    consumer = {
        "decompose-garment": "draft-patterns",
        "draft-patterns": "infer-stitches",
        "infer-stitches": "initialize-3d",
    }[stage]
    contract_report = write_json(
        runtime_root(product_id) / "contracts" / f"{stage}.json",
        {
            "schemaVersion": 1,
            "productId": product_id,
            "status": "PASS",
            "producerStage": stage,
            "consumerStage": consumer,
            "documentPath": relative(path),
            "documentSha256": sha256(path),
            "documentSemanticDigest": canonical_json_sha256(payload),
            "dependencies": dependencies,
            **semantic,
        },
    )
    emit(
        result,
        stage=stage,
        product_id=product_id,
        paths=[path, contract_report],
        extra={
            f"{count_key}Count": len(items),
            "outputRole": semantic["role"],
            "consumerStage": consumer,
            "documentSha256": sha256(path),
        },
    )

def stage_initialize(job: Mapping[str, Any], result: Path) -> None:
    product_id = str(job["id"])
    pattern_path, pattern = validate_product_document(
        job, "patternContractPath", "pattern contract"
    )
    stitch_path, stitches = validate_product_document(
        job, "stitchGraphPath", "stitch graph"
    )
    pattern_dependency = _require_stage_evidence(
        product_id,
        producer_stage="draft-patterns",
        expected_path=pattern_path,
    )
    stitch_dependency = _require_stage_evidence(
        product_id,
        producer_stage="infer-stitches",
        expected_path=stitch_path,
    )
    pieces = validate_pattern_contract(pattern, product_id=product_id)
    resolved_stitches = validate_stitch_graph(stitches, product_id=product_id, pieces=pieces)
    lower = pieces["lower-skirt-ring"]["raw"]
    construction3d = lower.get("construction3d")
    if not isinstance(construction3d, Mapping):
        raise ValueError("lower-skirt-ring construction3d mapping is required")
    placements = {
        "lower-skirt-ring": {
            "anchor": "Hips",
            "source": "patternContract",
            "topZM": construction3d["topZM"],
            "bottomZM": construction3d["bottomZM"],
            "mapping": construction3d["mapping"],
        }
    }
    report = write_json(
        runtime_root(product_id) / "initialization" / "initialization-3d.json",
        {
            "schemaVersion": 1,
            "productId": product_id,
            "status": "PASS",
            "collisionPolicy": (
                "positive body-normal offset before clearance refinement"
            ),
            "patternPieceCount": len(pieces),
            "stitchCount": len(resolved_stitches),
            "patternSha256": sha256(pattern_path),
            "stitchGraphSha256": sha256(stitch_path),
            "dependencies": [pattern_dependency, stitch_dependency],
            "placements": placements,
        },
    )
    emit(
        result,
        stage="initialize-3d",
        product_id=product_id,
        paths=[pattern_path, stitch_path, report],
        extra={
            "patternSha256": sha256(pattern_path),
            "stitchGraphSha256": sha256(stitch_path),
            "initializedPatternPiece": "lower-skirt-ring",
        },
    )

def blender_executable() -> str:
    configured = os.environ.get("IMAGE2OUTFIT_BLENDER", "").strip()
    candidates = [
        configured,
        str(ROOT / ".image2outfit" / "blender" / "blender"),
        shutil.which("blender") or "",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise FileNotFoundError("Blender executable was not found")


def _run_blender_build(
    *,
    job_path: Path,
    job: Mapping[str, Any],
    variant_id: str | None = None,
    output_root: Path | None = None,
) -> dict[str, Any]:
    product_id = str(job["id"])
    script = repo_path(job["buildScript"], label="build script")
    label = variant_id or "base"
    log = runtime_root(product_id) / "reports" / f"blender-build-{label}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    if output_root is None:
        report = repo_path(
            f"{job['productRoot']}/Evidence/Build/product-build-report.json",
            label="build report",
        )
        blend = repo_path(job["blendPath"], label="blend")
    else:
        report = output_root / "Evidence" / "Build" / "product-build-report.json"
        blend = output_root / "Source" / "Blender" / Path(job["blendPath"]).name
    command = [
        blender_executable(),
        "--python-use-system-env",
        "--background",
        "--factory-startup",
        "--python-exit-code",
        "1",
        "--python",
        str(script),
        "--",
        "--job",
        str(job_path),
    ]
    if variant_id:
        command.extend(["--variant", variant_id])
    if output_root is not None:
        command.extend(["--output-root", relative(output_root)])
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - started
    log.write_text(
        completed.stdout + "\n--- STDERR ---\n" + completed.stderr,
        encoding="utf-8",
    )
    payload = read_object(report, f"{label} build report") if report.is_file() else None
    quality = geometry_quality(payload) if payload is not None else None
    accepted_quality_reject = (
        completed.returncode == 2
        and quality is not None
        and quality["decision"] == QUALITY_REJECT
    )
    if completed.returncode != 0 and not accepted_quality_reject:
        raise RuntimeError(
            f"Blender {label} build failed with exit code {completed.returncode}; "
            f"see {relative(log)}"
        )
    if payload is None or quality is None:
        raise FileNotFoundError(f"{label} build report was not created")
    return {
        "variantId": str(payload.get("variantId", variant_id or "")),
        "returnCode": completed.returncode,
        "elapsedSeconds": elapsed,
        "reportPath": report,
        "blendPath": blend,
        "logPath": log,
        "report": payload,
        "quality": quality,
        "acceptedQualityReject": accepted_quality_reject,
    }


def stage_build(job_path: Path, job: Mapping[str, Any], result: Path) -> None:
    product_id = str(job["id"])
    base_run = _run_blender_build(job_path=job_path, job=job)
    quality = base_run["quality"]
    evidence_paths = [
        base_run["blendPath"],
        base_run["reportPath"],
        base_run["logPath"],
    ]
    proof: dict[str, Any] = {
        "schemaVersion": 1,
        "productId": product_id,
        "status": "PASS",
        "baseVariant": base_run["report"]["variantId"],
        "runs": [
            {
                "variantId": base_run["report"]["variantId"],
                "kind": "base",
                "geometryDigest": base_run["report"]["geometryDigest"],
                "elapsedSeconds": base_run["elapsedSeconds"],
                "qualityDecision": quality["decision"],
            }
        ],
    }
    if quality["passed"]:
        variants_path = repo_path(
            job["garmentPipeline"]["variantSpecPath"], label="variant spec"
        )
        variant_document = read_object(variants_path, "variant spec")
        base_digest = str(base_run["report"]["geometryDigest"])
        for variant in variant_document["variants"]:
            variant_id = str(variant["id"])
            variant_root = runtime_root(product_id) / "variants" / variant_id
            variant_run = _run_blender_build(
                job_path=job_path,
                job=job,
                variant_id=variant_id,
                output_root=variant_root,
            )
            variant_quality = variant_run["quality"]
            if not variant_quality["passed"]:
                raise ValueError(
                    f"variant {variant_id} failed geometry quality: "
                    f"{variant_quality['failedChecks']}"
                )
            report_payload = variant_run["report"]
            geometry_digest = str(report_payload["geometryDigest"])
            if variant["kind"] == "color" and geometry_digest != base_digest:
                raise ValueError(
                    f"color variant {variant_id} unexpectedly changed geometry"
                )
            if variant["kind"] == "size":
                if geometry_digest == base_digest:
                    raise ValueError(
                        f"size variant {variant_id} did not change geometry"
                    )
                width_scale = float(
                    report_payload["patternToMesh"]["widthScale"]
                )
                expected_scale = float(
                    variant["patternOverrides"]["lower-skirt-ring"]["widthScale"]
                )
                if abs(width_scale - expected_scale) > 1e-9:
                    raise ValueError(
                        f"size variant {variant_id} pattern scale was not consumed"
                    )
            invalidation = report_payload["variantInvalidation"]
            if bool(invalidation["reuseGeometry"]) != (
                variant["kind"] == "color"
            ):
                raise ValueError(
                    f"variant {variant_id} invalidation contract is inconsistent"
                )
            proof["runs"].append(
                {
                    "variantId": variant_id,
                    "kind": variant["kind"],
                    "geometryDigest": geometry_digest,
                    "elapsedSeconds": variant_run["elapsedSeconds"],
                    "qualityDecision": variant_quality["decision"],
                    "outputRoot": relative(variant_root),
                    "patternWidthScale": report_payload["patternToMesh"]["widthScale"],
                }
            )
            evidence_paths.extend(
                [
                    variant_run["reportPath"],
                    variant_run["blendPath"],
                    variant_run["logPath"],
                    variant_root / "ProductManifest.json",
                    variant_root / "Previews" / "geometry-check.png",
                ]
            )
        proof["successfulCandidates"] = len(proof["runs"])
        proof["attemptedCandidates"] = len(proof["runs"])
        proof["geometryReuseVerified"] = True
        proof["sizePropagationVerified"] = True
    else:
        proof["successfulCandidates"] = 0
        proof["attemptedCandidates"] = 1
        proof["geometryReuseVerified"] = False
        proof["sizePropagationVerified"] = False

    proof_path = write_json(
        runtime_root(product_id) / "variants" / "variant-proof.json",
        proof,
    )
    evidence_paths.append(proof_path)
    emit(
        result,
        stage="build-blender",
        product_id=product_id,
        paths=evidence_paths,
        extra={
            "blenderReturnCode": base_run["returnCode"],
            "executionDisposition": (
                "COMPLETED_WITH_QUALITY_REJECT"
                if base_run["acceptedQualityReject"]
                else "COMPLETED"
            ),
            "qualityDecision": quality["decision"],
            "geometryPassed": quality["passed"],
            "failedGeometryChecks": quality["failedChecks"],
            "variantProofed": bool(proof.get("geometryReuseVerified")),
            "candidateCount": len(proof["runs"]),
        },
    )

def stage_simulate(job: Mapping[str, Any], result: Path) -> None:
    product_id = str(job["id"])
    report = repo_path(
        f"{job['productRoot']}/Evidence/Build/cloth-simulation.json",
        label="cloth report",
    )
    _require_stage_evidence(
        product_id,
        producer_stage="build-blender",
        expected_path=report,
    )
    payload = read_object(report, "cloth simulation report")
    construction_path = repo_path(
        job["garmentPipeline"]["constructionPath"], label="construction"
    )
    construction = read_object(construction_path, "construction")
    simulation = construction.get("simulation", {})
    method = simulation.get("method")
    if payload.get("status") != "PASS" or payload.get("method") != method:
        raise ValueError("cloth simulation method/status does not match construction")
    if simulation.get("required") is True:
        if payload.get("cacheBakedDuringBuild") is not True:
            raise ValueError("cloth cache was not baked during the build")
        if payload.get("cacheValidatedBeforeApply") is not True:
            raise ValueError("cloth cache was not validated before apply")
    if simulation.get("reusableCacheRequired") is False:
        if payload.get("reusableCacheAvailable") is not False:
            raise ValueError("applied cloth must not claim a reusable cache")

    expected_inputs = {
        "pattern": sha256(
            repo_path(
                job["garmentPipeline"]["patternContractPath"],
                label="pattern contract",
            )
        ),
        "stitches": sha256(
            repo_path(
                job["garmentPipeline"]["stitchGraphPath"],
                label="stitch graph",
            )
        ),
        "materialRecipe": sha256(
            repo_path(
                job["garmentPipeline"]["materialRecipePath"],
                label="material recipe",
            )
        ),
    }
    if payload.get("inputHashes") != expected_inputs:
        raise ValueError("cloth report input hashes are stale")
    blend = repo_path(job["blendPath"], label="blend")
    if payload.get("blendSha256") != sha256(blend):
        raise ValueError("cloth report does not match current blend")

    frames = payload.get("evaluatedFrames")
    expected_labels = list(simulation.get("requiredFrames", []))
    if (
        not isinstance(frames, list)
        or [item.get("label") for item in frames] != expected_labels
    ):
        raise ValueError("cloth evaluated frames do not match construction contract")
    for frame in frames:
        meshes = frame.get("meshes")
        if not isinstance(meshes, list) or not meshes:
            raise ValueError("cloth evaluated frame is missing meshes")
        for mesh in meshes:
            digest = mesh.get("meshDigest")
            if (
                mesh.get("finiteBounds") is not True
                or not isinstance(digest, str)
                or len(digest) != 64
            ):
                raise ValueError("cloth evaluated mesh proof is invalid")

    emit(
        result,
        stage="simulate-cloth",
        product_id=product_id,
        paths=[report, construction_path, blend],
        extra={
            "simulationMethod": method,
            "cacheValidatedBeforeApply": True,
            "reusableCacheAvailable": False,
            "evaluatedFrameCount": len(frames),
        },
    )

def stage_export(job: Mapping[str, Any], result: Path) -> None:
    product_id = str(job["id"])
    paths = [
        repo_path(job["blendPath"], label="blend"),
        repo_path(job["fbxAssetPath"], label="fbx"),
        repo_path(job["prefabAssetPath"], label="prefab"),
        repo_path(job["integratedPrefabAssetPath"], label="integrated prefab"),
    ]
    emit(
        result,
        stage="skin-and-export",
        product_id=product_id,
        paths=paths,
        extra={"editableSource": True, "fbxExported": True, "prefabDeclared": True},
    )


def stage_render(job: Mapping[str, Any], result: Path) -> None:
    product_id = str(job["id"])
    images = review_image_paths(job)
    view_count = len(job["previewPaths"])
    emit(
        result,
        stage="render-evidence",
        product_id=product_id,
        paths=images,
        extra={
            "fiveViewCount": view_count,
            "poseEvidenceCount": len(images) - view_count,
        },
    )


def stage_audit(job: Mapping[str, Any], result: Path) -> None:
    product_id = str(job["id"])
    report = repo_path(
        f"{job['productRoot']}/Evidence/Build/product-build-report.json",
        label="build report",
    )
    quality = geometry_quality(read_object(report, "build report"))
    emit(
        result,
        stage="audit-geometry",
        product_id=product_id,
        paths=[report],
        extra={
            "qualityDecision": quality["decision"],
            "geometryPassed": quality["passed"],
            "failedChecks": quality["failedChecks"],
            "metrics": quality["metrics"],
        },
    )


def stage_visual_review(
    job: Mapping[str, Any], request: Mapping[str, Any], result: Path
) -> None:
    product_id = str(job["id"])
    review = repo_path(
        job["garmentPipeline"]["visualReviewPath"], label="visual review"
    )
    if not review.is_file():
        raise FileNotFoundError(
            "direct visual review is not recorded yet; inspect current render artifacts "
            f"and add {relative(review)}"
        )
    decision = validate_visual_review(
        read_object(review, "visual review"),
        product_id=product_id,
        revision_id=str(request.get("revisionId", "")),
    )
    images = review_image_paths(job)
    current_hashes = {relative(path): sha256(path) for path in images}
    verify_inspected_images(decision["inspectedImages"], current_hashes)
    emit(
        result,
        stage="visual-review",
        product_id=product_id,
        paths=[review, *images],
        extra={
            "reviewMethod": "direct-image-inspection",
            "reviewStatus": decision["status"],
            "reviewDecision": decision["decision"],
            "blockingFindingCount": len(decision["findings"]),
        },
    )


def stage_finalize(
    job: Mapping[str, Any], request: Mapping[str, Any], result: Path
) -> None:
    product_id = str(job["id"])
    revision_id = str(request.get("revisionId", ""))
    review_path = repo_path(job["garmentPipeline"]["visualReviewPath"], label="review")
    visual = validate_visual_review(
        read_object(review_path, "visual review"),
        product_id=product_id,
        revision_id=revision_id,
    )
    images = review_image_paths(job)
    verify_inspected_images(
        visual["inspectedImages"],
        {relative(path): sha256(path) for path in images},
    )

    build_report_path = repo_path(
        f"{job['productRoot']}/Evidence/Build/product-build-report.json",
        label="build report",
    )
    geometry = geometry_quality(read_object(build_report_path, "build report"))
    pose_paths = [
        repo_path(value, label="pose") for value in job.get("posePaths", {}).values()
    ]
    gates = {
        "blender": geometry["passed"],
        "editableSource": repo_path(job["blendPath"], label="blend").is_file(),
        "fbx": repo_path(job["fbxAssetPath"], label="fbx").is_file(),
        "prefabDeclared": repo_path(job["prefabAssetPath"], label="prefab").is_file(),
        "fiveViewEvidence": all(
            repo_path(value, label="preview").is_file()
            for value in job["previewPaths"].values()
        ),
        "poseEvidence": bool(pose_paths) and all(path.is_file() for path in pose_paths),
        "visualAppearanceReview": visual["decision"] == "PASS",
        "researchTrial": job.get("researchMethod", {}).get("trialStatus") == "DECLARED",
    }
    status = candidate_status(
        gates,
        geometry_decision=geometry["decision"],
        visual_decision=visual["decision"],
    )
    candidate_path = repo_path(
        f"{job['productRoot']}/Evidence/Candidate/candidate-state.json",
        label="candidate state",
    )
    candidate = {
        "schemaVersion": 1,
        "productId": product_id,
        "status": status,
        "revision": revision_id,
        "gates": {name: "PASS" if passed else "FAIL" for name, passed in gates.items()},
        "qualityDecisions": {
            "geometry": geometry["decision"],
            "visual": visual["decision"],
        },
        "blockingFindings": visual["findings"],
        "failedGeometryChecks": geometry["failedChecks"],
        "outOfScope": [
            "Unity import/save/reload",
            "Modular Avatar and NDMF execution",
            "VRChat Build & Test and runtime inspection",
        ],
        "decisionRecorded": True,
    }
    write_json(candidate_path, candidate)
    manifest_path = repo_path(job["productManifestPath"], label="manifest")
    manifest = read_object(manifest_path, "product manifest")
    manifest["status"] = status
    manifest["completionGates"] = candidate["gates"]
    manifest["candidateState"] = relative(candidate_path)
    write_json(manifest_path, manifest)
    emit(
        result,
        stage="finalize-candidate",
        product_id=product_id,
        paths=[candidate_path, manifest_path, review_path],
        extra={
            "decisionRecorded": True,
            "candidateStatus": status,
            "geometryDecision": geometry["decision"],
            "visualDecision": visual["decision"],
        },
    )


def main() -> int:
    args = parse_args()
    job_path = repo_path(args.job, label="job")
    request_path = repo_path(args.request, label="request")
    result_path = repo_path(args.result, label="result")
    runtime = (ROOT / ".image2outfit").resolve()
    if result_path != runtime and runtime not in result_path.parents:
        raise ValueError("result must be inside .image2outfit runtime state")
    job = read_object(job_path, "job")
    request = read_object(request_path, "request")
    if job.get("schemaVersion") != 2 or request.get("schemaVersion") != 1:
        raise ValueError("job/request schema version mismatch")
    if job.get("id") != request.get("productId"):
        raise ValueError("job/request product identity mismatch")

    stage = args.stage
    if stage == "ingest-reference":
        stage_ingest(job, request, result_path)
    elif stage == "normalize-view":
        stage_normalize(job, result_path)
    elif stage == "decompose-garment":
        stage_static(job, stage, "decompositionPath", result_path)
    elif stage == "draft-patterns":
        stage_static(job, stage, "patternContractPath", result_path)
    elif stage == "infer-stitches":
        stage_static(job, stage, "stitchGraphPath", result_path)
    elif stage == "initialize-3d":
        stage_initialize(job, result_path)
    elif stage == "build-blender":
        stage_build(job_path, job, result_path)
    elif stage == "simulate-cloth":
        stage_simulate(job, result_path)
    elif stage == "skin-and-export":
        stage_export(job, result_path)
    elif stage == "render-evidence":
        stage_render(job, result_path)
    elif stage == "audit-geometry":
        stage_audit(job, result_path)
    elif stage == "visual-review":
        stage_visual_review(job, request, result_path)
    elif stage == "finalize-candidate":
        stage_finalize(job, request, result_path)
    else:  # pragma: no cover
        raise AssertionError(stage)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
