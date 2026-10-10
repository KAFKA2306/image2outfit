#!/usr/bin/env python3
"""Execute one auditable stage for a tracked image-to-outfit product."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
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
from contract_io import validate_schema_file

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from image2outfit.stage_contracts import (
    audit_pattern_geometry_contract,
    audit_structural_pattern_coverage,
    normalize_observed_variants,
    resolve_private_reference,
    validate_pattern_contract,
    validate_stitch_contract,
)
from image2outfit.garmentcode import (
    GARMENTCODE_PATTERN_TOOL,
    GARMENTCODE_RUNTIME,
    audit_stitch_graph_connectivity,
    pattern_contract_to_garmentcode_preview,
)
from image2outfit.surface_attachments import (
    audit_surface_attachment_graph,
    render_surface_attachment_preview,
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


def validate_manufacturing_capability(job: Mapping[str, Any]) -> list[Path]:
    """Reject non-manufacturable jobs before spending time on 2D diagnostics."""
    raw = job.get("buildScript")
    if not isinstance(raw, str) or not raw:
        raise ValueError("MANUFACTURING_CAPABILITY_MISSING: declare buildScript")
    builder = repo_path(raw, label="build script")
    if not builder.is_file():
        raise ValueError(f"MANUFACTURING_CAPABILITY_MISSING: implement {raw}")
    inputs = [builder]
    if builder == ROOT / "tools" / "run_product_build.py":
        delegated = job.get("productBuildScript")
        if not isinstance(delegated, str) or not delegated:
            raise ValueError(
                "MANUFACTURING_CAPABILITY_MISSING: implement and register "
                "job.productBuildScript for this product; do not repeat 2D diagnostics"
            )
        source = repo_path(delegated, label="product build script")
        if source == builder or not source.is_file():
            raise ValueError(
                f"MANUFACTURING_CAPABILITY_MISSING: invalid productBuildScript {delegated}"
            )
        inputs.append(source)
    for field in ("targetSourcePath", "targetAvatarAssetPath"):
        raw = job.get(field)
        if not isinstance(raw, str) or not raw:
            raise ValueError(f"MANUFACTURING_CAPABILITY_MISSING: declare {field}")
        source = repo_path(raw, label=field)
        if not source.is_file():
            raise FileNotFoundError(f"MANUFACTURING_CAPABILITY_MISSING: {raw}")
        inputs.append(source)
    try:
        blender_executable()
    except (FileNotFoundError, ValueError, subprocess.SubprocessError) as exc:
        raise ValueError(f"MANUFACTURING_CAPABILITY_MISSING: {exc}") from exc
    return inputs


def validate_assembly_pose(job, pattern):
    pose_path, pose = validate_product_document(job, "assemblyPosePath", "assembly pose")
    if pose.get("status") != "PROTOTYPE_PLACEMENT_HYPOTHESIS":
        raise ValueError("Assembly pose is not a declared prototype hypothesis")
    target = repo_path(job["targetSourcePath"], label="target source")
    measured = repo_path(pose["measurementEvidencePath"], label="measurement evidence")
    if sha256(target) != pose["targetSourceSha256"] or sha256(measured) != pose["measurementEvidenceSha256"]:
        raise ValueError("Assembly pose measurement binding is stale")
    for item in pose.get("placementEvidence", []):
        if sha256(repo_path(item["path"], label="placement evidence")) != item["sha256"]:
            raise ValueError("Assembly pose placement evidence is stale")
    if set(pose["poses"]) != {piece["pieceId"] for piece in pattern["pieces"]}:
        raise ValueError("Assembly pose must explicitly cover every pattern piece")
    for transform in pose["poses"].values():
        for field in ("rotationDegreesXYZ", "translationM"):
            values = transform[field]
            if len(values) != 3 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
                raise ValueError("Assembly pose transform must contain three finite numbers")
    return pose_path, pose, measured


def validate_prototype_readiness(
    job: Mapping[str, Any], request: Mapping[str, Any], job_path: Path,
) -> tuple[Path, dict[str, Any], list[Path]]:
    """Validate executable construction inputs; never grant visual acceptance."""
    policy_path = ROOT / "contracts" / "quality" / "quality-spec.json"
    policy = read_object(policy_path, "quality spec").get("prototypeReadiness")
    if not isinstance(policy, Mapping) or policy.get("scope") != "construction-inputs-only":
        raise ValueError("quality spec is missing prototypeReadiness")
    paths = [job_path, policy_path, *validate_manufacturing_capability(job)]
    documents = {}
    for field in policy["requiredDocumentFields"]:
        path, document = validate_product_document(job, field, field)
        documents[field] = document
        paths.append(path)
    pattern = documents["patternContractPath"]
    stitches = documents["stitchGraphPath"]
    validate_pattern_contract(pattern, expected_product_id=str(job["id"]))
    validate_stitch_contract(stitches, pattern, expected_product_id=str(job["id"]))
    construction = documents["constructionPath"]
    errors = validate_schema_file(
        construction, ROOT / "config" / "products" / "construction.schema.v1.json",
        "prototype construction",
    )
    if errors:
        raise ValueError("prototype construction is invalid: " + "; ".join(errors))
    body_evidence = construction.get("bodyProfileEvidence")
    if isinstance(body_evidence, Mapping):
        for path_field, hash_field in (
            ("path", "sha256"),
            ("sourceEvidencePath", "sourceEvidenceSha256"),
            ("sourceAvatar", "sourceAvatarSha256"),
        ):
            bound = repo_path(body_evidence[path_field], label=path_field)
            if not bound.is_file() or sha256(bound) != body_evidence[hash_field]:
                raise ValueError(f"prototype body-profile evidence is stale: {path_field}")
            if bound not in paths:
                paths.append(bound)
    coverage = audit_structural_pattern_coverage(
        pattern, stitches, documents["decompositionPath"], construction,
        expected_product_id=str(job["id"]),
    )
    if coverage.get("status") != "PASS":
        raise ValueError("prototype structural pattern coverage failed")
    attachments = audit_surface_attachment_graph(
        documents["surfaceAttachmentGraphPath"], pattern, stitches,
        expected_product_id=str(job["id"]),
    )
    if attachments.get("status") != "PASS_2D_PLACEMENT_ONLY":
        raise ValueError("prototype surface attachment layout failed")
    if job["garmentPipeline"].get("assemblyPosePath"):
        pose_path, _pose, measured = validate_assembly_pose(job, pattern)
        paths.append(pose_path)
        if measured not in paths:
            paths.append(measured)
    report = {
        "schemaVersion": 1,
        "productId": job["id"],
        "designRevision": request["revisionId"],
        "status": "PASS",
        "decision": "PROTOTYPE_ONLY",
        "scope": policy["scope"],
        "unassessedAreas": policy["unassessedAreas"],
        "evidence": evidence(paths),
        "grantsVisualAcceptance": False,
        "structuralCoverage": coverage,
        "surfaceAttachmentLayout": attachments,
        "placementOwner": job.get("productBuildScript", job["buildScript"]),
    }
    report_path = write_json(
        runtime_root(str(job["id"])) / "initialization" / "prototype-readiness.json", report
    )
    return report_path, report, [*paths, report_path]


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


def stage_garmentcode_pattern(
    job: Mapping[str, Any],
    pattern_path: Path,
    pattern: Mapping[str, Any],
    stitch_path: Path,
    stitch_graph: Mapping[str, Any],
    pattern_summary: Mapping[str, Any],
    stitch_summary: Mapping[str, Any],
    geometry_audit: Mapping[str, Any],
    geometry_report_path: Path,
    geometry_implementation_paths: list[Path],
    stitch_export_mode: str,
    coverage_report_path: Path,
    result: Path,
) -> None:
    runtime_config_path = (
        ROOT / "config" / "oss-runtimes" / "garmentcode-pygarment.json"
    )
    runtime_config = read_object(runtime_config_path, "GarmentCode runtime config")
    if runtime_config.get("schemaVersion") != 1:
        raise ValueError("GarmentCode runtime config schema mismatch")
    if runtime_config.get("runtimeId") != GARMENTCODE_RUNTIME.runtime_id:
        raise ValueError("GarmentCode runtime ID does not match the adapter")
    if (
        runtime_config.get("upstreamRepository")
        != GARMENTCODE_RUNTIME.upstream_repository
    ):
        raise ValueError("GarmentCode upstream repository does not match the adapter")
    if runtime_config.get("upstreamRevision") != GARMENTCODE_RUNTIME.upstream_revision:
        raise ValueError("GarmentCode upstream revision does not match the adapter")
    if runtime_config.get("threeDEnabled") is not False:
        raise ValueError("GarmentCode pattern stage must keep 3D generation disabled")
    if runtime_config.get("outputMode") != "2d-panel-layout-only":
        raise ValueError("GarmentCode pattern stage output mode is unsupported")
    requirements_lock_path = repo_path(
        runtime_config["requirementsLockPath"], label="GarmentCode requirements lock"
    )
    if not requirements_lock_path.is_file():
        raise FileNotFoundError("GarmentCode requirements lock is missing")

    upstream_root = repo_path(
        runtime_config["runtimePath"], label="GarmentCode runtime path"
    )
    if not upstream_root.is_dir():
        raise FileNotFoundError(
            "GarmentCode runtime is not installed; run `task oss:garmentcode:setup`"
        )
    revision_result = subprocess.run(
        ["git", "-C", str(upstream_root), "rev-parse", "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if revision_result.returncode != 0:
        raise RuntimeError("GarmentCode runtime is not a Git checkout")
    actual_revision = revision_result.stdout.strip()
    if actual_revision != runtime_config["upstreamRevision"]:
        raise RuntimeError(
            "GarmentCode checkout revision mismatch: "
            f"expected {runtime_config['upstreamRevision']}, found {actual_revision}"
        )

    python_candidates = (
        upstream_root / ".venv" / "Scripts" / "python.exe",
        upstream_root / ".venv" / "bin" / "python",
    )
    python_executable = next(
        (candidate for candidate in python_candidates if candidate.is_file()), None
    )
    if python_executable is None:
        raise FileNotFoundError(
            "GarmentCode Python environment is missing; run `task oss:garmentcode:setup`"
        )

    product_id = str(job["id"])
    output_dir = runtime_root(product_id) / "pattern" / "garmentcode"
    coverage_report = read_object(
        coverage_report_path, "structural pattern coverage report"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    input_path = write_json(
        output_dir / "garmentcode-pattern-input.json",
        pattern_contract_to_garmentcode_preview(
            dict(pattern),
            dict(stitch_graph),
            pattern_sha256=sha256(pattern_path),
            stitch_graph_sha256=sha256(stitch_path),
            stitch_export_mode=stitch_export_mode,
        ),
    )
    command = [
        str(python_executable),
        str(ROOT / "tools" / "run_garmentcode_pattern_preview.py"),
        "--input",
        str(input_path),
        "--output-dir",
        str(output_dir),
        "--upstream-root",
        str(upstream_root),
        "--upstream-revision",
        str(runtime_config["upstreamRevision"]),
        "--python-version",
        str(runtime_config["pythonVersion"]),
        "--pygarment-version",
        str(runtime_config["pygarmentVersion"]),
        "--requirements-lock",
        str(requirements_lock_path),
        "--stitch-export-mode",
        stitch_export_mode,
    ]
    execution = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if execution.returncode != 0:
        raise RuntimeError(
            "GarmentCode 2D pattern preview failed: "
            f"{execution.stderr or execution.stdout}"
        )

    run_path = output_dir / "garmentcode-run.json"
    run_record = read_object(run_path, "GarmentCode run record")
    if run_record.get("selfIntersection") is not False:
        raise ValueError("GarmentCode reported a self-intersecting panel")
    if run_record.get("threeDGenerated") is not False:
        raise ValueError("GarmentCode pattern stage must not generate 3D output")
    if run_record.get("stitchExportMode") != stitch_export_mode:
        raise ValueError("GarmentCode run record has a different stitch export mode")
    if (
        stitch_export_mode == "strict-boundary-edges"
        and run_record.get("stitchCount") != stitch_summary["stitchCount"]
    ):
        raise ValueError("GarmentCode did not receive every canonical stitch pair")
    orientation_audit = run_record.get("seamOrientationAudit")
    if stitch_export_mode == "strict-boundary-edges" and (
        not isinstance(orientation_audit, Mapping)
        or orientation_audit.get("status") != "PASS"
        or orientation_audit.get("canonicalStitchPairCount")
        != stitch_summary["stitchCount"]
        or orientation_audit.get("directionAuditedCount")
        != stitch_summary["stitchCount"]
        or orientation_audit.get("directionMatchedCount")
        + orientation_audit.get("directionNotApplicableCount", -1)
        != stitch_summary["stitchCount"]
        or orientation_audit.get("directionMismatchCount") != 0
        or orientation_audit.get("directionUnknownCount") != 0
        or orientation_audit.get("endpointMappingAuditedCount")
        != stitch_summary["stitchCount"]
        or orientation_audit.get("endpointMappingMatchedCount")
        != stitch_summary["stitchCount"]
        or orientation_audit.get("endpointMappingMismatchCount") != 0
        or orientation_audit.get("assemblyConnectivityEvaluated") is not False
    ):
        raise ValueError(
            "GarmentCode 2D seam orientation or endpoint-mapping audit did not preserve every canonical stitch"
        )
    if run_record.get("requirementsLockSha256") != sha256(requirements_lock_path):
        raise ValueError("GarmentCode run record does not match its requirements lock")
    output_paths = [
        repo_path(output_dir / item, label="GarmentCode output")
        for item in run_record.get("outputs", [])
    ]
    required_outputs = {
        "garmentcode-pattern-specification.json",
        "garmentcode-pattern-layout.svg",
        "garmentcode-pattern-layout.png",
        "garmentcode-pattern-layout.pdf",
    }
    if {path.name for path in output_paths} != required_outputs:
        raise ValueError("GarmentCode output set does not match the 2D stage contract")

    open_sew_evidence = None
    open_sew_paths: list[Path] = []
    pipeline = job.get("garmentPipeline", {})
    if isinstance(pipeline, Mapping) and pipeline.get("openSew2dPreview") is True:
        config_path = ROOT / "config" / "oss-runtimes" / "opensew-2-blender.json"
        open_sew_config = read_object(config_path, "OpenSew runtime config")
        if open_sew_config.get("schemaVersion") != 1:
            raise ValueError("OpenSew runtime config schema mismatch")
        if open_sew_config.get("runtimeId") != "opensew-2-blender-2d":
            raise ValueError("OpenSew runtime ID is unsupported")
        if open_sew_config.get("upstreamRepository") != "https://github.com/MarcelloMorettoni/opensew-2":
            raise ValueError("OpenSew upstream repository does not match the adapter")
        if open_sew_config.get("outputMode") != "2d-panel-mesh-only" or open_sew_config.get("threeDEnabled") is not False:
            raise ValueError("OpenSew preview must keep 3D generation disabled")
        if open_sew_config.get("executionMode") != "external-isolated":
            raise ValueError("OpenSew must run in its isolated external runtime")

        open_sew_root = repo_path(open_sew_config["runtimePath"], label="OpenSew runtime path")
        if not open_sew_root.is_dir():
            raise FileNotFoundError("OpenSew runtime is not installed; run `task oss:opensew:setup`")
        revision_result = subprocess.run(
            ["git", "-C", str(open_sew_root), "rev-parse", "HEAD"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if revision_result.returncode != 0 or revision_result.stdout.strip() != open_sew_config.get("upstreamRevision"):
            raise RuntimeError("OpenSew checkout revision does not match its runtime pin")
        remote_result = subprocess.run(
            ["git", "-C", str(open_sew_root), "remote", "get-url", "origin"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if remote_result.returncode != 0 or remote_result.stdout.strip() != open_sew_config["upstreamRepository"]:
            raise RuntimeError("OpenSew checkout remote does not match its runtime pin")
        status_result = subprocess.run(
            ["git", "-C", str(open_sew_root), "status", "--porcelain"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if status_result.returncode != 0 or status_result.stdout.strip():
            raise RuntimeError("OpenSew checkout is dirty; refusing to run unpinned source")

        blender_path = repo_path(open_sew_config["blenderExecutable"], label="pinned Blender executable")
        if not blender_path.is_file():
            raise FileNotFoundError("Pinned Blender is missing; run `task oss:opensew:setup`")
        blender_version = subprocess.run(
            [str(blender_path), "--background", "--version"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        expected_blender_version = str(open_sew_config["blenderVersion"])
        first_version_line = (blender_version.stdout or blender_version.stderr).splitlines()
        if blender_version.returncode != 0 or not first_version_line or not first_version_line[0].startswith(f"Blender {expected_blender_version} "):
            raise RuntimeError("Pinned Blender executable version does not match its runtime config")

        preview_script = ROOT / "tools" / "run_opensew_pattern_preview.py"
        run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        open_sew_dir = runtime_root(product_id) / "pattern" / "opensew-2d" / f"run-{run_stamp}-{uuid.uuid4().hex[:8]}"
        open_sew_dir.mkdir(parents=True, exist_ok=False)
        command = [
            str(blender_path),
            "--background",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python",
            str(preview_script),
            "--",
            "--pattern",
            str(pattern_path),
            "--stitches",
            str(stitch_path),
            "--output-dir",
            str(open_sew_dir),
            "--opensew-root",
            str(open_sew_root),
            "--expected-revision",
            str(open_sew_config["upstreamRevision"]),
            "--expected-blender-version",
            expected_blender_version,
            "--target-grid-meters",
            str(open_sew_config["targetGridMeters"]),
            "--endpoint-tolerance-mm",
            str(open_sew_config["endpointToleranceMillimeters"]),
        ]
        open_sew_execution = None
        try:
            open_sew_execution = subprocess.run(
                command,
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
            )
            report_path = open_sew_dir / "opensew-2d-run.json"
            report = read_object(report_path, "OpenSew 2D preview report") if report_path.is_file() else None
            if open_sew_execution.returncode != 0:
                raise RuntimeError(f"OpenSew 2D preview failed: {open_sew_execution.stderr or open_sew_execution.stdout}")
            if report is None or report.get("status") != "PASS_2D_ENDPOINT_AWARE_ONLY":
                raise ValueError("OpenSew did not pass its endpoint-aware 2D-only audit")
            counts = report.get("counts", {})
            checks = report.get("checks", {})
            expected_counts = {
                "panelCount": pattern_summary["pieceCount"],
                "namedEdgeGroupCount": pattern_summary["edgeCount"],
                "canonicalNamedEdgeCount": pattern_summary["edgeCount"],
                "stitchPairCount": stitch_summary["stitchCount"],
            }
            if any(counts.get(key) != value for key, value in expected_counts.items()):
                raise ValueError("OpenSew panel, edge, or stitch counts differ from canonical contracts")
            for key in (
                "allPanelMeshesFlatInXZ",
                "noLooseOrNonmanifoldPanelEdges",
                "allNamedEdgesHaveConnectedEndpointInclusiveChains",
                "allStitchPairsHaveEndpointInclusiveChains",
                "allStitchPairSampleCountsEqual",
                "allCurvedEdgesPreservedWithinSamplingTolerance",
            ):
                if checks.get(key) is not True:
                    raise ValueError(f"OpenSew 2D audit failed: {key}")
            if checks.get("threeDGenerated") is not False or report.get("output", {}).get("blendSha256") is None:
                raise ValueError("OpenSew output crossed the 2D-only boundary or lacks saved evidence")
            blend_path = repo_path(report["output"]["blendPath"], label="OpenSew 2D panel blend")
            if not blend_path.is_file():
                raise FileNotFoundError("OpenSew 2D panel blend is missing")
        except Exception as exc:
            failure_path = open_sew_dir / "opensew-2d-failure.json"
            failure_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "productId": product_id,
                        "status": "FAIL",
                        "error": f"{type(exc).__name__}: {exc}",
                        "command": command,
                        "stdout": open_sew_execution.stdout[-12000:] if open_sew_execution else "",
                        "stderr": open_sew_execution.stderr[-12000:] if open_sew_execution else "",
                        "patternSha256": sha256(pattern_path),
                        "stitchGraphSha256": sha256(stitch_path),
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            raise

        open_sew_paths = [
            config_path,
            preview_script,
            open_sew_root / "LICENSE",
            open_sew_root / "clothing_design" / "patterns.py",
            report_path,
            blend_path,
        ]
        open_sew_evidence = {
            "status": "PASS_2D_ENDPOINT_AWARE_ONLY",
            "runtimeId": open_sew_config["runtimeId"],
            "upstreamRevision": open_sew_config["upstreamRevision"],
            "blenderVersion": expected_blender_version,
            "panelCount": counts["panelCount"],
            "namedEdgeGroupCount": counts["namedEdgeGroupCount"],
            "stitchPairCount": counts["stitchPairCount"],
            "allNamedEdgesHaveEndpointInclusiveChains": checks["allNamedEdgesHaveConnectedEndpointInclusiveChains"],
            "allStitchPairsHaveEndpointInclusiveChains": checks["allStitchPairsHaveEndpointInclusiveChains"],
            "allStitchPairSampleCountsEqual": checks["allStitchPairSampleCountsEqual"],
            "maximumIndexPairingStationGapMm": checks["maximumOpenSewIndexPairingStationGapMm"],
            "allCurvedEdgesPreservedWithinSamplingTolerance": checks[
                "allCurvedEdgesPreservedWithinSamplingTolerance"
            ],
            "curvedEdgeCount": checks["curvedEdgeCount"],
            "maximumCurveSamplingErrorBoundMm": checks["maximumCurveSamplingErrorBoundMm"],
            "maximumBoundaryProjectionErrorMm": checks["maximumBoundaryProjectionErrorMm"],
            "stitchPairSampleCountMismatchCount": checks[
                "stitchPairSampleCountMismatchCount"
            ],
            "nonQuadFaceCount": counts["nonQuadFaceCount"],
            "threeDGenerated": False,
            "garmentAssemblyCreated": False,
            "clothSimulationRun": False,
        }

    emit(
        result,
        stage="draft-patterns",
        product_id=product_id,
        paths=[
            pattern_path,
            stitch_path,
            coverage_report_path,
            geometry_report_path,
            *geometry_implementation_paths,
            requirements_lock_path,
            input_path,
            run_path,
            *output_paths,
            *open_sew_paths,
        ],
        extra={
            "artifactContractValidated": True,
            "consumerBindingValidated": True,
            "artifactRole": "patternLayoutPreview",
            "artifactSha256": sha256(output_dir / "garmentcode-pattern-layout.png"),
            "garmentcodeSpecificationSha256": sha256(
                output_dir / "garmentcode-pattern-specification.json"
            ),
            "inputPatternSha256": sha256(pattern_path),
            "stitchGraphSha256": sha256(stitch_path),
            "piecesCount": int(pattern_summary["pieceCount"]),
            "edgeCount": int(pattern_summary["edgeCount"]),
            "patternGeometryAudit": dict(geometry_audit),
            "patternGeometryAuditPath": relative(geometry_report_path),
            "stitchesCount": int(stitch_summary["stitchCount"]),
            "units": str(pattern.get("units", "")),
            "externalRuntime": GARMENTCODE_RUNTIME.runtime_id,
            "upstreamRevision": str(runtime_config["upstreamRevision"]),
            "pygarmentVersion": str(runtime_config["pygarmentVersion"]),
            "runtimeRequirementsSha256": sha256(requirements_lock_path),
            "selfIntersection": False,
            "threeDGenerated": False,
            "stitchExportMode": stitch_export_mode,
            "stitchesSubmittedToGarmentCode": run_record.get(
                "stitchesSubmittedToGarmentCode"
            ),
            "garmentCodeStitchPairCount": run_record.get("stitchCount"),
            "garmentCodeSeamOrientationAudit": orientation_audit,
            "structuralPatternCoverage": coverage_report,
            **({"openSew2dPreview": open_sew_evidence} if open_sew_evidence else {}),
        },
    )


def stage_static(
    job: Mapping[str, Any],
    stage: str,
    key: str,
    result: Path,
    request: Mapping[str, Any] | None = None,
) -> None:
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
        pipeline = job.get("garmentPipeline", {})
        construction_path = None
        construction = None
        if isinstance(pipeline, Mapping) and pipeline.get("constructionPath"):
            construction_path, construction = validate_product_document(
                job, "constructionPath", "construction contract"
            )
        decomposition_path, decomposition = validate_product_document(
            job, "decompositionPath", "garment decomposition"
        )
        stitch_path, stitch_graph = validate_product_document(
            job, "stitchGraphPath", "stitch graph"
        )
        validate_stitch_contract(
            stitch_graph,
            payload,
            expected_product_id=product_id,
        )
        coverage = audit_structural_pattern_coverage(
            payload,
            stitch_graph,
            decomposition,
            construction,
            expected_product_id=product_id,
        )
        source_paths = [path, stitch_path, decomposition_path]
        if construction_path is not None:
            source_paths.append(construction_path)
        source_artifacts = [
            {"path": relative(item), "sha256": sha256(item)}
            for item in source_paths
        ]
        coverage_key = hashlib.sha256(
            "".join(item["sha256"] for item in source_artifacts).encode("ascii")
        ).hexdigest()[:12]
        coverage_report_path = (
            runtime_root(product_id)
            / "stages"
            / f"draft-pattern-coverage-{coverage_key}.json"
        )
        write_json(
            coverage_report_path,
            {
                "schemaVersion": 1,
                "stage": "draft-patterns",
                "productId": product_id,
                **coverage,
                "sourceArtifacts": source_artifacts,
                "nextAction": (
                    "Add reviewed 2D pieces and stitch pairs for every missing structural component, then rerun the GarmentCode 2D stage."
                    if coverage["status"] == "BLOCKED"
                    else "Proceed with the selected 2D pattern tool; keep the 3D gate closed until visualAppearanceReview passes."
                    if coverage["status"] == "PASS"
                    else "No explicit requiredPatternComponents are declared; run the selected 2D pattern tool without treating component coverage as audited."
                ),
            },
        )
        if coverage["status"] == "BLOCKED":
            missing = coverage["missingStructuralComponents"]
            panels = coverage["missingExpectedPanels"]
            raise ValueError(
                "draft-patterns blocked by structural pattern coverage audit: "
                f"missing components={missing}; missing panels={panels}"
            )
        geometry_audit = audit_pattern_geometry_contract(
            payload,
            expected_product_id=product_id,
        )
        geometry_implementation_paths = [
            ROOT / "src" / "image2outfit" / "pattern_stage.py",
            ROOT / "src" / "image2outfit" / "stage_contracts.py",
            ROOT / "src" / "image2outfit" / "domain.py",
            ROOT / "tools" / "run_reference_product_stage.py",
        ]
        geometry_source_hash = hashlib.sha256(
            "".join(
                [
                    sha256(path),
                    *(sha256(item) for item in geometry_implementation_paths),
                ]
            ).encode("ascii")
        ).hexdigest()[:12]
        geometry_report_path = (
            runtime_root(product_id)
            / "stages"
            / f"pattern-geometry-{geometry_source_hash}.json"
        )
        write_json(
            geometry_report_path,
            {
                "schemaVersion": 1,
                "stage": "draft-patterns",
                "productId": product_id,
                "revisionId": (
                    request.get("revisionId")
                    if isinstance(request, Mapping)
                    else None
                ),
                **geometry_audit,
                "sourceArtifacts": [
                    {"path": relative(path), "sha256": sha256(path)}
                ],
                "implementationArtifacts": [
                    {"path": relative(item), "sha256": sha256(item)}
                    for item in geometry_implementation_paths
                ],
            },
        )
        if geometry_audit["status"] != "PASS":
            raise ValueError(
                "draft-patterns blocked by planar geometry audit: "
                f"{geometry_audit['defectCounts']}; "
                f"evidence: {relative(geometry_report_path)}"
            )
        pins = request.get("toolPins", {}) if isinstance(request, Mapping) else {}
        selected_tool = pins.get(stage) if isinstance(pins, Mapping) else None
        if selected_tool == GARMENTCODE_PATTERN_TOOL:
            stitch_path, stitch_graph = validate_product_document(
                job, "stitchGraphPath", "stitch graph"
            )
            stitch_summary = validate_stitch_contract(
                stitch_graph,
                payload,
                expected_product_id=product_id,
            )
            stage_garmentcode_pattern(
                job,
                path,
                payload,
                stitch_path,
                stitch_graph,
                summary,
                stitch_summary,
                geometry_audit,
                geometry_report_path,
                geometry_implementation_paths,
                str(
                    job.get("garmentPipeline", {}).get(
                        "garmentcodeStitchExport", "preview-only"
                    )
                ),
                coverage_report_path,
                result,
            )
            return
        emit(
            result,
            stage=stage,
            product_id=product_id,
            paths=[
                path,
                *([construction_path] if construction_path is not None else []),
                decomposition_path,
                stitch_path,
                coverage_report_path,
                geometry_report_path,
                *geometry_implementation_paths,
            ],
            extra={
                "artifactContractValidated": True,
                "artifactRole": "patternSpecification",
                "artifactSha256": sha256(path),
                "piecesCount": summary["pieceCount"],
                "edgeCount": summary["edgeCount"],
                "units": summary["units"],
                "structuralPatternCoverage": coverage,
                "patternGeometryAudit": geometry_audit,
                "patternGeometryAuditPath": relative(geometry_report_path),
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
    connectivity = audit_stitch_graph_connectivity(pattern, payload)
    source_hash = hashlib.sha256(
        f"{sha256(pattern_path)}:{sha256(path)}".encode("ascii")
    ).hexdigest()[:12]
    connectivity_path = (
        runtime_root(product_id)
        / "stages"
        / f"stitch-connectivity-{source_hash}.json"
    )
    edge_length_audit = summary["edgeLengthCompatibilityAudit"]
    edge_length_path = (
        runtime_root(product_id)
        / "stages"
        / f"stitch-edge-length-{source_hash}.json"
    )
    edge_length_record: dict[str, Any] = {
        "schemaVersion": 1,
        "stage": "infer-stitches",
        "auditType": "2d-stitch-edge-length-compatibility",
        "productId": product_id,
        "revisionId": (
            request.get("revisionId")
            if isinstance(request, Mapping)
            else None
        ),
        "sourceArtifacts": [
            {"path": relative(pattern_path), "sha256": sha256(pattern_path)},
            {"path": relative(path), "sha256": sha256(path)},
        ],
        "implementationArtifacts": [
            {
                "path": relative(implementation_path),
                "sha256": sha256(implementation_path),
            }
            for implementation_path in (
                ROOT / "src" / "image2outfit" / "stage_contracts.py",
                ROOT / "src" / "image2outfit" / "construction.py",
                ROOT / "src" / "image2outfit" / "seam_stage.py",
                ROOT / "tools" / "run_reference_product_stage.py",
            )
        ],
        "audit": edge_length_audit,
    }
    connectivity_record: dict[str, Any] = {
        "schemaVersion": 1,
        "stage": "infer-stitches",
        "productId": product_id,
        "revisionId": (
            request.get("revisionId")
            if isinstance(request, Mapping)
            else None
        ),
        "sourceArtifacts": [
            {"path": relative(pattern_path), "sha256": sha256(pattern_path)},
            {"path": relative(path), "sha256": sha256(path)},
        ],
        "connectivity": connectivity,
    }
    paths = [pattern_path, path]

    pipeline = job.get("garmentPipeline", {})
    surface_attachment_path: Path | None = None
    surface_attachment_report_path: Path | None = None
    surface_attachment_summary: dict[str, Any] | None = None
    surface_attachment_preview_path: Path | None = None
    surface_attachment_preview_report_path: Path | None = None
    surface_attachment_preview_summary: dict[str, Any] | None = None
    if isinstance(pipeline, Mapping) and pipeline.get("surfaceAttachmentGraphPath"):
        surface_attachment_path, surface_attachment_graph = validate_product_document(
            job, "surfaceAttachmentGraphPath", "surface attachment graph"
        )
        surface_attachment_schema_path = (
            ROOT / "config" / "products" / "surface-attachment-graph.schema.v1.json"
        )
        schema_errors = validate_schema_file(
            surface_attachment_graph,
            surface_attachment_schema_path,
            "surfaceAttachmentGraph",
        )
        if schema_errors:
            raise ValueError(
                "surface attachment graph schema validation failed: "
                + "; ".join(schema_errors)
            )
        surface_attachment_summary = audit_surface_attachment_graph(
            surface_attachment_graph,
            pattern,
            payload,
            expected_product_id=product_id,
        )
        surface_attachment_implementation_paths = [
            ROOT / "src" / "image2outfit" / "surface_attachments.py",
            ROOT / "tools" / "run_reference_product_stage.py",
            ROOT / "tools" / "contract_io.py",
        ]
        attachment_source_artifacts = [pattern_path, path, surface_attachment_path]
        attachment_source_hash = hashlib.sha256(
            "".join(sha256(item) for item in attachment_source_artifacts).encode("ascii")
        ).hexdigest()[:12]
        surface_attachment_report_path = (
            runtime_root(product_id)
            / "stages"
            / f"surface-attachment-layout-{attachment_source_hash}.json"
        )
        write_json(
            surface_attachment_report_path,
            {
                **surface_attachment_summary,
                "sourceArtifacts": [
                    {"path": relative(item), "sha256": sha256(item)}
                    for item in attachment_source_artifacts
                ],
                "schemaArtifact": {
                    "path": relative(surface_attachment_schema_path),
                    "sha256": sha256(surface_attachment_schema_path),
                },
                "implementationArtifacts": [
                    {"path": relative(item), "sha256": sha256(item)}
                    for item in surface_attachment_implementation_paths
                ],
            },
        )
        reference_image_paths = {
            view: runtime_root(product_id) / "normalized" / f"{view}.png"
            for view in ("front", "back")
        }
        surface_attachment_preview_implementation_paths = [
            ROOT / "src" / "image2outfit" / "surface_attachments.py",
            ROOT / "tools" / "run_reference_product_stage.py",
        ]
        preview_source_artifacts = [
            pattern_path,
            path,
            surface_attachment_path,
            *reference_image_paths.values(),
        ]
        preview_source_hash = hashlib.sha256(
            "".join(
                sha256(item)
                for item in [
                    *preview_source_artifacts,
                    *surface_attachment_preview_implementation_paths,
                ]
            ).encode("ascii")
        ).hexdigest()[:12]
        surface_attachment_preview_path = (
            runtime_root(product_id)
            / "stages"
            / f"surface-attachment-host-preview-{preview_source_hash}.png"
        )
        surface_attachment_preview_summary = render_surface_attachment_preview(
            pattern,
            surface_attachment_summary,
            reference_image_paths,
            surface_attachment_preview_path,
        )
        surface_attachment_preview_report_path = surface_attachment_preview_path.with_suffix(
            ".json"
        )
        write_json(
            surface_attachment_preview_report_path,
            {
                "schemaVersion": 1,
                "stage": "infer-stitches",
                "auditType": "2d-host-surface-attachment-visualization",
                "productId": product_id,
                **surface_attachment_preview_summary,
                "evaluationBoundary": (
                    "Reference images and audited overlay polygons projected onto flat host panels only; "
                    "no interlaced linework, stitches, sewn attachment, avatar fit, fabric behavior, "
                    "3D garment, or visual appearance gate is implied."
                ),
                "renderArtifact": {
                    "path": relative(surface_attachment_preview_path),
                    "sha256": sha256(surface_attachment_preview_path),
                },
                "sourceArtifacts": [
                    {"path": relative(item), "sha256": sha256(item)}
                    for item in preview_source_artifacts
                ],
                "implementationArtifacts": [
                    {"path": relative(item), "sha256": sha256(item)}
                    for item in surface_attachment_preview_implementation_paths
                ],
            },
        )
        paths.extend(
            [
                surface_attachment_path,
                surface_attachment_schema_path,
                surface_attachment_report_path,
                surface_attachment_preview_path,
                surface_attachment_preview_report_path,
                ROOT / "src" / "image2outfit" / "surface_attachments.py",
                ROOT / "tools" / "contract_io.py",
            ]
        )

    pins = request.get("toolPins", {}) if isinstance(request, Mapping) else {}
    selected_pattern_tool = (
        pins.get("draft-patterns") if isinstance(pins, Mapping) else None
    )
    if selected_pattern_tool == GARMENTCODE_PATTERN_TOOL:
        garmentcode_dir = runtime_root(product_id) / "pattern" / "garmentcode"
        input_path = garmentcode_dir / "garmentcode-pattern-input.json"
        run_path = garmentcode_dir / "garmentcode-run.json"
        runtime_config_path = ROOT / "config" / "oss-runtimes" / "garmentcode-pygarment.json"
        requirements_path = repo_path(
            read_object(runtime_config_path, "GarmentCode runtime config")["requirementsLockPath"],
            label="GarmentCode requirements lock",
        )
        if not input_path.is_file() or not run_path.is_file():
            raise FileNotFoundError(
                "infer-stitches requires the current pinned GarmentCode 2D result; "
                "run draft-patterns first"
            )
        garmentcode_input = read_object(input_path, "GarmentCode pattern input")
        input_parameters = garmentcode_input.get("parameters", {}).get("image2outfit", {})
        if (
            input_parameters.get("patternContractSha256") != sha256(pattern_path)
            or input_parameters.get("stitchGraphSha256") != sha256(path)
            or input_parameters.get("stitchExportMode") != "strict-boundary-edges"
        ):
            raise ValueError(
                "infer-stitches found a stale or non-strict GarmentCode input; "
                "rerun draft-patterns"
            )
        garmentcode_run = read_object(run_path, "GarmentCode run record")
        runtime_config = read_object(runtime_config_path, "GarmentCode runtime config")
        if (
            garmentcode_run.get("upstreamRevision") != runtime_config.get("upstreamRevision")
            or garmentcode_run.get("requirementsLockSha256") != sha256(requirements_path)
            or garmentcode_run.get("threeDGenerated") is not False
        ):
            raise ValueError("infer-stitches found an incompatible GarmentCode run record")
        connectivity_record["garmentCodeEvidence"] = {
            "tool": GARMENTCODE_PATTERN_TOOL,
            "upstreamRevision": garmentcode_run["upstreamRevision"],
            "pygarmentVersion": runtime_config["pygarmentVersion"],
            "stitchExportMode": garmentcode_run["stitchExportMode"],
            "inputPath": relative(input_path),
            "inputSha256": sha256(input_path),
            "runPath": relative(run_path),
            "runSha256": sha256(run_path),
            "requirementsLockPath": relative(requirements_path),
            "requirementsLockSha256": sha256(requirements_path),
        }
        paths.extend([input_path, run_path, requirements_path])

    write_json(connectivity_path, connectivity_record)
    write_json(edge_length_path, edge_length_record)
    paths.extend(
        [
            connectivity_path,
            edge_length_path,
            ROOT / "src" / "image2outfit" / "stage_contracts.py",
            ROOT / "src" / "image2outfit" / "construction.py",
            ROOT / "src" / "image2outfit" / "seam_stage.py",
            ROOT / "tools" / "run_reference_product_stage.py",
        ]
    )
    if edge_length_audit["status"] != "PASS":
        raise ValueError(
            "stitch edge-length compatibility failed: "
            f"{edge_length_audit['mismatchCount']} pair(s) exceed "
            f"{edge_length_audit['relativeTolerance']:.1%} tolerance; "
            f"evidence: {relative(edge_length_path)}"
        )
    emit(
        result,
        stage=stage,
        product_id=product_id,
        paths=paths,
        extra={
            "artifactContractValidated": True,
            "consumerBindingValidated": True,
            "artifactRole": "stitchGraph",
            "inputPatternSha256": sha256(pattern_path),
            "stitchGraphSha256": sha256(path),
            "stitchesCount": summary["stitchCount"],
            "referencedEdgeCount": summary["referencedEdgeCount"],
            "orientationChecks": summary["orientationChecks"],
            "edgeLengthCompatibilityPassed": (
                edge_length_audit["status"] == "PASS"
            ),
            "edgeLengthCompatibilityAudit": edge_length_audit,
            "edgeLengthCompatibilityAuditPath": relative(edge_length_path),
            "panelConnectivityAudit": connectivity,
            "panelConnectivityAuditPath": relative(connectivity_path),
            **(
                {
                    "surfaceAttachmentLayoutAudit": surface_attachment_summary,
                    "surfaceAttachmentLayoutAuditPath": relative(
                        surface_attachment_report_path
                    ),
                }
                if surface_attachment_summary is not None
                and surface_attachment_report_path is not None
                else {}
            ),
            **(
                {
                    "surfaceAttachmentPreviewStatus": surface_attachment_preview_summary[
                        "status"
                    ],
                    "surfaceAttachmentPreviewPath": relative(
                        surface_attachment_preview_path
                    ),
                    "surfaceAttachmentPreviewSha256": sha256(
                        surface_attachment_preview_path
                    ),
                    "surfaceAttachmentPreviewReportPath": relative(
                        surface_attachment_preview_report_path
                    ),
                }
                if surface_attachment_preview_summary is not None
                and surface_attachment_preview_path is not None
                and surface_attachment_preview_report_path is not None
                else {}
            ),
        },
    )


def stage_initialize(
    job: Mapping[str, Any],
    request: Mapping[str, Any],
    job_path: Path,
    result: Path,
) -> None:
    product_id = str(job["id"])
    manifest_path = repo_path(
        f"{job['productRoot']}/ProductManifest.json", label="product manifest"
    )
    manifest = read_object(manifest_path, "product manifest")
    if manifest.get("productId") != product_id:
        raise ValueError("product manifest identity does not match initialize-3d job")
    review_path, review, review_evidence_paths = (
        validate_prototype_readiness(job, request, job_path)
    )
    gates = manifest.get("technicalGates", {})
    if not isinstance(gates, Mapping):
        raise ValueError("product manifest technicalGates must be an object")
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

    report = write_json(
        runtime_root(product_id) / "initialization" / "initialization-3d.json",
        {
            "schemaVersion": 1,
            "productId": product_id,
            "status": "PASS",
            "visualAppearanceReview": gates.get("visualAppearanceReview", "PENDING"),
            "prototypeReadiness": {
                "status": review["status"],
                "decision": review["decision"],
                "reviewPath": relative(review_path),
                "reviewSha256": sha256(review_path),
                "scope": review["scope"],
                "unassessedAreas": review["unassessedAreas"],
            },
            "productManifestSha256": sha256(manifest_path),
            "collisionPolicy": (
                "positive body-normal offset before clearance refinement"
            ),
            "patternPieceCount": len(pattern["pieces"]),
            "stitchCount": len(stitches["stitches"]),
            "placementOwner": review["placementOwner"],
            **contract_summary,
        },
    )
    emit(
        result,
        stage="initialize-3d",
        product_id=product_id,
        paths=[manifest_path, *review_evidence_paths, report],
        extra={
            "visualAppearanceReview": gates.get("visualAppearanceReview", "PENDING"),
            "prototypeReadiness": {
                "status": review["status"],
                "decision": review["decision"],
                "reviewSha256": sha256(review_path),
                "scope": review["scope"],
            },
            **contract_summary,
        },
    )


def blender_executable() -> str:
    lock = read_object(ROOT / "config" / "toolchain-lock.json", "toolchain lock")
    version = str(lock["blender"]["version"])
    configured = os.environ.get("IMAGE2OUTFIT_BLENDER", "").strip()
    executable_name = "blender.exe" if os.name == "nt" else "blender"
    candidates = [configured] if configured else [
        str(ROOT / ".image2outfit" / f"blender-{version}" / executable_name),
        str(ROOT / ".image2outfit" / "blender" / executable_name),
        shutil.which("blender") or "",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            result = subprocess.run(
                [candidate, "--version"], capture_output=True, text=True,
                check=False, timeout=30,
            )
            actual = result.stdout.splitlines()[0] if result.stdout else ""
            if result.returncode != 0 or actual != f"Blender {version}":
                raise ValueError(f"Blender version must be {version}; observed {actual!r}")
            return candidate
    raise FileNotFoundError(f"Pinned Blender {version} executable was not found")


def _run_garmentcode_boxmesh_preflight(
    job_path: Path,
    job: Mapping[str, Any],
    request: Mapping[str, Any],
) -> tuple[Path, Path] | None:
    pipeline = job.get("garmentPipeline", {})
    if not isinstance(pipeline, Mapping):
        return None
    contract_version = int(pipeline.get("stageContractVersion", 1))
    if contract_version < 2:
        return None
    if pipeline.get("garmentcodeStitchExport") != "strict-boundary-edges":
        raise ValueError(
            "build-blender requires strict-boundary-edges for stage contract v2"
        )

    review_path, review, review_evidence = (
        validate_prototype_readiness(job, request, job_path)
    )
    manifest = read_object(
        repo_path(job["productManifestPath"], label="product manifest"),
        "product manifest",
    )
    gates = manifest.get("technicalGates")
    if (
        manifest.get("productId") != job.get("id")
        or not isinstance(gates, Mapping)
    ):
        raise ValueError(
            "build-blender product manifest identity or technicalGates is invalid"
        )

    runtime_config = read_object(
        ROOT / "config" / "oss-runtimes" / "garmentcode-pygarment.json",
        "GarmentCode runtime config",
    )
    if (
        runtime_config.get("schemaVersion") != 1
        or runtime_config.get("runtimeId") != GARMENTCODE_RUNTIME.runtime_id
        or runtime_config.get("upstreamRepository")
        != GARMENTCODE_RUNTIME.upstream_repository
        or runtime_config.get("upstreamRevision")
        != GARMENTCODE_RUNTIME.upstream_revision
        or runtime_config.get("threeDEnabled") is not False
        or runtime_config.get("outputMode") != "2d-panel-layout-only"
    ):
        raise ValueError("GarmentCode 2D runtime contract is inconsistent")
    mesh_audit_config = runtime_config.get("postReviewMeshAudit")
    expected_mesh_audit = {
        "executionStage": "build-blender",
        "api": "pygarment.meshgen.boxmeshgen.BoxMesh",
        "outputMode": "in-memory-sewn-mesh-preflight",
        "threeDEnabled": True,
        "productMeshArtifactWritten": False,
    }
    if mesh_audit_config != expected_mesh_audit:
        raise ValueError("GarmentCode post-review BoxMesh audit contract is inconsistent")

    pattern_path, pattern = validate_product_document(
        job, "patternContractPath", "pattern contract"
    )
    stitch_path, stitch_graph = validate_product_document(
        job, "stitchGraphPath", "stitch graph"
    )
    pattern_summary = validate_pattern_contract(
        pattern, expected_product_id=str(job["id"])
    )
    stitch_summary = validate_stitch_contract(
        stitch_graph, pattern, expected_product_id=str(job["id"])
    )
    pattern_hash = sha256(pattern_path)
    stitch_hash = sha256(stitch_path)
    attempt_name = "build-blender-boxmesh-" + datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )
    attempt_dir = runtime_root(str(job["id"])) / "stages" / "attempts" / attempt_name
    native = pattern_contract_to_garmentcode_preview(
        pattern, stitch_graph, pattern_sha256=pattern_hash,
        stitch_graph_sha256=stitch_hash, stitch_export_mode="strict-boundary-edges",
    )
    if pipeline.get("assemblyPosePath"):
        _pose_path, pose, _measured = validate_assembly_pose(job, pattern)
        for panel_key, piece_id in native["parameters"]["image2outfit"]["panelKeyMap"].items():
            transform = pose["poses"][piece_id]
            native["pattern"]["panels"][panel_key]["rotation"] = transform["rotationDegreesXYZ"]
            native["pattern"]["panels"][panel_key]["translation"] = [v * native["properties"]["units_in_meter"] for v in transform["translationM"]]
            if "cylindricalWrap" in transform:
                native["pattern"]["panels"][panel_key]["image2outfitCylindricalWrap"] = transform["cylindricalWrap"]
                cap_placement = transform["cylindricalWrap"].get("sewnCapPlacement")
                if cap_placement is not None:
                    piece_keys = {value: key for key, value in native["parameters"]["image2outfit"]["panelKeyMap"].items()}
                    for edge in cap_placement["edges"]:
                        edge["targetPanelKey"] = piece_keys[edge["targetPieceId"]]
            if "torsoWrap" in transform:
                native["pattern"]["panels"][panel_key]["image2outfitTorsoWrap"] = transform["torsoWrap"]
            if "legWrap" in transform:
                native["pattern"]["panels"][panel_key]["image2outfitLegWrap"] = transform["legWrap"]
            if "collarWrap" in transform:
                native["pattern"]["panels"][panel_key]["image2outfitCollarWrap"] = transform["collarWrap"]
            if "skirtWrap" in transform:
                native["pattern"]["panels"][panel_key]["image2outfitSkirtWrap"] = transform["skirtWrap"]
    input_path = write_json(attempt_dir / "garmentcode-pattern-input.json", native)
    output_path = attempt_dir / "garmentcode-boxmesh-audit.json"

    upstream_root = repo_path(
        runtime_config["runtimePath"], label="GarmentCode runtime path"
    )
    if not upstream_root.is_dir():
        raise FileNotFoundError(
            "GarmentCode runtime is not installed; run `task oss:garmentcode:setup`"
        )
    python_candidates = (
        upstream_root / ".venv" / "Scripts" / "python.exe",
        upstream_root / ".venv" / "bin" / "python",
    )
    python_executable = next(
        (candidate for candidate in python_candidates if candidate.is_file()), None
    )
    if python_executable is None:
        raise FileNotFoundError(
            "GarmentCode Python environment is missing; run `task oss:garmentcode:setup`"
        )
    requirements_lock_path = repo_path(
        runtime_config["requirementsLockPath"],
        label="GarmentCode requirements lock",
    )
    if not requirements_lock_path.is_file():
        raise FileNotFoundError("GarmentCode requirements lock is missing")
    command = [
        "uv", "run", "--offline", "--no-project", "--no-python-downloads",
        "--python", str(python_executable),
        str(ROOT / "tools" / "run_garmentcode_boxmesh_audit.py"),
        "--input",
        str(input_path),
        "--output",
        str(output_path),
        "--upstream-root",
        str(upstream_root),
        "--upstream-revision",
        str(runtime_config["upstreamRevision"]),
        "--python-version",
        str(runtime_config["pythonVersion"]),
        "--pygarment-version",
        str(runtime_config["pygarmentVersion"]),
        "--requirements-lock",
        str(requirements_lock_path),
    ]
    if pipeline.get("meshSource") == "garmentcode-boxmesh":
        command.extend(["--mesh-output", str(attempt_dir / "sewn-mesh.json")])
    execution = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if not output_path.is_file():
        raise RuntimeError(
            "GarmentCode BoxMesh preflight did not write evidence; "
            f"exit code {execution.returncode}: {execution.stderr or execution.stdout}"
    )
    audit = read_object(output_path, "GarmentCode BoxMesh audit")
    audit["prototypeReadiness"] = {
        "status": review["status"],
        "path": relative(review_path),
        "sha256": sha256(review_path),
        "evidence": [
            {"path": relative(path), "sha256": sha256(path)}
            for path in review_evidence
        ],
    }
    audit["canonicalStitchInputs"] = {
        "patternContractPath": relative(pattern_path),
        "patternContractSha256": pattern_hash,
        "stitchGraphPath": relative(stitch_path),
        "stitchGraphSha256": stitch_hash,
    }
    write_json(output_path, audit)
    if execution.returncode != 0 or audit.get("status") != "PASS":
        raise RuntimeError(
            "GarmentCode BoxMesh preflight blocked Blender; "
            f"status={audit.get('status')}, "
            f"exception={audit.get('exceptionType')}: {audit.get('message')}, "
            f"invalid stitches={audit.get('invalidStitchCount', 'unknown')}, "
            f"topology={json.dumps(audit.get('meshTopologyAudit', {}), sort_keys=True)}, "
            f"review={relative(review_path)}, evidence={relative(output_path)}"
        )
    if (
        audit.get("inputSha256") != sha256(input_path)
        or audit.get("upstreamRevision") != runtime_config["upstreamRevision"]
        or audit.get("requirementsLockSha256") != sha256(requirements_lock_path)
        or audit.get("patternPanels") != pattern_summary["pieceCount"]
        or audit.get("stitchPairs") != stitch_summary["stitchCount"]
        or audit.get("inMemoryMeshAssembly") is not True
        or not isinstance(audit.get("meshVertexCount"), int)
        or not isinstance(audit.get("meshFaceCount"), int)
        or audit.get("productMeshArtifactWritten") is not False
    ):
        raise ValueError("GarmentCode BoxMesh audit evidence does not match its inputs")
    if pipeline.get("meshSource") == "garmentcode-boxmesh":
        mesh_path = repo_path(audit["meshExchangePath"], label="sewn mesh exchange")
        if sha256(mesh_path) != audit["meshExchangeSha256"]:
            raise ValueError("Sewn mesh exchange hash does not match audit")
    return input_path, output_path


def stage_build(
    job_path: Path,
    job: Mapping[str, Any],
    request: Mapping[str, Any],
    result: Path,
) -> None:
    product_id = str(job["id"])
    boxmesh_evidence = _run_garmentcode_boxmesh_preflight(job_path, job, request)
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
    build_env = dict(os.environ)
    if job["garmentPipeline"].get("meshSource") == "garmentcode-boxmesh":
        if boxmesh_evidence is None:
            raise ValueError("Sewn prototype requires a validated BoxMesh exchange")
        audit = read_object(boxmesh_evidence[1], "BoxMesh audit")
        build_env["IMAGE2OUTFIT_SEWN_MESH_PATH"] = audit["meshExchangePath"]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=build_env,
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
        paths=[
            blend,
            report,
            log,
            *([*boxmesh_evidence] if boxmesh_evidence is not None else []),
            *(
                [repo_path(read_object(boxmesh_evidence[1], "BoxMesh audit")["meshExchangePath"], label="sewn mesh exchange")]
                if job["garmentPipeline"].get("meshSource") == "garmentcode-boxmesh"
                and boxmesh_evidence is not None else []
            ),
        ],
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
            **(
                {
                    "garmentCodeBoxMeshPreflight": "PASS",
                    "garmentCodeBoxMeshInputSha256": sha256(boxmesh_evidence[0]),
                    "garmentCodeBoxMeshAuditSha256": sha256(boxmesh_evidence[1]),
                }
                if boxmesh_evidence is not None
                else {}
            ),
        },
    )


def stage_simulate(job: Mapping[str, Any], result: Path) -> None:
    product_id = str(job["id"])
    report = repo_path(
        f"{job['productRoot']}/Evidence/Build/cloth-simulation.json",
        label="cloth report",
    )
    simulation_log = None
    if job.get("garmentPipeline", {}).get("meshSource") == "garmentcode-boxmesh":
        simulation_log = runtime_root(product_id) / "reports" / "cloth-simulation.log"
        simulation_log.parent.mkdir(parents=True, exist_ok=True)
        command = [blender_executable(), "--background", "--factory-startup", "--python-exit-code", "1",
                   "--python", str(ROOT / "tools/blender_cloth_simulation.py"), "--", "--job",
                   str(ROOT / "config/products" / product_id / "job.json"), "--prototype"]
        execution = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        simulation_log.write_text(execution.stdout + "\n" + execution.stderr, encoding="utf-8")
        if execution.returncode:
            raise RuntimeError(f"Native sewn cloth solve failed; see {relative(simulation_log)}: {execution.stderr[-2500:]}")
    payload = read_object(report, "cloth simulation report")
    candidate_paths = []
    if simulation_log is not None:
        if (payload.get("sourceBlendSha256") != sha256(repo_path(job["blendPath"], label="blend"))
                or payload.get("constructionSha256") != sha256(repo_path(job["garmentPipeline"]["constructionPath"], label="construction"))):
            raise ValueError("cloth experiment input binding is stale")
        candidate = repo_path(payload["candidatePath"], label="cloth candidate")
        if sha256(candidate) != payload["candidateSha256"]:
            raise ValueError("cloth candidate hash mismatch")
        candidate_paths = [candidate, simulation_log]
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
        paths=[construction_path, report, blend, *candidate_paths],
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
    if job.get("garmentPipeline", {}).get("meshSource") == "garmentcode-boxmesh":
        log = runtime_root(product_id) / "reports/skin-export.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        command = [blender_executable(), "--background", "--factory-startup", "--python-exit-code", "1",
                   "--python", str(ROOT / "tools/blender_sewn_skin_export.py"), "--", "--job",
                   str(ROOT / "config/products" / product_id / "job.json")]
        execution = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        log.write_text(execution.stdout + "\n" + execution.stderr, encoding="utf-8")
        if execution.returncode:
            raise RuntimeError(f"Skin/export failed: {execution.stderr[-2500:]}")
        report_path = runtime_root(product_id) / "skin/skin-export-report.json"
        report = read_object(report_path, "skin report")
        source = repo_path(report["weightedBlendPath"], label="weighted prototype")
        fbx = repo_path(job["fbxAssetPath"], label="FBX")
        if (report["productId"] != product_id or report["executionStatus"] != "PASS"
                or sha256(source) != report["weightedBlendSha256"] or sha256(fbx) != report["fbxSha256"]):
            raise ValueError("skin/export artifact binding mismatch")
        emit(result, stage="skin-and-export", product_id=product_id,
             paths=[source, fbx, report_path, log],
             extra={"editableSource": True, "fbxExported": True, "prefabDeclared": False,
                    "qualityDecision": "UNVERIFIED", "grantsFitAcceptance": False,
                    "unweightedVertices": report["unweightedVertices"]})
        return
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
    render_artifacts = []
    if job.get("garmentPipeline", {}).get("meshSource") == "garmentcode-boxmesh":
        log = runtime_root(product_id) / "reports/weighted-render.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        command = [blender_executable(), "--background", "--factory-startup", "--python-exit-code", "1",
                   "--python", str(ROOT / "tools/blender_sewn_render.py"), "--", "--job",
                   str(ROOT / "config/products" / product_id / "job.json")]
        execution = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        log.write_text(execution.stdout + "\n" + execution.stderr, encoding="utf-8")
        if execution.returncode:
            raise RuntimeError(f"Weighted render failed: {execution.stderr[-2500:]}")
        render_artifacts = [log, runtime_root(product_id) / "reports/weighted-render.json"]
    images = review_image_paths(job)
    view_count = len(job["previewPaths"])
    emit(
        result,
        stage="render-evidence",
        product_id=product_id,
        paths=[*images, *render_artifacts],
        extra={
            "fiveViewCount": view_count,
            "poseEvidenceCount": len(images) - view_count,
        },
    )


def _candidate_geometry_quality(
    job: Mapping[str, Any],
) -> tuple[dict[str, Any], list[Path]]:
    """Combine sewn-topology and post-skin weight evidence for the current candidate.

    The sewn prototype report is written before skin transfer and deliberately marks
    every vertex unweighted.  That is not a measurement of the later exported
    garment.  For this pipeline, use the hash-bound skin export report for weight
    facts while retaining the prototype report's topology and fit gates.
    """
    build_report_path = repo_path(
        f"{job['productRoot']}/Evidence/Build/product-build-report.json",
        label="build report",
    )
    report = read_object(build_report_path, "build report")
    evidence_paths = [build_report_path]
    if job.get("garmentPipeline", {}).get("meshSource") == "garmentcode-boxmesh":
        product_id = str(job["id"])
        skin_path = runtime_root(product_id) / "skin/skin-export-report.json"
        skin = read_object(skin_path, "skin export report")
        weighted_blend = repo_path(skin["weightedBlendPath"], label="weighted prototype")
        fbx = repo_path(job["fbxAssetPath"], label="FBX")
        if (
            skin.get("productId") != product_id
            or skin.get("executionStatus") != "PASS"
            or sha256(weighted_blend) != skin.get("weightedBlendSha256")
            or sha256(fbx) != skin.get("fbxSha256")
        ):
            raise ValueError("skin/export evidence is stale or bound to another candidate")
        audits = skin.get("audits")
        weights_verified = (
            isinstance(audits, Mapping)
            and bool(audits)
            and all(isinstance(item, Mapping) and item.get("passed") is True
                    for item in audits.values())
            and skin.get("unweightedVertices") == 0
        )
        combined = dict(report)
        metrics = dict(report.get("metrics", {}))
        metrics["unweightedVertices"] = skin.get("unweightedVertices")
        combined["metrics"] = metrics
        geometry_gate = dict(report.get("geometryGate", {}))
        checks = dict(geometry_gate.get("checks", {}))
        checks["deformWeightsVerified"] = weights_verified
        geometry_gate["checks"] = checks
        combined["geometryGate"] = geometry_gate
        report = combined
        evidence_paths.append(skin_path)
    return geometry_quality(report), evidence_paths


def stage_audit(job: Mapping[str, Any], result: Path) -> None:
    product_id = str(job["id"])
    quality, evidence_paths = _candidate_geometry_quality(job)
    emit(
        result,
        stage="audit-geometry",
        product_id=product_id,
        paths=evidence_paths,
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

    geometry, geometry_evidence = _candidate_geometry_quality(job)
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
        paths=[candidate_path, manifest_path, review_path, *geometry_evidence],
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

    validate_manufacturing_capability(job)
    stage = args.stage
    if stage == "ingest-reference":
        stage_ingest(job, request, result_path)
    elif stage == "normalize-view":
        stage_normalize(job, result_path)
    elif stage == "decompose-garment":
        stage_static(job, stage, "decompositionPath", result_path)
    elif stage == "draft-patterns":
        stage_static(job, stage, "patternContractPath", result_path, request=request)
    elif stage == "infer-stitches":
        stage_static(job, stage, "stitchGraphPath", result_path, request=request)
    elif stage == "initialize-3d":
        stage_initialize(job, request, job_path, result_path)
    elif stage == "build-blender":
        stage_build(job_path, job, request, result_path)
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
