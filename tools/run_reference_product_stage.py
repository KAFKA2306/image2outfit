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
from collections.abc import Mapping
from pathlib import Path
from typing import Any

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

from image2outfit.stage_contracts import (
    normalize_observed_variants,
    resolve_private_reference,
    validate_pattern_contract,
    validate_stitch_contract,
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
    source_path = resolve_private_reference(ROOT, job, audit)
    output_root = runtime_root(product_id) / "normalized"
    outputs, manifest = normalize_observed_variants(source_path, audit, output_root)
    report = write_json(output_root / "normalized-view.json", manifest)
    emit(
        result,
        stage="normalize-view",
        product_id=product_id,
        paths=[*outputs, report],
        extra={
            "observationSource": "original-image",
            "sourceImageResolved": True,
            "sourceImageSha256": audit["source"]["originalSha256"],
            "normalizationContractValidated": True,
            "roundTripMaxErrorPx": manifest["roundTripMaxErrorPx"],
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


def stage_static(job: Mapping[str, Any], stage: str, key: str, result: Path) -> None:
    path, payload = validate_product_document(job, key, stage)
    count_key = {
        "decompose-garment": "parts",
        "draft-patterns": "pieces",
        "infer-stitches": "stitches",
    }[stage]
    items = payload.get(count_key)
    if not isinstance(items, list) or not items:
        raise ValueError(f"{stage} requires a non-empty {count_key} list")

    pipeline = job.get("garmentPipeline", {})
    contract_version = (
        int(pipeline.get("stageContractVersion", 1))
        if isinstance(pipeline, Mapping)
        else 1
    )
    if contract_version < 2 or stage == "decompose-garment":
        emit(
            result,
            stage=stage,
            product_id=str(job["id"]),
            paths=[path],
            extra={f"{count_key}Count": len(items)},
        )
        return

    product_id = str(job["id"])
    if stage == "draft-patterns":
        summary = validate_pattern_contract(payload, expected_product_id=product_id)
        emit(
            result,
            stage=stage,
            product_id=product_id,
            paths=[path],
            extra={
                "artifactContractValidated": True,
                "artifactRole": "patternSpecification",
                "artifactSha256": sha256(path),
                "piecesCount": summary["pieceCount"],
                "edgeCount": summary["edgeCount"],
                "units": summary["units"],
            },
        )
        return

    pattern_path, pattern = validate_product_document(
        job, "patternContractPath", "pattern contract"
    )
    summary = validate_stitch_contract(
        payload,
        pattern,
        expected_product_id=product_id,
    )
    emit(
        result,
        stage=stage,
        product_id=product_id,
        paths=[pattern_path, path],
        extra={
            "artifactContractValidated": True,
            "consumerBindingValidated": True,
            "artifactRole": "stitchGraph",
            "inputPatternSha256": sha256(pattern_path),
            "stitchGraphSha256": sha256(path),
            "stitchesCount": summary["stitchCount"],
            "referencedEdgeCount": summary["referencedEdgeCount"],
            "orientationChecks": summary["orientationChecks"],
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
    pipeline = job.get("garmentPipeline", {})
    contract_version = (
        int(pipeline.get("stageContractVersion", 1))
        if isinstance(pipeline, Mapping)
        else 1
    )
    contract_summary: dict[str, Any] = {}
    if contract_version >= 2:
        pattern_summary = validate_pattern_contract(
            pattern, expected_product_id=product_id
        )
        stitch_summary = validate_stitch_contract(
            stitches, pattern, expected_product_id=product_id
        )
        contract_summary = {
            "inputBindingsValidated": True,
            "patternSha256": sha256(pattern_path),
            "stitchSha256": sha256(stitch_path),
            "patternPieceCount": pattern_summary["pieceCount"],
            "patternEdgeCount": pattern_summary["edgeCount"],
            "stitchCount": stitch_summary["stitchCount"],
        }

    placements = {
        "bib-front": {"anchor": "Chest", "offsetM": [0.0, -0.009, 0.885]},
        "waistcoat-left": {
            "anchor": "Chest",
            "offsetM": [-0.072, -0.010, 0.820],
        },
        "waistcoat-right": {
            "anchor": "Chest",
            "offsetM": [0.072, -0.010, 0.820],
        },
        "waistcoat-back": {"anchor": "Chest", "offsetM": [0.0, 0.010, 0.820]},
        "upper-skirt-ring": {"anchor": "Hips", "offsetM": [0.0, 0.0, 0.655]},
        "lower-skirt-ring": {"anchor": "Hips", "offsetM": [0.0, 0.0, 0.625]},
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
            "patternPieceCount": len(pattern["pieces"]),
            "stitchCount": len(stitches["stitches"]),
            "placements": placements,
            **contract_summary,
        },
    )
    emit(
        result,
        stage="initialize-3d",
        product_id=product_id,
        paths=[pattern_path, stitch_path, report],
        extra=contract_summary or None,
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


def stage_build(job_path: Path, job: Mapping[str, Any], result: Path) -> None:
    product_id = str(job["id"])
    script = repo_path(job["buildScript"], label="build script")
    log = runtime_root(product_id) / "reports" / "blender-build.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    report = repo_path(
        f"{job['productRoot']}/Evidence/Build/product-build-report.json",
        label="build report",
    )
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
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    log.write_text(
        completed.stdout + "\n--- STDERR ---\n" + completed.stderr,
        encoding="utf-8",
    )

    quality: dict[str, Any] | None = None
    if report.is_file():
        quality = geometry_quality(read_object(report, "build report"))
    accepted_quality_reject = (
        completed.returncode == 2
        and quality is not None
        and quality["decision"] == QUALITY_REJECT
    )
    if completed.returncode != 0 and not accepted_quality_reject:
        raise RuntimeError(
            f"Blender build failed with exit code {completed.returncode}; "
            f"see {relative(log)}"
        )
    if quality is None:
        raise FileNotFoundError(f"build report was not created: {relative(report)}")

    blend = repo_path(job["blendPath"], label="blend")
    emit(
        result,
        stage="build-blender",
        product_id=product_id,
        paths=[blend, report, log],
        extra={
            "blenderReturnCode": completed.returncode,
            "executionDisposition": (
                "COMPLETED_WITH_QUALITY_REJECT"
                if accepted_quality_reject
                else "COMPLETED"
            ),
            "qualityDecision": quality["decision"],
            "geometryPassed": quality["passed"],
            "failedGeometryChecks": quality["failedChecks"],
        },
    )


def stage_simulate(job: Mapping[str, Any], result: Path) -> None:
    product_id = str(job["id"])
    report = repo_path(
        f"{job['productRoot']}/Evidence/Build/cloth-simulation.json",
        label="cloth report",
    )
    payload = read_object(report, "cloth simulation report")
    pipeline = job.get("garmentPipeline", {})
    contract_version = (
        int(pipeline.get("stageContractVersion", 1))
        if isinstance(pipeline, Mapping)
        else 1
    )
    if contract_version < 2:
        if payload.get("status") != "PASS" or not payload.get("cacheBaked"):
            raise ValueError("cloth simulation report must record a baked PASS cache")
        emit(
            result,
            stage="simulate-cloth",
            product_id=product_id,
            paths=[report],
            extra={"cacheBaked": True, "frameEnd": payload.get("frameEnd")},
        )
        return

    construction_path, construction = validate_product_document(
        job,
        "constructionPath",
        "construction contract",
    )
    policy = construction.get("clothSimulation")
    if not isinstance(policy, Mapping):
        raise ValueError("construction clothSimulation policy is required")
    applicability = policy.get("applicability")
    if applicability not in {"REQUIRED", "NOT_REQUIRED"}:
        raise ValueError("cloth applicability must be REQUIRED or NOT_REQUIRED")
    if payload.get("status") != "PASS":
        raise ValueError("cloth simulation report status must be PASS")
    if payload.get("applicability") != applicability:
        raise ValueError(
            "cloth report applicability does not match construction policy"
        )

    contracts = payload.get("contracts")
    if not isinstance(contracts, list):
        raise ValueError("cloth report contracts must be a list")

    blend = repo_path(job["blendPath"], label="blend")
    if applicability == "REQUIRED":
        expected_components = policy.get("components")
        if (
            not isinstance(expected_components, list)
            or not expected_components
            or not all(
                isinstance(value, str) and value for value in expected_components
            )
        ):
            raise ValueError("required cloth components must be declared")
        actual_components = [
            contract.get("object")
            for contract in contracts
            if isinstance(contract, Mapping)
        ]
        if sorted(actual_components) != sorted(expected_components):
            raise ValueError(
                "cloth report object set does not match construction policy"
            )
        if not payload.get("cacheBaked") or not payload.get("geometryChanged"):
            raise ValueError("required cloth simulation did not bake and settle")

        def valid_hash(value: object) -> bool:
            return (
                isinstance(value, str)
                and len(value) == 64
                and all(character in "0123456789abcdef" for character in value)
            )

        for index, contract in enumerate(contracts):
            if not isinstance(contract, Mapping):
                raise ValueError(f"cloth contract {index} must be an object")
            if contract.get("cacheBakedActual") is not True:
                raise ValueError(f"cloth contract {index} has no actual baked cache")
            if contract.get("geometryChanged") is not True:
                raise ValueError(f"cloth contract {index} did not change geometry")
            before = contract.get("preBakeMeshSha256")
            evaluated = contract.get("evaluatedFrameMeshSha256")
            settled = contract.get("settledMeshSha256")
            if not all(valid_hash(value) for value in (before, evaluated, settled)):
                raise ValueError(f"cloth contract {index} mesh hashes are invalid")
            if before == settled:
                raise ValueError(f"cloth contract {index} settled mesh is unchanged")
            if contract.get("frameStart") != payload.get("frameStart"):
                raise ValueError(f"cloth contract {index} frameStart mismatch")
            if contract.get("frameEnd") != payload.get("frameEnd"):
                raise ValueError(f"cloth contract {index} frameEnd mismatch")
    elif contracts:
        raise ValueError("NOT_REQUIRED cloth policy must not report simulated objects")

    emit(
        result,
        stage="simulate-cloth",
        product_id=product_id,
        paths=[construction_path, report, blend],
        extra={
            "cacheEvidenceValidated": True,
            "simulationApplicability": applicability,
            "cacheBaked": bool(payload.get("cacheBaked")),
            "geometryChanged": bool(payload.get("geometryChanged")),
            "simulatedObjectCount": len(contracts),
            "frameEnd": payload.get("frameEnd"),
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
