#!/usr/bin/env python3
"""Execute one auditable stage for a tracked image-to-outfit product."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
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


def stage_ingest(
    job: Mapping[str, Any], request: Mapping[str, Any], result: Path
) -> None:
    product_id = str(job["id"])
    audit_path = repo_path(job["garmentPipeline"]["referenceAuditPath"], label="audit")
    audit = read_object(audit_path, "reference audit")
    if audit.get("productId") != product_id:
        raise ValueError("reference audit product identity mismatch")
    expected_reference = f"private-reference://sha256/{audit['source']['originalSha256']}"
    if request.get("sourceReference") != expected_reference:
        raise ValueError("request sourceReference does not match reference audit")
    if audit["source"]["sourceRetention"].get("repositoryContainsSourceImage") is not False:
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
    output_root = runtime_root(product_id) / "normalized"
    output_root.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    normalized_records: list[dict[str, Any]] = []
    for variant in audit["variants"]:
        canvas = Image.new("RGB", (768, 768), "white")
        from PIL import ImageDraw

        draw = ImageDraw.Draw(canvas)
        colors = variant["dominantColors"]
        primary = tuple(
            colors[1]["rgb"]
            if variant["variantId"] == "wine-red-black"
            else colors[0]["rgb"]
        )
        black = (15, 15, 18)
        white = (242, 242, 240)
        silver = (142, 148, 160)
        draw.rounded_rectangle(
            (286, 105, 482, 420), radius=48, fill=primary, outline=black, width=6
        )
        draw.polygon(
            [(330, 120), (438, 120), (408, 355), (384, 390), (360, 355)],
            fill=white,
        )
        draw.polygon(
            [(286, 390), (482, 390), (590, 650), (178, 650)], fill=black
        )
        draw.polygon(
            [(205, 620), (563, 620), (610, 700), (158, 700)],
            fill=(30, 30, 34),
        )
        draw.ellipse((335, 92, 433, 160), fill=black)
        draw.line((320, 405, 384, 455, 448, 405), fill=silver, width=5)
        for y in (225, 265, 305, 345):
            draw.ellipse((377, y, 391, y + 14), fill=black)
        path = output_root / f"{variant['variantId']}.png"
        canvas.save(path, optimize=True)
        outputs.append(path)
        normalized_records.append(
            {
                "variantId": variant["variantId"],
                "sourceBoundingBoxPx": variant["boundingBoxPx"],
                "output": relative(path),
                "normalization": (
                    "privacy-preserving construction schematic from audited observations"
                ),
            }
        )
    report = write_json(
        output_root / "normalized-view.json",
        {
            "schemaVersion": 1,
            "productId": product_id,
            "status": "PASS",
            "records": normalized_records,
            "poseNormalization": "not-applicable-product-mannequin-front-view",
            "sourceImageRedistributed": False,
            "viewLimitations": [
                "front view only",
                "back construction inferred and marked uncertain",
            ],
        },
    )
    emit(
        result,
        stage="normalize-view",
        product_id=product_id,
        paths=[*outputs, report],
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
    emit(
        result,
        stage=stage,
        product_id=str(job["id"]),
        paths=[path],
        extra={f"{count_key}Count": len(items)},
    )


def stage_initialize(job: Mapping[str, Any], result: Path) -> None:
    product_id = str(job["id"])
    pattern_path, pattern = validate_product_document(
        job, "patternContractPath", "pattern contract"
    )
    stitch_path, stitches = validate_product_document(
        job, "stitchGraphPath", "stitch graph"
    )
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
        },
    )
    emit(
        result,
        stage="initialize-3d",
        product_id=product_id,
        paths=[pattern_path, stitch_path, report],
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
    if completed.returncode != 0:
        raise RuntimeError(
            f"Blender build failed with exit code {completed.returncode}; "
            f"see {relative(log)}"
        )
    blend = repo_path(job["blendPath"], label="blend")
    report = repo_path(
        f"{job['productRoot']}/Evidence/Build/product-build-report.json",
        label="build report",
    )
    emit(
        result,
        stage="build-blender",
        product_id=product_id,
        paths=[blend, report, log],
        extra={"blenderReturnCode": completed.returncode},
    )


def stage_simulate(job: Mapping[str, Any], result: Path) -> None:
    product_id = str(job["id"])
    report = repo_path(
        f"{job['productRoot']}/Evidence/Build/cloth-simulation.json",
        label="cloth report",
    )
    payload = read_object(report, "cloth simulation report")
    if payload.get("status") != "PASS" or not payload.get("cacheBaked"):
        raise ValueError("cloth simulation report must record a baked PASS cache")
    emit(
        result,
        stage="simulate-cloth",
        product_id=product_id,
        paths=[report],
        extra={"cacheBaked": True, "frameEnd": payload.get("frameEnd")},
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
    views = [repo_path(value, label="preview") for value in job["previewPaths"].values()]
    pose_paths = [
        repo_path(value, label="pose")
        for value in job.get("posePaths", {}).values()
    ]
    emit(
        result,
        stage="render-evidence",
        product_id=product_id,
        paths=[*views, *pose_paths],
        extra={"fiveViewCount": len(views), "poseEvidenceCount": len(pose_paths)},
    )


def stage_audit(job: Mapping[str, Any], result: Path) -> None:
    product_id = str(job["id"])
    report = repo_path(
        f"{job['productRoot']}/Evidence/Build/product-build-report.json",
        label="build report",
    )
    payload = read_object(report, "build report")
    if payload.get("passed") is not True:
        raise ValueError("geometry build report did not pass")
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("geometry report metrics are missing")
    if metrics.get("unweightedVertices") != 0 or metrics.get("degenerateTriangles") != 0:
        raise ValueError("geometry report contains unweighted or degenerate geometry")
    emit(
        result,
        stage="audit-geometry",
        product_id=product_id,
        paths=[report],
        extra={"metrics": metrics},
    )


def stage_visual_review(
    job: Mapping[str, Any], request: Mapping[str, Any], result: Path
) -> None:
    product_id = str(job["id"])
    review = repo_path(job["garmentPipeline"]["visualReviewPath"], label="visual review")
    if not review.is_file():
        raise FileNotFoundError(
            "direct visual review is not recorded yet; inspect current render artifacts "
            f"and add {relative(review)}"
        )
    payload = read_object(review, "visual review")
    required = {
        "schemaVersion": 1,
        "productId": product_id,
        "status": "PASS",
        "reviewMethod": "direct-image-inspection",
        "reviewedRevision": request.get("revisionId", ""),
    }
    mismatches = {
        key: {"found": payload.get(key), "expected": expected}
        for key, expected in required.items()
        if payload.get(key) != expected
    }
    if mismatches:
        raise ValueError(f"visual review contract mismatch: {mismatches}")
    views = [repo_path(value, label="preview") for value in job["previewPaths"].values()]
    emit(
        result,
        stage="visual-review",
        product_id=product_id,
        paths=[review, *views],
        extra={
            "reviewMethod": "direct-image-inspection",
            "reviewDecision": payload.get("decision"),
        },
    )


def stage_finalize(
    job: Mapping[str, Any], request: Mapping[str, Any], result: Path
) -> None:
    product_id = str(job["id"])
    review_path = repo_path(job["garmentPipeline"]["visualReviewPath"], label="review")
    review = read_object(review_path, "visual review")
    build_report_path = repo_path(
        f"{job['productRoot']}/Evidence/Build/product-build-report.json",
        label="build report",
    )
    build_report = read_object(build_report_path, "build report")
    pose_paths = [
        repo_path(value, label="pose")
        for value in job.get("posePaths", {}).values()
    ]
    gates = {
        "blender": build_report.get("passed") is True,
        "editableSource": repo_path(job["blendPath"], label="blend").is_file(),
        "fbx": repo_path(job["fbxAssetPath"], label="fbx").is_file(),
        "prefabDeclared": repo_path(
            job["prefabAssetPath"], label="prefab"
        ).is_file(),
        "fiveViewEvidence": all(
            repo_path(value, label="preview").is_file()
            for value in job["previewPaths"].values()
        ),
        "poseEvidence": bool(pose_paths) and all(path.is_file() for path in pose_paths),
        "visualAppearanceReview": review.get("status") == "PASS",
        "researchTrial": job.get("researchMethod", {}).get("trialStatus")
        == "DECLARED",
    }
    status = "COMPLETE" if all(gates.values()) else "WORKING"
    candidate_path = repo_path(
        f"{job['productRoot']}/Evidence/Candidate/candidate-state.json",
        label="candidate state",
    )
    candidate = {
        "schemaVersion": 1,
        "productId": product_id,
        "status": status,
        "revision": request.get("revisionId", ""),
        "gates": {name: "PASS" if passed else "FAIL" for name, passed in gates.items()},
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
        extra={"decisionRecorded": True, "candidateStatus": status},
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
