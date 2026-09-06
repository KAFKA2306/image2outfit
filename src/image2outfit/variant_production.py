"""Deterministic materialization of production variants from one base garment recipe."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_ALLOWED_KINDS = {"BASE", "COLOR", "SIZE"}
_ALLOWED_RESULTS = {"PASS", "FAIL"}
_ALLOWED_PROOF_ROLES = {"BASELINE", "COLOR", "SIZE", "NEGATIVE"}
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def stable_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, Mapping) and isinstance(override, Mapping):
        merged = {str(key): copy.deepcopy(value) for key, value in base.items()}
        for key, value in override.items():
            key = str(key)
            merged[key] = deep_merge(merged.get(key), value)
        return merged
    return copy.deepcopy(override)


def _rewrite_value(value: Any, replacements: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        result = value
        for source, target in replacements.items():
            result = result.replace(source, target)
        return result
    if isinstance(value, list):
        return [_rewrite_value(item, replacements) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): _rewrite_value(item, replacements) for key, item in value.items()
        }
    return copy.deepcopy(value)


def _variant_map(recipe: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    variants = recipe.get("variants")
    if not isinstance(variants, list) or not variants:
        raise ValueError("production variant recipe requires variants")
    result: dict[str, Mapping[str, Any]] = {}
    for item in variants:
        if not isinstance(item, Mapping):
            raise ValueError("variant entries must be objects")
        variant_id = item.get("id")
        if not isinstance(variant_id, str) or not _ID_RE.fullmatch(variant_id):
            raise ValueError("variant id is invalid")
        if variant_id in result:
            raise ValueError(f"duplicate variant id: {variant_id}")
        if item.get("kind") not in _ALLOWED_KINDS:
            raise ValueError(f"variant {variant_id!r} kind is invalid")
        if item.get("expectedResult") not in _ALLOWED_RESULTS:
            raise ValueError(f"variant {variant_id!r} expectedResult is invalid")
        if item.get("proofRole") not in _ALLOWED_PROOF_ROLES:
            raise ValueError(f"variant {variant_id!r} proofRole is invalid")
        result[variant_id] = item
    return result


def _validate_required_revalidation(variant: Mapping[str, Any]) -> list[str]:
    stages = variant.get("requiredRevalidation")
    if (
        not isinstance(stages, list)
        or not stages
        or not all(isinstance(stage, str) and stage for stage in stages)
    ):
        raise ValueError("variant requiredRevalidation must be a non-empty string list")
    kind = variant["kind"]
    expected_result = variant["expectedResult"]
    if expected_result == "FAIL":
        required = {"initialize-3d", "build-blender"}
        if not required.issubset(stages):
            raise ValueError("failing variant must validate through its build boundary")
        return list(stages)

    if kind == "COLOR":
        required = {"build-blender", "render-evidence", "visual-review"}
        if not required.issubset(stages):
            raise ValueError("color variant does not revalidate material/render stages")
        forbidden = {"initialize-3d"}
        if forbidden.intersection(stages):
            raise ValueError("color-only variant must not invalidate initialize-3d")
    elif kind == "SIZE":
        required = {
            "initialize-3d",
            "build-blender",
            "render-evidence",
        }
        if not required.issubset(stages):
            raise ValueError("size variant must revalidate fit/build/render")
    return list(stages)


def _runtime_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    root = root.resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"runtime path escapes repository: {relative}")
    return path


def materialize_variant(
    root: Path,
    *,
    base_job: Mapping[str, Any],
    base_request: Mapping[str, Any],
    base_material_recipe: Mapping[str, Any],
    production_recipe: Mapping[str, Any],
    variant_id: str,
    workspace_id: str,
) -> dict[str, Any]:
    """Create an isolated derived job/request/material recipe in runtime state."""

    root = root.resolve()
    base_product_id = production_recipe.get("baseProductId")
    recipe_version = production_recipe.get("recipeVersion")
    if base_product_id != base_job.get("id") or base_product_id != base_request.get(
        "productId"
    ):
        raise ValueError("production recipe/base job/base request identity mismatch")
    if base_material_recipe.get("productId") != base_product_id:
        raise ValueError("base material recipe identity mismatch")
    if not isinstance(recipe_version, str) or not recipe_version:
        raise ValueError("production recipeVersion is required")
    if not isinstance(workspace_id, str) or not _ID_RE.fullmatch(workspace_id):
        raise ValueError("workspace id is invalid")

    variants = _variant_map(production_recipe)
    if variant_id not in variants:
        raise ValueError(f"unknown variant: {variant_id}")
    variant = variants[variant_id]
    required_revalidation = _validate_required_revalidation(variant)

    candidate_id = f"{base_product_id}--{variant_id}"
    runtime_root = root / ".image2outfit" / "variants" / workspace_id / candidate_id
    product_root = f"Assets/GenWorks/{candidate_id}--{workspace_id}"
    base_product_root = str(base_job["productRoot"])

    job = copy.deepcopy(dict(base_job))
    replacements = {
        base_product_root: product_root,
        f"Assets/_Local/Evidence/{base_product_id}": (
            f"Assets/_Local/Evidence/{candidate_id}--{workspace_id}"
        ),
    }
    job = _rewrite_value(job, replacements)
    job["candidateId"] = candidate_id
    job["variantId"] = variant_id
    job["variantRecipeVersion"] = recipe_version
    job["workspaceId"] = workspace_id
    job["productRoot"] = product_root
    job["bodyShapeProfile"] = deep_merge(
        base_job.get("bodyShapeProfile", {}),
        variant.get("bodyShapeProfileOverrides", {}),
    )
    job["geometryVariables"] = deep_merge(
        base_job.get("geometryVariables", {}),
        variant.get("geometryVariablesOverrides", {}),
    )

    material_recipe = deep_merge(
        base_material_recipe,
        variant.get("materialOverrides", {}),
    )
    material_recipe["candidateId"] = candidate_id
    material_recipe["variantId"] = variant_id
    material_recipe["variantRecipeVersion"] = recipe_version

    material_path = runtime_root / "material-recipe.json"
    job_path = runtime_root / "job.json"
    request_path = runtime_root / "request.json"
    report_path = runtime_root / "variant-contract.json"
    visual_review_path = runtime_root / "visual-review.json"
    job["garmentPipeline"]["materialRecipePath"] = material_path.relative_to(
        root
    ).as_posix()
    job["garmentPipeline"]["visualReviewPath"] = visual_review_path.relative_to(
        root
    ).as_posix()

    request = copy.deepcopy(dict(base_request))
    base_job_rel = f"config/products/{base_product_id}/job.json"
    base_request_rel = f"config/pipeline/requests/{base_product_id}.json"
    candidate_runtime_prefix = f".image2outfit/products/{candidate_id}--{workspace_id}/"
    bindings = request.get("stageBindings")
    if not isinstance(bindings, dict):
        raise ValueError("base request stageBindings must be an object")
    for binding in bindings.values():
        if not isinstance(binding, dict):
            raise ValueError("stage binding must be an object")
        command = binding.get("command")
        if isinstance(command, list):
            binding["command"] = [
                str(item)
                .replace(base_job_rel, job_path.relative_to(root).as_posix())
                .replace(base_request_rel, request_path.relative_to(root).as_posix())
                .replace(
                    ".image2outfit/products/{productId}/",
                    candidate_runtime_prefix,
                )
                for item in command
            ]
        result_path = binding.get("resultPath")
        if isinstance(result_path, str):
            binding["resultPath"] = result_path.replace(
                ".image2outfit/products/{productId}/",
                candidate_runtime_prefix,
            )

    variant_contract = {
        "schemaVersion": 1,
        "baseProductId": base_product_id,
        "candidateId": candidate_id,
        "variantId": variant_id,
        "kind": variant["kind"],
        "proofRole": variant["proofRole"],
        "expectedResult": variant["expectedResult"],
        "geometryRelation": variant.get("geometryRelation"),
        "recipeVersion": recipe_version,
        "workspaceId": workspace_id,
        "requiredRevalidation": required_revalidation,
        "bodyShapeProfile": job["bodyShapeProfile"],
        "geometryVariables": job["geometryVariables"],
        "materialRecipeSha256": stable_sha256(material_recipe),
    }
    variant_contract["geometryInputFingerprint"] = stable_sha256(
        {
            "patternContractPath": job["garmentPipeline"]["patternContractPath"],
            "stitchGraphPath": job["garmentPipeline"]["stitchGraphPath"],
            "bodyShapeProfile": job["bodyShapeProfile"],
            "geometryVariables": job["geometryVariables"],
            "buildScript": job["buildScript"],
        }
    )
    variant_contract["variantFingerprint"] = stable_sha256(variant_contract)

    variables = request.setdefault("variables", {})
    if not isinstance(variables, dict):
        raise ValueError("request variables must be an object")
    variables.update(
        {
            "candidateId": candidate_id,
            "variantId": variant_id,
            "variantRecipeVersion": recipe_version,
            "variantFingerprint": variant_contract["variantFingerprint"],
            "workspaceId": workspace_id,
        }
    )
    request["revisionId"] = (
        f"{base_request.get('revisionId', '')}+{recipe_version}:{variant_id}"
    )

    for path, payload in (
        (material_path, material_recipe),
        (job_path, job),
        (request_path, request),
        (report_path, variant_contract),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    return {
        "candidateId": candidate_id,
        "variantId": variant_id,
        "workspaceId": workspace_id,
        "jobPath": job_path,
        "requestPath": request_path,
        "materialRecipePath": material_path,
        "contractPath": report_path,
        "variantContract": variant_contract,
    }


def materialize_all_variants(
    root: Path,
    *,
    base_job: Mapping[str, Any],
    base_request: Mapping[str, Any],
    base_material_recipe: Mapping[str, Any],
    production_recipe: Mapping[str, Any],
    workspace_id: str,
) -> list[dict[str, Any]]:
    variants = _variant_map(production_recipe)
    return [
        materialize_variant(
            root,
            base_job=base_job,
            base_request=base_request,
            base_material_recipe=base_material_recipe,
            production_recipe=production_recipe,
            variant_id=variant_id,
            workspace_id=workspace_id,
        )
        for variant_id in variants
    ]
