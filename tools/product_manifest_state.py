#!/usr/bin/env python3
"""Single fail-close mutation owner for ProductManifest.json."""

from __future__ import annotations

import copy
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from contract_io import digest, read_json, relative, repo_path, write_json
import production_contract

ROOT = Path(__file__).resolve().parents[1]
UNITY_GATE_NAMES = (
    "unityImport",
    "prefabSerialized",
    "prefabReload",
    "modularAvatar",
    "ndmf",
)


def _manifest_errors(manifest: dict[str, Any], job: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("schemaVersion") != 1:
        errors.append("ProductManifest schemaVersion must be 1")
    if manifest.get("productId") != job.get("id"):
        errors.append("ProductManifest productId must match job.id")
    if manifest.get("productRoot") != job.get("productRoot"):
        errors.append("ProductManifest productRoot must match job.productRoot")
    if not isinstance(manifest.get("technicalGates"), dict):
        errors.append("ProductManifest technicalGates must be an object")
    release_readiness = manifest.get("releaseReadiness")
    if release_readiness is not None and not isinstance(release_readiness, dict):
        errors.append("ProductManifest releaseReadiness must be an object")
    return errors


def _validate_with_completion_policy(
    manifest: dict[str, Any], job: dict[str, Any], root: Path, *, suffix: str
) -> list[str]:
    errors = _manifest_errors(manifest, job)
    manifest_path = repo_path(root, str(job["productManifestPath"]))
    staged = manifest_path.with_name(f".{manifest_path.name}.{suffix}.tmp")
    staged.parent.mkdir(parents=True, exist_ok=True)
    try:
        write_json(staged, manifest)
        staged_job = dict(job)
        staged_job["productManifestPath"] = relative(root, staged)
        errors.extend(production_contract.product_state_errors(staged_job, root))
    finally:
        staged.unlink(missing_ok=True)
    return list(dict.fromkeys(errors))


def _validate_unity_ready_payload(payload: Any, root: Path) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("unity-ready payload must be an object")
    forbidden = {"state", "completionGates", "completionBlocker"} & set(payload)
    if forbidden:
        raise ValueError(
            "policy-derived completion fields cannot be supplied by callers: "
            + ", ".join(sorted(forbidden))
        )
    required = {
        "status",
        "multiMaterialSetup",
        "modularAvatarSetup",
        "ndmfBake",
        "reimport",
        "targetAvatarAssetPath",
        "materialRoles",
        "evidencePath",
        "evidenceSha256",
    }
    if set(payload) != required:
        missing = sorted(required - set(payload))
        extra = sorted(set(payload) - required)
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if extra:
            details.append("extra=" + ",".join(extra))
        raise ValueError("invalid unity-ready payload: " + " ".join(details))
    for field in (
        "status",
        "multiMaterialSetup",
        "modularAvatarSetup",
        "ndmfBake",
        "reimport",
    ):
        if payload.get(field) != "VERIFIED":
            raise ValueError(f"unity-ready {field} must be VERIFIED")
    evidence_path = repo_path(root, str(payload["evidencePath"]))
    if not evidence_path.is_file():
        raise ValueError("unity-ready evidence does not exist")
    if digest(evidence_path) != payload.get("evidenceSha256"):
        raise ValueError("unity-ready evidence SHA-256 mismatch")
    if not isinstance(payload.get("materialRoles"), dict):
        raise ValueError("unity-ready materialRoles must be an object")
    return copy.deepcopy(payload)


def apply_update(
    *,
    manifest_path: Path,
    job: dict[str, Any],
    intent: dict[str, Any],
    root: Path = ROOT,
    before_replace: Callable[[Path, Path], None] | None = None,
) -> dict[str, Any]:
    """Apply one typed ProductManifest transition and atomically replace the file."""
    if intent.get("kind") != "unity-ready":
        raise ValueError(f"unknown ProductManifest update kind: {intent.get('kind')!r}")
    if intent.get("productId") != job.get("id"):
        raise ValueError("ProductManifest update product identity mismatch")
    if intent.get("buildRevision") != job.get("buildRevision"):
        raise ValueError("ProductManifest update revision mismatch")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"ProductManifest missing: {manifest_path}")
    expected_hash = intent.get("expectedManifestSha256")
    if not isinstance(expected_hash, str) or digest(manifest_path) != expected_hash:
        raise ValueError("ProductManifest update is stale: manifest SHA-256 mismatch")

    current = read_json(manifest_path)
    pre_errors = _validate_with_completion_policy(current, job, root, suffix="precheck")
    if pre_errors:
        raise ValueError(
            "ProductManifest precondition failed: " + "; ".join(pre_errors)
        )

    updated = copy.deepcopy(current)
    technical = updated.setdefault("technicalGates", {})
    if not isinstance(technical, dict):
        raise ValueError("ProductManifest technicalGates must be an object")
    for name in UNITY_GATE_NAMES:
        technical[name] = "PASS"
    readiness = updated.setdefault("releaseReadiness", {})
    if not isinstance(readiness, dict):
        raise ValueError("ProductManifest releaseReadiness must be an object")
    readiness["unityReady"] = _validate_unity_ready_payload(intent.get("payload"), root)

    post_errors = _validate_with_completion_policy(
        updated, job, root, suffix="postcheck"
    )
    if post_errors:
        raise ValueError(
            "ProductManifest transition invalid: " + "; ".join(post_errors)
        )

    staged = manifest_path.with_name(f".{manifest_path.name}.replace.tmp")
    try:
        write_json(staged, updated)
        staged_job = dict(job)
        staged_job["productManifestPath"] = relative(root, staged)
        final_errors = _manifest_errors(updated, job)
        if final_errors:
            raise ValueError(
                "staged ProductManifest invalid: " + "; ".join(final_errors)
            )
        if before_replace is not None:
            before_replace(staged, manifest_path)
        os.replace(staged, manifest_path)
    finally:
        staged.unlink(missing_ok=True)

    stored = read_json(manifest_path)
    stored_errors = _manifest_errors(stored, job)
    if stored_errors:
        raise RuntimeError(
            "stored ProductManifest failed post-write validation: "
            + "; ".join(stored_errors)
        )
    return stored


def replace_legacy_snapshot(
    manifest_path: Path,
    proposed: dict[str, Any],
    *,
    root: Path = ROOT,
    before_replace: Callable[[Path, Path], None] | None = None,
) -> dict[str, Any]:
    """Convert the existing Unity-ready caller snapshot into the typed transition."""
    if not manifest_path.is_file():
        raise FileNotFoundError(f"ProductManifest missing: {manifest_path}")
    current = read_json(manifest_path)
    job_path_value = current.get("sourceJobPath")
    if not isinstance(job_path_value, str) or not job_path_value:
        raise ValueError("ProductManifest sourceJobPath is required for mutation")
    job = read_json(repo_path(root, job_path_value))
    if not isinstance(job, dict) or not job:
        raise ValueError("ProductManifest source job is unreadable")

    allowed_top_level = {"technicalGates", "releaseReadiness"}
    for key in set(current) | set(proposed):
        if key not in allowed_top_level and current.get(key) != proposed.get(key):
            raise ValueError(
                f"direct ProductManifest field mutation is forbidden: {key}"
            )

    current_technical = current.get("technicalGates")
    proposed_technical = proposed.get("technicalGates")
    if not isinstance(current_technical, dict) or not isinstance(
        proposed_technical, dict
    ):
        raise ValueError("ProductManifest technicalGates must be objects")
    for key in set(current_technical) | set(proposed_technical):
        if key in UNITY_GATE_NAMES:
            if proposed_technical.get(key) != "PASS":
                raise ValueError(f"Unity-ready transition requires {key}=PASS")
        elif current_technical.get(key) != proposed_technical.get(key):
            raise ValueError(f"direct technical gate mutation is forbidden: {key}")

    current_readiness = current.get("releaseReadiness", {})
    proposed_readiness = proposed.get("releaseReadiness", {})
    if not isinstance(current_readiness, dict) or not isinstance(
        proposed_readiness, dict
    ):
        raise ValueError("ProductManifest releaseReadiness must be objects")
    for key in set(current_readiness) | set(proposed_readiness):
        if key != "unityReady" and current_readiness.get(key) != proposed_readiness.get(
            key
        ):
            raise ValueError(f"direct release readiness mutation is forbidden: {key}")
    payload = proposed_readiness.get("unityReady")

    return apply_update(
        manifest_path=manifest_path,
        job=job,
        intent={
            "kind": "unity-ready",
            "productId": job.get("id"),
            "buildRevision": job.get("buildRevision"),
            "expectedManifestSha256": digest(manifest_path),
            "payload": payload,
        },
        root=root,
        before_replace=before_replace,
    )


def record_workflow_attempt(
    *,
    manifest_path: Path,
    job: dict[str, Any],
    checkpoint_path: Path,
    expected_manifest_sha256: str,
    root: Path = ROOT,
    manufacturing_failure_path: Path | None = None,
    environment_failure_path: Path | None = None,
    before_replace: Callable[[Path, Path], None] | None = None,
) -> dict[str, Any]:
    """Synchronize only the resumable handoff from a verified pipeline checkpoint.

    The checkpoint is the source of stage/run evidence. This transition cannot
    alter technical gates or release readiness.
    """
    root = root.resolve()
    manifest_path = manifest_path.resolve()
    checkpoint_path = checkpoint_path.resolve()
    if not manifest_path.is_file():
        raise FileNotFoundError(f"ProductManifest missing: {manifest_path}")
    if not checkpoint_path.is_file():
        raise FileNotFoundError(f"pipeline checkpoint missing: {checkpoint_path}")
    if job.get("id") is None or job.get("buildRevision") is None:
        raise ValueError("workflow handoff requires job id and buildRevision")
    if digest(manifest_path) != expected_manifest_sha256:
        raise ValueError("workflow handoff is stale: ProductManifest SHA-256 mismatch")

    current = read_json(manifest_path)
    # A workflow attempt records execution evidence only. A product with a
    # failed technical gate must still be able to record its failed or rejected
    # attempt without changing that gate or release readiness.
    pre_errors = _manifest_errors(current, job)
    if pre_errors:
        raise ValueError(
            "ProductManifest precondition failed: " + "; ".join(pre_errors)
        )

    checkpoint_hash = digest(checkpoint_path)
    checkpoint = read_json(checkpoint_path)
    product_id = str(job["id"])
    run_id = checkpoint.get("run_id")
    if checkpoint.get("product_id") != product_id:
        raise ValueError("workflow checkpoint product identity mismatch")
    if str(checkpoint.get("execution_mode", "")).upper() != "EXECUTE":
        raise ValueError("workflow handoff requires an execute-mode checkpoint")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("workflow checkpoint run_id is required")

    pipeline_status = checkpoint.get("status")
    if pipeline_status not in {"FAILED", "EXECUTED"}:
        raise ValueError(
            f"workflow checkpoint is not terminal: {pipeline_status!r}"
        )
    completed = checkpoint.get("completed_stages")
    stage_records = checkpoint.get("stage_records")
    if not isinstance(completed, list) or not all(
        isinstance(stage, str) and stage for stage in completed
    ):
        raise ValueError("workflow checkpoint completed_stages is malformed")
    if not isinstance(stage_records, list):
        raise ValueError("workflow checkpoint stage evidence is malformed")

    stage_records_by_name: dict[str, dict[str, Any]] = {}
    for record in stage_records:
        if not isinstance(record, dict):
            raise ValueError("workflow checkpoint contains a malformed stage record")
        stage_name = record.get("stage")
        if isinstance(stage_name, str) and stage_name:
            # Resumed pipelines may contain earlier failed records for a stage;
            # the latest record is the current evidence for that stage.
            stage_records_by_name[stage_name] = record

    completed_evidence: dict[str, dict[str, str]] = {}
    for stage_name in completed:
        record = stage_records_by_name.get(stage_name)
        if record is None or record.get("status") not in {"PASS", "REUSED"}:
            raise ValueError(
                f"completed workflow stage lacks PASS evidence: {stage_name}"
            )
        result_path = record.get("resultPath")
        if not isinstance(result_path, str) or not result_path:
            raise ValueError(
                f"completed workflow stage lacks a result path: {stage_name}"
            )
        result_file = repo_path(root, result_path)
        if not result_file.is_file():
            raise FileNotFoundError(
                f"workflow stage evidence missing: {result_path}"
            )
        if record.get("status") == "REUSED":
            # A resumed run retains the original successful result, rather
            # than executing that stage again. Require the current result to
            # equal the immutable record's embedded execution evidence.
            result = read_json(result_file)
            output = record.get("output")
            if (not isinstance(output, dict)
                    or output.get("mode") != "executed"
                    or result != output.get("result")
                    or result.get("status") != "PASS"
                    or result.get("productId") != product_id
                    or result.get("stage") != stage_name):
                raise ValueError(f"reused workflow stage lacks matching PASS evidence: {stage_name}")
        completed_evidence[stage_name] = {
            "status": str(record["status"]),
            "stageResultSha256": digest(result_file),
        }

    checkpoint_rel = relative(root, checkpoint_path)
    terminal_record = stage_records[-1] if stage_records else None
    failed_record = (
        terminal_record
        if isinstance(terminal_record, dict)
        and terminal_record.get("status") in {"FAILED", "BLOCKED"}
        else None
    )
    if pipeline_status == "FAILED" and failed_record is None:
        raise ValueError("failed workflow checkpoint has no terminal failed stage")
    if pipeline_status == "EXECUTED" and (
        terminal_record is None or terminal_record.get("status") != "PASS"
    ):
        raise ValueError("executed workflow checkpoint has no terminal PASS stage")

    last_passed_stage = completed[-1] if completed else None
    if last_passed_stage:
        last_result_path = stage_records_by_name[last_passed_stage]["resultPath"]
        last_result_file = repo_path(root, last_result_path)
        stage_evidence_path = relative(root, last_result_file)
        stage_evidence_sha256 = digest(last_result_file)
    else:
        stage_evidence_path = checkpoint_rel
        stage_evidence_sha256 = checkpoint_hash

    failed_stage = failed_record.get("stage") if failed_record else None
    failed_output = failed_record.get("output") if failed_record else None
    failure_message = (
        failed_output.get("error")
        if isinstance(failed_output, dict)
        else None
    )
    if failure_message is not None:
        failure_message = str(failure_message)[:2000]
    technical_gates = current.get("technicalGates")
    if not isinstance(technical_gates, dict):
        raise ValueError("ProductManifest technicalGates must be an object")
    visual_status = technical_gates.get("visualAppearanceReview")
    if failure_message and "MANUFACTURING_CAPABILITY_MISSING" in failure_message:
        next_action = (
            "Implement and register the product-specific Blender builder and verify "
            "target assets. Resume this checkpoint; do not repeat unchanged 2D diagnostics."
        )
    elif failed_stage:
        next_action = (
            f"Inspect the {failed_stage} failure in {checkpoint_rel}, resolve it, "
            "then resume from this checkpoint."
        )
    else:
        next_action = (
            "Review the completed workflow checkpoint and continue through the "
            "independent product-quality and release gates."
        )

    handoff = current.get("handoff")
    if not isinstance(handoff, dict):
        raise ValueError("ProductManifest handoff must be an object")
    updated = copy.deepcopy(current)
    updated_handoff = updated["handoff"]
    updated_handoff["resumeFrom"] = checkpoint_rel
    updated_handoff["nextAction"] = next_action
    updated_handoff["lastAttempt"] = {
        "runId": run_id,
        "status": (
            "PARTIAL"
            if pipeline_status == "FAILED" and completed
            else pipeline_status
        ),
        "checkedAt": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "visualAppearanceReview": visual_status,
        "lastPassedStage": last_passed_stage,
        "stageEvidence": stage_evidence_path,
        "stageEvidenceSha256": stage_evidence_sha256,
        "completedStages": completed_evidence,
        "contractResult": (
            f"Workflow {pipeline_status}; completed {len(completed)} stage(s)."
        ),
        "failedAttemptEvidencePaths": (
            [checkpoint_rel] if pipeline_status == "FAILED" else []
        ),
        "checkpointPath": checkpoint_rel,
        "checkpointSha256": checkpoint_hash,
        "blockedStage": failed_stage,
        "failure": failure_message,
        "nextAction": next_action,
    }

    if "build-blender" in completed:
        build_result_path = repo_path(root, stage_records_by_name["build-blender"]["resultPath"])
        build_result = read_json(build_result_path)
        if (build_result.get("productId") != product_id
                or build_result.get("status") != "PASS"):
            raise ValueError("manufacturing execution evidence identity/status mismatch")
        artifacts = build_result.get("evidence", [])
        for artifact in artifacts:
            if digest(repo_path(root, artifact["path"])) != artifact["sha256"]:
                raise ValueError("manufacturing execution artifact is stale")
        sources = [item for item in artifacts if item["path"].endswith(".blend")]
        reports = [item for item in artifacts if item["path"].endswith("/product-build-report.json")]
        if build_result.get("garmentCodeBoxMeshPreflight") == "PASS":
            if len(sources) != 1 or len(reports) != 1:
                raise ValueError("sewn prototype requires one source and build report")
            report = read_json(repo_path(root, reports[0]["path"]))
            if (report.get("productId") != product_id
                    or report.get("sourceBlendSha256") != sources[0]["sha256"]):
                raise ValueError("sewn prototype source binding mismatch")
            for field, hash_field in (("patternContractPath", "patternSha256"),
                                      ("stitchGraphPath", "stitchGraphSha256")):
                if digest(repo_path(root, job["garmentPipeline"][field])) != report["canonicalInputs"][hash_field]:
                    raise ValueError("sewn prototype canonical inputs are stale")
            updated_handoff["manufacturingPrototype"] = {
                "stage": "build-blender",
                "executionDisposition": build_result.get("executionDisposition"),
                "qualityDecision": build_result.get("qualityDecision"),
                "sourcePath": sources[0]["path"], "sourceSha256": sources[0]["sha256"],
                "reportPath": reports[0]["path"], "reportSha256": reports[0]["sha256"],
                "metrics": report.get("metrics"),
                "grantsQualityAcceptance": False,
            }
            updated_handoff.pop("manufacturingFailure", None)
            updated_handoff.pop("environmentFailure", None)
            if failed_stage == "simulate-cloth":
                updated_handoff["nextAction"] = (
                    "Implement physical cloth settling and target-avatar fit for the saved "
                    "editable sewn prototype, then produce current-input-bound cloth evidence "
                    "and resume this checkpoint. Deform weights, Shape Keys, rendered appearance, "
                    "and runtime acceptance remain required."
                )
            if (failed_stage == "simulate-cloth" and failure_message
                    and "Declared rest shape produced no measurable native Cloth response" in failure_message):
                updated_handoff["nextAction"] = (
                    "Replace the ineffective canonical-row rest-shape linkage with explicit "
                    "crease-aligned skirt topology and measured folded geometry in the existing "
                    "product builder. Preserve the sewn waist and sleeve improvements; measure "
                    "row circumference and seam continuity before resuming this checkpoint. "
                    "Do not repeat unchanged rest-key or 2D diagnostics. Rendered appearance, "
                    "fit, weights, Shape Keys, Unity/VRChat and release remain unverified."
                )
            updated_handoff["lastAttempt"]["nextAction"] = updated_handoff["nextAction"]

    if manufacturing_failure_path is not None:
        probe_path = manufacturing_failure_path.resolve()
        product_runtime = root / ".image2outfit" / "products" / str(job["id"])
        if product_runtime not in probe_path.parents:
            raise ValueError("manufacturing failure evidence escapes product runtime")
        probe = read_json(probe_path)
        if probe.get("status") != "FAIL" or probe.get("productMeshArtifactWritten") is not False:
            raise ValueError("manufacturing failure must be a rejected preflight")
        bindings = probe.get("canonicalStitchInputs", {})
        for path_key, hash_key, job_key in (
            ("patternContractPath", "patternContractSha256", "patternContractPath"),
            ("stitchGraphPath", "stitchGraphSha256", "stitchGraphPath"),
        ):
            if bindings.get(path_key) != job["garmentPipeline"][job_key]:
                raise ValueError("manufacturing failure product input mismatch")
            bound = repo_path(root, bindings[path_key])
            if digest(bound) != bindings.get(hash_key):
                raise ValueError("manufacturing failure input is stale")
        for item in probe["prototypeReadiness"]["evidence"]:
            if digest(repo_path(root, item["path"])) != item["sha256"]:
                raise ValueError("manufacturing readiness evidence is stale")
        updated_handoff["manufacturingFailure"] = {
            "stage": "build-blender", "status": "FAIL",
            "evidencePath": relative(root, probe_path), "sha256": digest(probe_path),
            "invalidStitchIds": [item["stitchId"] for item in probe["invalidStitches"]],
            "topology": probe.get("meshTopologyAudit"),
            "currentInputsMatch": True,
            "grantsStageCompletion": False,
        }
        if probe.get("inMemoryMeshAssembly") is True:
            updated_handoff.pop("environmentFailure", None)
        if probe.get("invalidStitchCount"):
            updated_handoff["nextAction"] = (
                "Resolve the stitch endpoint conflicts listed in manufacturingFailure "
                "and rerun the sewn-mesh preflight. No visual, fit, or release PASS is implied."
            )
        else:
            updated_handoff["nextAction"] = (
                "Locate the degenerate sewn faces and author product-specific panel "
                "assembly transforms from the target-avatar measurements. Preserve "
                "pattern dimensions and rerun the 3D preflight; do not repeat unchanged 2D diagnostics."
            )

    if environment_failure_path is not None:
        env_path = environment_failure_path.resolve()
        if root / ".image2outfit" / "products" / str(job["id"]) not in env_path.parents:
            raise ValueError("environment failure escapes product runtime")
        env_failure = read_json(env_path)
        if (env_failure.get("productId") != job["id"]
            or env_failure.get("status") != "BLOCKED"
            or env_failure.get("code") != "DISK_SPACE_EXHAUSTED"):
            raise ValueError("invalid environment failure evidence")
        job_path = root / "config" / "products" / str(job["id"]) / "job.json"
        if digest(job_path) != env_failure.get("jobSha256"):
            raise ValueError("environment failure job binding is stale")
        for field, hash_field in (("patternContractPath", "patternSha256"),
                                  ("stitchGraphPath", "stitchGraphSha256")):
            if digest(repo_path(root, job["garmentPipeline"][field])) != env_failure.get(hash_field):
                raise ValueError("environment failure input binding is stale")
        updated_handoff["environmentFailure"] = {
            "status": "BLOCKED", "code": env_failure["code"],
            "evidencePath": relative(root, env_path), "sha256": digest(env_path),
        }
        if "manufacturingFailure" in updated_handoff:
            prior = read_json(repo_path(root, updated_handoff["manufacturingFailure"]["evidencePath"]))
            updated_handoff["manufacturingFailure"]["currentInputsMatch"] = (
                prior["canonicalStitchInputs"]["patternContractSha256"] == env_failure["patternSha256"]
                and prior["canonicalStitchInputs"]["stitchGraphSha256"] == env_failure["stitchGraphSha256"]
            )
        updated_handoff["nextAction"] = env_failure["nextAction"]

    review_value = job.get("garmentPipeline", {}).get("visualReviewPath")
    if review_value and "render-evidence" in completed:
        review_file = repo_path(root, review_value)
        if review_file.is_file():
            from candidate_quality import validate_visual_review, verify_inspected_images

            review_document = read_json(review_file)
            review = validate_visual_review(review_document, product_id=product_id,
                                            revision_id=str(job["buildRevision"]))
            image_paths = [*job["previewPaths"].values(), *job["posePaths"].values()]
            current_images = {value: digest(repo_path(root, value)) for value in image_paths}
            review_is_current = dict(review["inspectedImages"]) == current_images
            if not review_is_current:
                updated_handoff["currentVisualReview"] = {
                    "decision": review["decision"], "status": "STALE",
                    "currentInputsMatch": False, "evidencePath": relative(root, review_file),
                    "sha256": digest(review_file), "grantsQualityAcceptance": False,
                }
                updated_handoff["nextAction"] = (
                    "Directly inspect the newly generated render evidence and replace the stale "
                    "visual review with current image hashes. Do not reuse prior visual acceptance."
                )
                updated_handoff["lastAttempt"]["nextAction"] = updated_handoff["nextAction"]
            else:
                verify_inspected_images(review["inspectedImages"], current_images)
            if review_is_current and review["decision"] == "REJECT":
                updated_handoff["currentVisualReview"] = {
                    "decision": "REJECT", "evidencePath": relative(root, review_file),
                    "currentInputsMatch": True,
                    "sha256": digest(review_file), "findings": review["findings"],
                    "grantsQualityAcceptance": False,
                }
                updated_handoff["nextAction"] = (
                    "Correct the actual rendered defects recorded in currentVisualReview, "
                    "starting with panel assembly and target-body fit; then regenerate the "
                    "weighted candidate and directly inspect its new renders."
                )
                if isinstance(review_document.get("nextAction"), str) and review_document["nextAction"].strip():
                    updated_handoff["nextAction"] = review_document["nextAction"]
                updated_handoff["lastAttempt"]["nextAction"] = updated_handoff["nextAction"]

    if updated.get("technicalGates") != current.get("technicalGates"):
        raise RuntimeError("workflow handoff must not alter technical gates")
    if updated.get("releaseReadiness") != current.get("releaseReadiness"):
        raise RuntimeError("workflow handoff must not alter release readiness")
    post_errors = _manifest_errors(updated, job)
    if post_errors:
        raise ValueError(
            "ProductManifest workflow handoff invalid: " + "; ".join(post_errors)
        )
    if digest(manifest_path) != expected_manifest_sha256:
        raise ValueError(
            "workflow handoff became stale before replace: ProductManifest changed"
        )

    staged = manifest_path.with_name(
        f".{manifest_path.name}.workflow-{uuid.uuid4().hex}.replace.tmp"
    )
    try:
        write_json(staged, updated)
        staged_job = dict(job)
        staged_job["productManifestPath"] = relative(root, staged)
        final_errors = _manifest_errors(updated, job)
        if final_errors:
            raise ValueError(
                "staged ProductManifest invalid: " + "; ".join(final_errors)
            )
        if before_replace is not None:
            before_replace(staged, manifest_path)
        os.replace(staged, manifest_path)
    finally:
        staged.unlink(missing_ok=True)

    stored = read_json(manifest_path)
    if _manifest_errors(stored, job):
        raise RuntimeError("stored ProductManifest failed post-write validation")
    if stored.get("technicalGates") != current.get("technicalGates"):
        raise RuntimeError("stored workflow handoff changed technical gates")
    if stored.get("releaseReadiness") != current.get("releaseReadiness"):
        raise RuntimeError("stored workflow handoff changed release readiness")
    return stored
