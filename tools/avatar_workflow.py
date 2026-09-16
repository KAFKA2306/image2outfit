#!/usr/bin/env python3
"""Deterministic local orchestration for the generated avatar upload set."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from contract_io import digest, read_json, repo_path, write_json

try:
    from PIL import Image, ImageChops, ImageStat
except ImportError:  # pragma: no cover - the locked project set includes Pillow.
    Image = None
    ImageChops = None
    ImageStat = None


ROOT = Path(__file__).resolve().parents[1]
CONFIG_RELATIVE = Path("config/avatar-workflow.v1.json")
GUID_PATTERN = re.compile(r"\bguid:\s*([0-9a-f]{32})\b", re.IGNORECASE)


class AvatarWorkflowError(ValueError):
    """Raised when the workflow contract cannot be safely resolved."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _git_revision(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise AvatarWorkflowError(f"cannot read {path}: {exc}") from exc


def _asset(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value:
        raise AvatarWorkflowError("asset path must be a non-empty string")
    return repo_path(root, value)


def _load_config(root: Path = ROOT) -> dict[str, Any]:
    path = repo_path(root, str(CONFIG_RELATIVE))
    try:
        config = read_json(path)
    except (OSError, ValueError) as exc:
        raise AvatarWorkflowError(f"workflow config is unreadable: {exc}") from exc
    _validate_config(root, config)
    return config


def _validate_config(root: Path, config: dict[str, Any]) -> None:
    if config.get("schemaVersion") != 1:
        raise AvatarWorkflowError("avatar workflow config must use schemaVersion 1")
    paths = config.get("paths")
    if not isinstance(paths, dict):
        raise AvatarWorkflowError("avatar workflow config.paths must be an object")
    for key in ("bakeRoot", "cauRoot", "runtimeRoot", "ledger", "visualBaselineRoot"):
        value = paths.get(key)
        if not isinstance(value, str) or not value:
            raise AvatarWorkflowError(f"avatar workflow config.paths.{key} is required")
        _asset(root, value)
    visual = config.get("visual")
    required_visuals = visual.get("requiredPaths") if isinstance(visual, dict) else None
    if (
        not isinstance(required_visuals, list)
        or not required_visuals
        or not all(isinstance(item, str) and item for item in required_visuals)
    ):
        raise AvatarWorkflowError(
            "avatar workflow visual.requiredPaths must be a non-empty list"
        )
    if not isinstance(visual.get("warningMeanAbsoluteError"), (int, float)):
        raise AvatarWorkflowError(
            "avatar workflow visual.warningMeanAbsoluteError is required"
        )
    outfits = config.get("outfits")
    if not isinstance(outfits, list) or not outfits:
        raise AvatarWorkflowError("avatar workflow outfits must be a non-empty list")
    seen: set[str] = set()
    for index, outfit in enumerate(outfits):
        if not isinstance(outfit, dict):
            raise AvatarWorkflowError(f"outfits[{index}] must be an object")
        for key in ("id", "name", "productId", "prefab", "cauSetting", "visualRoot"):
            if not isinstance(outfit.get(key), str) or not outfit[key]:
                raise AvatarWorkflowError(f"outfits[{index}].{key} is required")
        outfit_id = outfit["id"]
        if outfit_id in seen:
            raise AvatarWorkflowError(f"duplicate outfit id: {outfit_id}")
        seen.add(outfit_id)
        for key in ("prefab", "cauSetting", "visualRoot"):
            _asset(root, outfit[key])


def _selected_outfits(
    config: dict[str, Any], outfit_ids: Iterable[str] | None
) -> list[dict[str, Any]]:
    outfits = [item for item in config["outfits"] if isinstance(item, dict)]
    requested = {item for item in (outfit_ids or []) if item}
    if not requested:
        return outfits
    known = {item["id"] for item in outfits}
    unknown = sorted(requested - known)
    if unknown:
        raise AvatarWorkflowError(f"unknown outfit id(s): {', '.join(unknown)}")
    return [item for item in outfits if item["id"] in requested]


def _meta_guid(path: Path) -> str | None:
    meta = path.with_name(path.name + ".meta")
    if not meta.is_file():
        return None
    match = re.search(
        r"^guid:\s*([0-9a-f]{32})\s*$", _read_text(meta), re.MULTILINE | re.IGNORECASE
    )
    return match.group(1).lower() if match else None


def _referenced_guids(path: Path) -> list[str]:
    return [value.lower() for value in GUID_PATTERN.findall(_read_text(path))]


def _package_report(
    root: Path, config: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    project = config.get("project", {})
    expected_unity = project.get("unityVersion") if isinstance(project, dict) else None
    project_version_path = root / "ProjectSettings" / "ProjectVersion.txt"
    project_version = ""
    if project_version_path.is_file():
        for line in _read_text(project_version_path).splitlines():
            if line.startswith("m_EditorVersion:"):
                project_version = line.split(":", 1)[1].strip()
                break
    if expected_unity and project_version != expected_unity:
        errors.append(
            f"Unity version mismatch: expected {expected_unity}, found {project_version or 'missing'}"
        )

    vpm = (
        read_json(root / "Packages" / "vpm-manifest.json")
        if (root / "Packages" / "vpm-manifest.json").is_file()
        else {}
    )
    upm = (
        read_json(root / "Packages" / "packages-lock.json")
        if (root / "Packages" / "packages-lock.json").is_file()
        else {}
    )
    dependencies = vpm.get("dependencies", {})
    locked = vpm.get("locked", {})
    upm_dependencies = upm.get("dependencies", {})
    package_results: dict[str, Any] = {}
    expected_packages = project.get("packages", {}) if isinstance(project, dict) else {}
    for package_id, expected in expected_packages.items():
        dependency_version = dependencies.get(package_id, {}).get("version")
        locked_version = locked.get(package_id, {}).get("version")
        upm_entry = upm_dependencies.get(package_id, {})
        package_dir = root / "Packages" / package_id
        passed = dependency_version == expected and locked_version == expected
        if not passed:
            errors.append(
                f"package mismatch: {package_id} expected {expected}, "
                f"dependency={dependency_version}, locked={locked_version}"
            )
        package_results[package_id] = {
            "expected": expected,
            "dependency": dependency_version,
            "locked": locked_version,
            "upmSource": upm_entry.get("source"),
            "pathExists": package_dir.is_dir(),
            "passed": passed,
        }
    return {
        "unity": {"expected": expected_unity, "project": project_version},
        "packages": package_results,
        "unityPackageLockPresent": bool(upm),
    }, errors


def _outfit_preflight(
    root: Path, config: dict[str, Any], outfit: dict[str, Any]
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    prefab = _asset(root, outfit["prefab"])
    setting = _asset(root, outfit["cauSetting"])
    visual_root = _asset(root, outfit["visualRoot"])
    for label, path in (
        ("prefab", prefab),
        ("cauSetting", setting),
        ("visualRoot", visual_root),
    ):
        if not path.exists():
            errors.append(f"{label} missing: {path.relative_to(root).as_posix()}")
        elif path.is_file() and not path.with_name(path.name + ".meta").is_file():
            errors.append(
                f"{label} meta missing: {path.relative_to(root).as_posix()}.meta"
            )

    prefab_guid = _meta_guid(prefab) if prefab.is_file() else None
    setting_guids = _referenced_guids(setting) if setting.is_file() else []
    if prefab_guid is None:
        errors.append(f"prefab GUID missing: {outfit['prefab']}")
    elif prefab_guid not in setting_guids:
        errors.append(f"CAU setting does not reference prefab: {outfit['id']}")

    setting_text = _read_text(setting) if setting.is_file() else ""
    if "windows:\n    enabled: 1" not in setting_text:
        errors.append(f"Windows upload is not enabled in CAU setting: {outfit['id']}")
    for platform in ("ios", "quest"):
        if f"{platform}:\n    enabled: 1" in setting_text:
            warnings.append(
                f"{platform} upload is enabled in CAU setting: {outfit['id']}"
            )

    prefab_text = _read_text(prefab) if prefab.is_file() else ""
    serialized_script_count = prefab_text.count("m_Script:")
    descriptor_evidence = "m_Avatar:" in prefab_text and "m_Name:" in prefab_text
    if not descriptor_evidence:
        errors.append(f"avatar descriptor evidence missing in prefab: {outfit['id']}")
    if serialized_script_count < 2:
        warnings.append(
            f"prefab has unusually few serialized script references: {outfit['id']}"
        )

    required_visuals = config["visual"]["requiredPaths"]
    missing_visuals = []
    if visual_root.is_dir():
        for relative_path in required_visuals:
            if not (visual_root / relative_path).is_file():
                missing_visuals.append(
                    (visual_root / relative_path).relative_to(root).as_posix()
                )
    if missing_visuals:
        errors.append(
            f"required visual evidence missing for {outfit['id']}: {', '.join(missing_visuals)}"
        )

    product_manifest = (
        root / "Assets" / "GenWorks" / outfit["productId"] / "ProductManifest.json"
    )
    product_state = None
    if product_manifest.is_file():
        try:
            product_state = read_json(product_manifest).get("state")
        except (OSError, ValueError):
            warnings.append(
                f"product manifest could not be read: {outfit['productId']}"
            )
    else:
        warnings.append(f"product manifest missing: {outfit['productId']}")
    if product_state not in (None, "COMPLETE"):
        warnings.append(f"product lifecycle is {product_state} for {outfit['id']}")

    return {
        "id": outfit["id"],
        "name": outfit["name"],
        "productId": outfit["productId"],
        "prefab": outfit["prefab"],
        "cauSetting": outfit["cauSetting"],
        "visualRoot": outfit["visualRoot"],
        "prefabGuid": prefab_guid,
        "serializedScriptReferences": serialized_script_count,
        "descriptorEvidence": descriptor_evidence,
        "productState": product_state,
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def preflight(
    root: Path = ROOT,
    *,
    config: dict[str, Any] | None = None,
    outfit_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    config = config or _load_config(root)
    _validate_config(root, config)
    package_snapshot, errors = _package_report(root, config)
    cau_group = _asset(root, config["paths"]["cauRoot"]) / "siroino-all-outfits.asset"
    group_guids = _referenced_guids(cau_group) if cau_group.is_file() else []
    selected = _selected_outfits(config, outfit_ids)
    outfits = [_outfit_preflight(root, config, item) for item in selected]
    if not cau_group.is_file():
        errors.append(
            "CAU group asset missing: Assets/UnityMCP_CAU/siroino-all-outfits.asset"
        )
    setting_guids = {_meta_guid(_asset(root, item["cauSetting"])) for item in selected}
    setting_guids.discard(None)
    if len(setting_guids) != len(selected):
        errors.append("one or more selected CAU setting meta GUIDs are missing")
    if not setting_guids.issubset(set(group_guids)):
        errors.append("selected CAU settings are not all present in the CAU group")
    for item in outfits:
        errors.extend(item["errors"])
    warnings = [warning for item in outfits for warning in item["warnings"]]
    return {
        "schemaVersion": 1,
        "tool": "avatar-preflight",
        "checkedAt": _now(),
        "gitRevision": _git_revision(root),
        "configPath": CONFIG_RELATIVE.as_posix(),
        "selectedOutfitCount": len(selected),
        "selectedOutfitIds": [item["id"] for item in selected],
        "packages": package_snapshot,
        "cauGroup": {
            "path": (
                cau_group.relative_to(root).as_posix()
                if cau_group.is_file()
                else "Assets/UnityMCP_CAU/siroino-all-outfits.asset"
            ),
            "exists": cau_group.is_file(),
            "referencedGuidCount": len(group_guids),
        },
        "outfits": outfits,
        "externalBoundary": {
            "unityEditor": "NOT_RUN",
            "vrchatLogin": "NOT_RUN",
            "realUpload": "NOT_RUN",
        },
        "passed": not errors,
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
    }


def _image_metrics(current: Path, baseline: Path) -> dict[str, Any]:
    if Image is None or ImageChops is None or ImageStat is None:
        raise AvatarWorkflowError("Pillow is required for visual regression")
    with Image.open(current) as current_image, Image.open(baseline) as baseline_image:
        current_rgba = current_image.convert("RGBA")
        baseline_rgba = baseline_image.convert("RGBA")
    if current_rgba.size != baseline_rgba.size:
        return {
            "passed": False,
            "status": "ERROR",
            "error": f"image dimensions differ: current={current_rgba.size}, baseline={baseline_rgba.size}",
        }
    difference = ImageChops.difference(current_rgba, baseline_rgba)
    mean_absolute_error = sum(ImageStat.Stat(difference).mean) / 4.0 / 255.0
    gray = difference.convert("L")
    histogram = gray.histogram()
    pixels = current_rgba.width * current_rgba.height
    changed_pixels = sum(histogram[9:])
    return {
        "passed": True,
        "status": "PASS",
        "width": current_rgba.width,
        "height": current_rgba.height,
        "meanAbsoluteError": round(mean_absolute_error, 8),
        "changedPixelRatio": round(changed_pixels / pixels, 8) if pixels else 0.0,
    }


def visual_regression(
    root: Path = ROOT,
    *,
    config: dict[str, Any] | None = None,
    outfit_ids: Iterable[str] | None = None,
    record_baseline: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    config = config or _load_config(root)
    _validate_config(root, config)
    selected = _selected_outfits(config, outfit_ids)
    baseline_root = _asset(root, config["paths"]["visualBaselineRoot"])
    threshold = float(config["visual"]["warningMeanAbsoluteError"])
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    for outfit in selected:
        visual_root = _asset(root, outfit["visualRoot"])
        outfit_baseline = baseline_root / outfit["id"]
        for relative_path in config["visual"]["requiredPaths"]:
            current = visual_root / relative_path
            baseline = outfit_baseline / relative_path
            item: dict[str, Any] = {
                "outfitId": outfit["id"],
                "path": (current.relative_to(root).as_posix()),
                "baselinePath": baseline.relative_to(root).as_posix(),
            }
            if not current.is_file():
                item.update(
                    {
                        "status": "ERROR",
                        "passed": False,
                        "error": "current image missing",
                    }
                )
                errors.append(f"current visual missing: {item['path']}")
            elif record_baseline:
                baseline.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(current, baseline)
                item.update(
                    {
                        "status": "BASELINE_RECORDED",
                        "passed": True,
                        "sha256": digest(current),
                    }
                )
            elif not baseline.is_file():
                item.update(
                    {
                        "status": "ERROR",
                        "passed": False,
                        "error": "baseline image missing",
                    }
                )
                errors.append(f"baseline visual missing: {item['baselinePath']}")
            else:
                try:
                    item.update(_image_metrics(current, baseline))
                except (OSError, ValueError) as exc:
                    item.update({"status": "ERROR", "passed": False, "error": str(exc)})
                if item.get("status") == "ERROR":
                    errors.append(
                        f"visual comparison failed: {item['path']}: {item.get('error')}"
                    )
                elif item.get("meanAbsoluteError", 0) > threshold:
                    item["status"] = "WARN"
                    item["visualGate"] = "NON_BLOCKING"
                    warnings.append(
                        f"visual difference above warning threshold: {item['path']} "
                        f"({item['meanAbsoluteError']:.5f} > {threshold:.5f})"
                    )
            results.append(item)

    return {
        "schemaVersion": 1,
        "tool": "visual-regression",
        "checkedAt": _now(),
        "gitRevision": _git_revision(root),
        "recordBaseline": record_baseline,
        "warningMeanAbsoluteError": threshold,
        "selectedOutfitCount": len(selected),
        "results": results,
        "visualIssuesAreNonBlocking": True,
        "passed": not errors,
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
    }


def _ledger_path(root: Path, config: dict[str, Any]) -> Path:
    return _asset(root, config["paths"]["ledger"])


def _file_fingerprint(root: Path, relative_path: str) -> dict[str, Any]:
    path = _asset(root, relative_path)
    return {
        "path": relative_path,
        "exists": path.is_file(),
        "sha256": digest(path) if path.is_file() else None,
    }


def initialise_ledger(
    root: Path = ROOT,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    config = config or _load_config(root)
    path = _ledger_path(root, config)
    existing = read_json(path) if path.is_file() else {}
    old_entries = {
        item.get("id"): item
        for item in existing.get("outfits", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    outfits = []
    for outfit in config["outfits"]:
        old = old_entries.get(outfit["id"], {})
        entry = {
            "id": outfit["id"],
            "name": outfit["name"],
            "productId": outfit["productId"],
            "prefab": outfit["prefab"],
            "cauSetting": outfit["cauSetting"],
            "status": old.get("status", "PENDING"),
            "sourceFingerprint": {
                "prefab": _file_fingerprint(root, outfit["prefab"]),
                "cauSetting": _file_fingerprint(root, outfit["cauSetting"]),
            },
            "history": old.get("history", []),
        }
        for key in ("blueprintId", "uploadId", "error"):
            if key in old:
                entry[key] = old[key]
        outfits.append(entry)
    value = {
        "schemaVersion": 1,
        "tool": "upload-ledger",
        "workflowId": config["workflowId"],
        "createdAt": existing.get("createdAt", _now()),
        "updatedAt": _now(),
        "gitRevision": _git_revision(root),
        "credentialsStored": False,
        "outfits": outfits,
    }
    write_json(path, value)
    return value


def record_ledger(
    root: Path = ROOT,
    *,
    outfit_id: str,
    status: str,
    blueprint_id: str | None = None,
    upload_id: str | None = None,
    error: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    allowed = {"PENDING", "READY", "UPLOADING", "SUCCEEDED", "FAILED", "SKIPPED"}
    if status not in allowed:
        raise AvatarWorkflowError(f"invalid ledger status: {status}")
    config = config or _load_config(root)
    value = initialise_ledger(root, config=config)
    selected = next(
        (item for item in value["outfits"] if item["id"] == outfit_id), None
    )
    if selected is None:
        raise AvatarWorkflowError(f"unknown outfit id: {outfit_id}")
    selected["status"] = status
    selected["updatedAt"] = _now()
    selected["history"].append(
        {"at": _now(), "status": status, "gitRevision": _git_revision(root)}
    )
    for key, item in (
        ("blueprintId", blueprint_id),
        ("uploadId", upload_id),
        ("error", error),
    ):
        if item is not None:
            selected[key] = item
    value["updatedAt"] = _now()
    value["gitRevision"] = _git_revision(root)
    write_json(_ledger_path(root, config), value)
    return value


def build_plan(
    root: Path = ROOT,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = config or _load_config(root)
    return {
        "schemaVersion": 1,
        "tool": "outfit-pipeline-runner",
        "createdAt": _now(),
        "gitRevision": _git_revision(root),
        "workflowId": config["workflowId"],
        "outfitCount": len(config["outfits"]),
        "outfitIds": [item["id"] for item in config["outfits"]],
        "steps": [
            {"id": "preflight", "kind": "local", "entrypoint": "task avatar:preflight"},
            {
                "id": "visual-regression",
                "kind": "local",
                "entrypoint": "task avatar:visual",
                "visualIssuesAreNonBlocking": True,
            },
            {
                "id": "ndmf-bake",
                "kind": "unity-mcp",
                "status": "DELEGATED",
                "entrypoint": "Unity MCP ndmf.bake",
            },
            {
                "id": "vrc-avatar-audit",
                "kind": "unity-mcp",
                "status": "DELEGATED",
                "entrypoint": "Unity MCP vrc.avatarAudit",
            },
            {
                "id": "cau-upload",
                "kind": "external-publish",
                "status": "REQUIRES_LOGIN",
                "entrypoint": "CAU group upload",
            },
            {
                "id": "upload-ledger",
                "kind": "local",
                "entrypoint": "task avatar:ledger",
            },
        ],
        "credentialsStored": False,
        "realUploadCount": 0,
    }


def run_workflow(
    root: Path = ROOT,
    *,
    config: dict[str, Any] | None = None,
    record_baseline: bool = False,
) -> dict[str, Any]:
    config = config or _load_config(root)
    preflight_result = preflight(root, config=config)
    visual_result = visual_regression(
        root, config=config, record_baseline=record_baseline
    )
    ledger = initialise_ledger(root, config=config)
    result = {
        "schemaVersion": 1,
        "tool": "outfit-pipeline-runner",
        "completedAt": _now(),
        "gitRevision": _git_revision(root),
        "preflight": {
            "passed": preflight_result["passed"],
            "errors": len(preflight_result["errors"]),
            "warnings": len(preflight_result["warnings"]),
        },
        "visualRegression": {
            "passed": visual_result["passed"],
            "errors": len(visual_result["errors"]),
            "warnings": len(visual_result["warnings"]),
        },
        "ledger": {
            "path": config["paths"]["ledger"],
            "outfitCount": len(ledger["outfits"]),
        },
        "externalSteps": {
            "ndmfBake": "DELEGATED_TO_UNITY_MCP",
            "avatarAudit": "DELEGATED_TO_UNITY_MCP",
            "cauUpload": "BLOCKED_UNTIL_VRCHAT_LOGIN",
        },
        "realUploadCount": sum(
            1 for item in ledger["outfits"] if item.get("status") == "SUCCEEDED"
        ),
        "passed": preflight_result["passed"] and visual_result["passed"],
        "errors": [*preflight_result["errors"], *visual_result["errors"]],
        "warnings": [*preflight_result["warnings"], *visual_result["warnings"]],
    }
    return result


def _write_report(root: Path, relative_path: str, value: dict[str, Any]) -> None:
    write_json(_asset(root, relative_path), value)


def dispatch(root: Path, options: argparse.Namespace) -> int:
    try:
        config = _load_config(root)
        outfit_ids = getattr(options, "outfit", None)
        if options.avatar_command == "preflight":
            result = preflight(root, config=config, outfit_ids=outfit_ids)
            output = (
                options.output or f"{config['paths']['runtimeRoot']}/preflight.json"
            )
        elif options.avatar_command == "visual":
            result = visual_regression(
                root,
                config=config,
                outfit_ids=outfit_ids,
                record_baseline=options.record_baseline,
            )
            output = (
                options.output
                or f"{config['paths']['runtimeRoot']}/visual-regression.json"
            )
        elif options.avatar_command == "ledger":
            if options.ledger_action == "init":
                result = initialise_ledger(root, config=config)
            else:
                result = record_ledger(
                    root,
                    config=config,
                    outfit_id=options.outfit_id,
                    status=options.status,
                    blueprint_id=options.blueprint_id,
                    upload_id=options.upload_id,
                    error=options.error,
                )
            output = options.output
        elif options.avatar_command == "plan":
            result = build_plan(root, config=config)
            output = (
                options.output or f"{config['paths']['runtimeRoot']}/pipeline-plan.json"
            )
        elif options.avatar_command == "run":
            result = run_workflow(
                root, config=config, record_baseline=options.record_baseline
            )
            output = options.output or f"{config['paths']['runtimeRoot']}/run.json"
        else:
            raise AvatarWorkflowError(
                f"unknown avatar command: {options.avatar_command}"
            )
        if output:
            _write_report(root, output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("passed", True) else 2
    except (OSError, ValueError, AvatarWorkflowError) as exc:
        print(f"avatar workflow: {exc}", file=sys.stderr)
        return 1
