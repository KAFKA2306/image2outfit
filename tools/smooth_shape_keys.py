#!/usr/bin/env python3
"""Safe Smooth Shape Keys bridge for Blender garment builds.

The vendor add-on is intentionally not bundled. Exact module/operator ids are
read from the product construction contract and must come from the installed
add-on, never from guesses in this repository.
"""
from __future__ import annotations

import importlib
import json
import math
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROVIDER = "maxwilso-smooth-shape-keys"
REPORT_NAME = "smooth-shape-keys.json"
OPERATOR_ID = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$"
)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _construction(job: dict[str, Any], root: Path) -> dict[str, Any]:
    product_id = str(job.get("id") or "")
    return _read_json(
        root / "config" / "products" / product_id / "construction.json"
    )


def _report_path(job: dict[str, Any], root: Path) -> Path:
    value = job.get("artifactDir")
    if not isinstance(value, str) or not value:
        raise ValueError("job.artifactDir is required")
    path = (root / value).resolve()
    root = root.resolve()
    if path != root and root not in path.parents:
        raise ValueError("job.artifactDir escapes repository")
    return path / REPORT_NAME


def _contract_errors(contract: Any) -> list[str]:
    if not isinstance(contract, dict):
        return ["construction.shapeKeyPostprocess must be an object"]
    errors: list[str] = []
    if contract.get("provider") != PROVIDER:
        errors.append(f"provider must be {PROVIDER}")
    applicability = contract.get("applicability")
    if applicability not in {"REQUIRED", "NOT_REQUIRED"}:
        errors.append("applicability must be REQUIRED or NOT_REQUIRED")
    reason = contract.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        errors.append("reason is required")
    if applicability == "REQUIRED":
        module = contract.get("module")
        operator = contract.get("operator")
        targets = contract.get("targets")
        invocation = contract.get("invocation")
        properties = contract.get("properties")
        if not isinstance(module, str) or not module.strip():
            errors.append("module is required when applicability is REQUIRED")
        if not isinstance(operator, str) or not OPERATOR_ID.fullmatch(operator):
            errors.append("operator must be an exact Blender operator id")
        if invocation not in {"ACTIVE_KEY", "OPERATOR_MANAGED"}:
            errors.append("invocation must be ACTIVE_KEY or OPERATOR_MANAGED")
        if not isinstance(targets, list) or not targets or not all(
            isinstance(item, str) and item.strip() for item in targets
        ):
            errors.append("targets must contain at least one exact selector")
        if not isinstance(properties, dict):
            errors.append("properties must be an object")
        cleanup = contract.get("cleanupOperator")
        if cleanup is not None and (
            not isinstance(cleanup, str) or not OPERATOR_ID.fullmatch(cleanup)
        ):
            errors.append("cleanupOperator must be an exact Blender operator id")
        cleanup_properties = contract.get("cleanupProperties", {})
        if not isinstance(cleanup_properties, dict):
            errors.append("cleanupProperties must be an object")
    return errors


def _operator(bpy: Any, operator_id: str) -> Any:
    category, name = operator_id.split(".", 1)
    return getattr(getattr(bpy.ops, category), name)


def _coords(block: Any) -> tuple[tuple[float, float, float], ...]:
    return tuple(tuple(float(value) for value in point.co) for point in block.data)


def _uv_state(mesh: Any) -> tuple[Any, ...]:
    return tuple(
        (
            layer.name,
            tuple(tuple(float(value) for value in loop.uv) for loop in layer.data),
        )
        for layer in mesh.uv_layers
    )


def _weights(obj: Any) -> tuple[Any, ...]:
    return tuple(
        tuple(
            sorted(
                (int(group.group), float(group.weight))
                for group in vertex.groups
            )
        )
        for vertex in obj.data.vertices
    )


def _snapshot(bpy: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        mesh = obj.data
        key_blocks = mesh.shape_keys.key_blocks if mesh.shape_keys else []
        result[obj.name] = {
            "topology": (
                len(mesh.vertices),
                len(mesh.edges),
                len(mesh.polygons),
            ),
            "materials": tuple(
                slot.material.name if slot.material is not None else None
                for slot in obj.material_slots
            ),
            "uv": _uv_state(mesh),
            "weights": _weights(obj),
            "keys": {block.name: _coords(block) for block in key_blocks},
        }
    return result


def _selectors(snapshot: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for object_name, state in snapshot.items():
        names = list(state["keys"])
        if not names:
            continue
        for name in names[1:]:
            result.append(f"{object_name}:{name}")
    return result


def _resolve_targets(
    snapshot: dict[str, Any], requested: list[str]
) -> list[str]:
    available = _selectors(snapshot)
    resolved: list[str] = []
    for selector in requested:
        if ":" in selector:
            matches = [value for value in available if value == selector]
        else:
            matches = [
                value
                for value in available
                if value.rsplit(":", 1)[1] == selector
            ]
        for match in matches:
            if match not in resolved:
                resolved.append(match)
    return resolved


def _max_mean_change(
    before: tuple[Any, ...], after: tuple[Any, ...]
) -> tuple[float, float]:
    distances: list[float] = []
    for left, right in zip(before, after, strict=True):
        distance = math.sqrt(
            sum(
                (a - b) ** 2
                for a, b in zip(left, right, strict=True)
            )
        )
        distances.append(distance)
    return (
        max(distances, default=0.0),
        sum(distances) / len(distances) if distances else 0.0,
    )


def _validate(
    before: dict[str, Any],
    after: dict[str, Any],
    targets: set[str],
    *,
    allow_extra_keys: bool,
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    metrics: dict[str, Any] = {"targets": {}, "changedTargetCount": 0}
    if set(before) != set(after):
        errors.append("mesh object set changed")
        return errors, metrics
    for object_name, left in before.items():
        right = after[object_name]
        for field in ("topology", "materials", "uv", "weights"):
            if left[field] != right[field]:
                errors.append(f"{object_name}: {field} changed")
        left_keys = left["keys"]
        right_keys = right["keys"]
        if not left_keys and not right_keys:
            continue
        if not left_keys or not right_keys:
            errors.append(f"{object_name}: shape key container changed")
            continue
        basis_name = next(iter(left_keys))
        if (
            basis_name not in right_keys
            or left_keys[basis_name] != right_keys[basis_name]
        ):
            errors.append(f"{object_name}: Basis changed")
        missing = set(left_keys) - set(right_keys)
        if missing:
            errors.append(
                f"{object_name}: original shape keys missing: "
                + ", ".join(sorted(missing))
            )
        if not allow_extra_keys:
            extra = set(right_keys) - set(left_keys)
            if extra:
                errors.append(
                    f"{object_name}: backup/extra shape keys remain: "
                    + ", ".join(sorted(extra))
                )
        for key_name, left_coords in left_keys.items():
            selector = f"{object_name}:{key_name}"
            if key_name == basis_name or key_name not in right_keys:
                continue
            right_coords = right_keys[key_name]
            if any(
                not math.isfinite(value)
                for point in right_coords
                for value in point
            ):
                errors.append(f"{selector}: non-finite coordinates")
                continue
            if selector not in targets:
                if left_coords != right_coords:
                    errors.append(
                        f"{selector}: non-target shape key changed"
                    )
                continue
            maximum, mean = _max_mean_change(left_coords, right_coords)
            metrics["targets"][selector] = {
                "maxVertexChange": maximum,
                "meanVertexChange": mean,
            }
            if maximum > 0.0:
                metrics["changedTargetCount"] += 1
    return errors, metrics


def _addon_version(module: Any) -> str | None:
    info = getattr(module, "bl_info", None)
    if not isinstance(info, dict):
        return None
    version = info.get("version")
    if isinstance(version, (list, tuple)) and all(
        isinstance(item, int) for item in version
    ):
        return ".".join(str(item) for item in version)
    return str(version) if version else None


def _call(operator: Any, properties: dict[str, Any]) -> None:
    result = operator(**properties)
    if isinstance(result, set) and "FINISHED" not in result:
        raise RuntimeError(f"operator did not finish: {sorted(result)}")


def _activate(bpy: Any, object_name: str, key_name: str) -> None:
    obj = bpy.data.objects[object_name]
    for candidate in bpy.context.selected_objects:
        candidate.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    blocks = obj.data.shape_keys.key_blocks
    obj.active_shape_key_index = blocks.find(key_name)


def apply_for_job(
    job: dict[str, Any],
    *,
    root: Path = ROOT,
    bpy_module: Any | None = None,
) -> dict[str, Any]:
    bpy = bpy_module
    if bpy is None:
        import bpy as bpy_runtime  # type: ignore

        bpy = bpy_runtime

    report_path = _report_path(job, root)
    before = _snapshot(bpy)
    available = _selectors(before)
    base_report: dict[str, Any] = {
        "schemaVersion": 1,
        "provider": PROVIDER,
        "productId": job.get("id"),
        "blenderVersion": str(getattr(bpy.app, "version_string", "")),
        "shapeKeysFound": available,
        "passed": False,
    }
    if not available:
        report = {
            **base_report,
            "passed": True,
            "status": "NOT_APPLICABLE",
            "errors": [],
            "metrics": {"targetCount": 0},
        }
        _write_json(report_path, report)
        return report

    construction = _construction(job, root)
    contract = construction.get("shapeKeyPostprocess")
    errors = _contract_errors(contract)
    if errors:
        report = {**base_report, "status": "BLOCKED", "errors": errors}
        _write_json(report_path, report)
        return report
    assert isinstance(contract, dict)
    if contract["applicability"] == "NOT_REQUIRED":
        report = {
            **base_report,
            "passed": True,
            "status": "EXPLICITLY_NOT_REQUIRED",
            "reason": contract["reason"],
            "errors": [],
            "metrics": {"targetCount": 0},
        }
        _write_json(report_path, report)
        return report

    requested = list(contract["targets"])
    targets = _resolve_targets(before, requested)
    unresolved = [
        selector
        for selector in requested
        if not _resolve_targets(before, [selector])
    ]
    if unresolved or not targets:
        errors = [
            "shape key targets did not resolve: "
            + ", ".join(unresolved or requested)
        ]
        report = {
            **base_report,
            "status": "BLOCKED",
            "errors": errors,
            "requestedTargets": requested,
        }
        _write_json(report_path, report)
        return report

    try:
        module = importlib.import_module(str(contract["module"]))
        operator = _operator(bpy, str(contract["operator"]))
        if contract["invocation"] == "ACTIVE_KEY":
            for selector in targets:
                object_name, key_name = selector.rsplit(":", 1)
                _activate(bpy, object_name, key_name)
                _call(operator, dict(contract["properties"]))
        else:
            first_object, first_key = targets[0].rsplit(":", 1)
            _activate(bpy, first_object, first_key)
            _call(operator, dict(contract["properties"]))

        after_apply = _snapshot(bpy)
        validation_errors, metrics = _validate(
            before,
            after_apply,
            set(targets),
            allow_extra_keys=True,
        )
        if validation_errors:
            report = {
                **base_report,
                "status": "BLOCKED",
                "module": contract["module"],
                "operator": contract["operator"],
                "addonVersion": _addon_version(module),
                "targets": targets,
                "errors": validation_errors,
                "metrics": metrics,
            }
            _write_json(report_path, report)
            return report

        extra_keys = any(
            set(after_apply[name]["keys"]) - set(before[name]["keys"])
            for name in before
        )
        cleanup_id = contract.get("cleanupOperator")
        if extra_keys:
            if not cleanup_id:
                validation_errors.append(
                    "add-on backup shape keys remain but cleanupOperator "
                    "is not configured"
                )
            else:
                _call(
                    _operator(bpy, str(cleanup_id)),
                    dict(contract.get("cleanupProperties", {})),
                )
        after_cleanup = _snapshot(bpy)
        final_errors, final_metrics = _validate(
            before,
            after_cleanup,
            set(targets),
            allow_extra_keys=False,
        )
        validation_errors.extend(final_errors)
        if validation_errors:
            report = {
                **base_report,
                "status": "BLOCKED",
                "module": contract["module"],
                "operator": contract["operator"],
                "addonVersion": _addon_version(module),
                "targets": targets,
                "errors": list(dict.fromkeys(validation_errors)),
                "metrics": final_metrics,
            }
            _write_json(report_path, report)
            return report

        report = {
            **base_report,
            "passed": True,
            "status": "APPLIED",
            "module": contract["module"],
            "operator": contract["operator"],
            "addonVersion": _addon_version(module),
            "targets": targets,
            "errors": [],
            "metrics": final_metrics,
        }
        _write_json(report_path, report)
        return report
    except Exception as exc:
        report = {
            **base_report,
            "status": "BLOCKED",
            "module": contract.get("module"),
            "operator": contract.get("operator"),
            "targets": targets,
            "errors": [f"Smooth Shape Keys invocation failed: {exc}"],
        }
        _write_json(report_path, report)
        return report
