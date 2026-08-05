from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path.cwd()
TOOL = ROOT / "tools/material_drape_calibration.py"
PROFILE = ROOT / "config/materials/blender-4.4-kes-calibration.v1.json"
WORKFLOW = ROOT / ".github/workflows/material-drape-calibration.yml"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, got {count}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, got {count}")
    return updated


text = TOOL.read_text(encoding="utf-8")
text = replace_once(
    text,
    "RENDER_SUBDIVISION_LEVELS = 2\n",
    "RENDER_SUBDIVISION_LEVELS = 2\n"
    "CONVERGENCE_CHECKPOINTS = (100, 150, 200, 250)\n",
    "checkpoint constants",
)

helper = '''\n\ndef temporal_convergence_report(\n    snapshots: Mapping[str, list[dict[str, Any]]],\n    thresholds: Mapping[str, float],\n) -> dict[str, Any]:\n    required = {\n        "maximumCoefficientDelta",\n        "maximumSupportContactDelta",\n        "maximumMaximumZDeltaM",\n        "maximumMeanVertexDisplacementM",\n        "maximumVertexDisplacementM",\n    }\n    if set(thresholds) != required:\n        raise ValueError("temporalConvergence must define the exact threshold set")\n    parsed = {name: float(thresholds[name]) for name in sorted(required)}\n    if any(not math.isfinite(value) or value < 0 for value in parsed.values()):\n        raise ValueError("temporal convergence thresholds must be finite and non-negative")\n\n    records: list[dict[str, Any]] = []\n    failures: list[dict[str, Any]] = []\n    for material_id, states in snapshots.items():\n        if len(states) < 2:\n            raise ValueError(f"at least two checkpoints are required for {material_id}")\n        previous = states[-2]\n        current = states[-1]\n        previous_coordinates = previous["coordinates"]\n        current_coordinates = current["coordinates"]\n        if len(previous_coordinates) != len(current_coordinates):\n            raise RuntimeError(f"checkpoint topology changed for {material_id}")\n        displacements = [\n            float((right - left).length)\n            for left, right in zip(\n                previous_coordinates, current_coordinates, strict=True\n            )\n        ]\n        deltas = {\n            "coefficientDelta": abs(\n                float(current["metrics"]["cusickDrapeCoefficient"])\n                - float(previous["metrics"]["cusickDrapeCoefficient"])\n            ),\n            "supportContactDelta": abs(\n                float(current["metrics"]["supportContactFraction"])\n                - float(previous["metrics"]["supportContactFraction"])\n            ),\n            "maximumZDeltaM": abs(\n                float(current["metrics"]["maximumZ"])\n                - float(previous["metrics"]["maximumZ"])\n            ),\n            "meanVertexDisplacementM": statistics.fmean(displacements),\n            "maximumVertexDisplacementM": max(displacements),\n        }\n        errors: list[str] = []\n        checks = (\n            ("coefficient-drift", deltas["coefficientDelta"], parsed["maximumCoefficientDelta"]),\n            ("support-contact-drift", deltas["supportContactDelta"], parsed["maximumSupportContactDelta"]),\n            ("maximum-z-drift", deltas["maximumZDeltaM"], parsed["maximumMaximumZDeltaM"]),\n            ("mean-geometry-drift", deltas["meanVertexDisplacementM"], parsed["maximumMeanVertexDisplacementM"]),\n            ("maximum-geometry-drift", deltas["maximumVertexDisplacementM"], parsed["maximumVertexDisplacementM"]),\n        )\n        for name, value, limit in checks:\n            if value > limit:\n                errors.append(name)\n        public_states = [\n            {\n                "frame": int(state["frame"]),\n                "metrics": state["metrics"],\n            }\n            for state in states\n        ]\n        record = {\n            "materialId": material_id,\n            "checkpoints": public_states,\n            "finalInterval": {\n                "fromFrame": int(previous["frame"]),\n                "toFrame": int(current["frame"]),\n                **deltas,\n                "errors": errors,\n                "passed": not errors,\n            },\n        }\n        records.append(record)\n        if errors:\n            failures.append({"materialId": material_id, "errors": errors})\n    return {\n        "checkpointFrames": [int(item["frame"]) for item in next(iter(snapshots.values()))],\n        "thresholds": parsed,\n        "records": records,\n        "failures": failures,\n        "passed": not failures,\n    }\n'''
text = replace_once(
    text,
    "\ndef plausibility_errors(metrics: Mapping[str, float | str]) -> list[str]:\n",
    helper + "\n\ndef plausibility_errors(metrics: Mapping[str, float | str]) -> list[str]:\n",
    "temporal helper insertion",
)

text = replace_once(
    text,
    "    render_materials: bool,\n) -> tuple[list[dict[str, Any]], dict[str, Any]]:\n",
    "    render_materials: bool,\n"
    "    convergence_thresholds: Mapping[str, float],\n"
    ") -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:\n",
    "simulate signature",
)

old_loop = '''    for frame in range(scene.frame_start, scene.frame_end + 1):\n        scene.frame_set(frame)\n        bpy.context.view_layer.update()\n    scene.frame_set(scene.frame_end)\n    bpy.context.view_layer.update()\n    for record in records:\n        metrics = drape_metrics(bpy.data.objects[record["runtime"]["clothObject"]])\n        record["metrics"] = metrics\n        record["plausibilityErrors"] = plausibility_errors(metrics)\n        record["plausibilityWarnings"] = plausibility_warnings(metrics)\n    return records, floor_settings\n'''
new_loop = '''    checkpoint_frames = tuple(\n        frame for frame in CONVERGENCE_CHECKPOINTS if frame <= frame_end\n    )\n    if len(checkpoint_frames) < 2 or checkpoint_frames[-1] != frame_end:\n        raise ValueError(\n            "frame-end must equal a convergence checkpoint and include at least two checkpoints"\n        )\n    snapshots: dict[str, list[dict[str, Any]]] = {\n        record["materialId"]: [] for record in records\n    }\n    for frame in range(scene.frame_start, scene.frame_end + 1):\n        scene.frame_set(frame)\n        bpy.context.view_layer.update()\n        if frame in checkpoint_frames:\n            for record in records:\n                cloth = bpy.data.objects[record["runtime"]["clothObject"]]\n                coordinates, _ = evaluated_geometry(cloth)\n                snapshots[record["materialId"]].append(\n                    {\n                        "frame": frame,\n                        "metrics": drape_metrics(cloth),\n                        "coordinates": coordinates,\n                    }\n                )\n    scene.frame_set(scene.frame_end)\n    bpy.context.view_layer.update()\n    for record in records:\n        metrics = snapshots[record["materialId"]][-1]["metrics"]\n        record["metrics"] = metrics\n        record["plausibilityErrors"] = plausibility_errors(metrics)\n        record["plausibilityWarnings"] = plausibility_warnings(metrics)\n    convergence = temporal_convergence_report(snapshots, convergence_thresholds)\n    return records, floor_settings, convergence\n'''
text = replace_once(text, old_loop, new_loop, "simulate checkpoint loop")

text = text.replace(
    "candidate_records, _ = simulate(\n",
    "candidate_records, _, _ = simulate(\n",
)
text = replace_once(
    text,
    "                render_materials=False,\n            )\n",
    "                render_materials=False,\n"
    "                convergence_thresholds=raw_profile[\"temporalConvergence\"],\n"
    "            )\n",
    "candidate convergence argument",
)
text = replace_once(
    text,
    "    records, floor_settings = simulate(\n",
    "    records, floor_settings, temporal_convergence = simulate(\n",
    "final simulate unpack",
)
text = replace_once(
    text,
    "        render_materials=True,\n    )\n",
    "        render_materials=True,\n"
    "        convergence_thresholds=raw_profile[\"temporalConvergence\"],\n"
    "    )\n",
    "final convergence argument",
)
text = replace_once(
    text,
    '    fixed_scales = raw_profile.get("calibratedElasticScales")\n',
    '    fixed_scales = raw_profile.get("diagnosticElasticScales")\n',
    "diagnostic scale key",
)
text = replace_once(
    text,
    "    passed = (\n        not comparison[\"plausibilityFailures\"]\n",
    "    passed = (\n        temporal_convergence[\"passed\"]\n        and not comparison[\"plausibilityFailures\"]\n",
    "convergence acceptance",
)
text = replace_once(text, '        "schemaVersion": 5,\n', '        "schemaVersion": 6,\n', "schema version")
text = replace_once(
    text,
    '        "selectedElasticScales": selected_scales,\n',
    '        "selectedDiagnosticElasticScales": selected_scales,\n'
    '        "elasticScaleStatus": "diagnostic-until-temporal-convergence-passes",\n'
    '        "temporalConvergence": temporal_convergence,\n',
    "report diagnostic fields",
)
text = replace_once(
    text,
    '            "solver correction rather than a universal physical-unit conversion. "\n',
    '            "diagnostic solver correction rather than a calibrated or universal "\n'
    '            "physical-unit conversion. Temporal convergence is required before "\n'
    '            "coefficient-fit acceptance. "\n',
    "report boundary",
)
TOOL.write_text(text, encoding="utf-8")

profile = json.loads(PROFILE.read_text(encoding="utf-8"))
profile["profileId"] = "blender-4.4.3-kes-cusick-calibration-v9-temporal-audit"
profile["mappingStatus"] = "temporal-convergence-diagnostic"
profile["searchPolicy"] = {
    "spacing": "fixed-scales-temporal-convergence-diagnostic",
    "policy": "evaluate fixed diagnostic material scales at frames 100, 150, 200, and 250; reject coefficient fit unless the final interval is temporally converged",
    "reason": "the 250-frame run changed the 100-frame material ordering and retained rebound or missing support contact, so time stability must be demonstrated before any further fitting",
}
profile["diagnosticElasticScales"] = profile.pop("calibratedElasticScales")
profile["temporalConvergence"] = {
    "maximumCoefficientDelta": 0.02,
    "maximumSupportContactDelta": 0.05,
    "maximumMaximumZDeltaM": 0.005,
    "maximumMeanVertexDisplacementM": 0.003,
    "maximumVertexDisplacementM": 0.015,
}
profile["calibrationFixture"]["purpose"] = (
    "temporal convergence audit at fixed diagnostic material scales before friction "
    "or constitutive re-identification; final validation still requires the published "
    "approximately 4 mm mesh resolution"
)
profile["calibrationScope"]["transferability"] = (
    "diagnostic factors are solver- and discretization-specific and remain uncalibrated "
    "until temporal convergence and direct visual review both pass"
)
PROFILE.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

workflow = WORKFLOW.read_text(encoding="utf-8")
workflow = replace_once(workflow, 'assert report["schemaVersion"] == 5', 'assert report["schemaVersion"] == 6', "workflow schema")
workflow = replace_once(
    workflow,
    '          assert set(report["selectedElasticScales"]) == {\n'
    '              record["materialId"] for record in report["records"]\n'
    '          }\n'
    '          assert all(\n'
    '              record["runtime"]["elasticScale"]\n'
    '              == report["selectedElasticScales"][record["materialId"]]\n'
    '              for record in report["records"]\n'
    '          )\n',
    '          assert set(report["selectedDiagnosticElasticScales"]) == {\n'
    '              record["materialId"] for record in report["records"]\n'
    '          }\n'
    '          assert report["elasticScaleStatus"] == (\n'
    '              "diagnostic-until-temporal-convergence-passes"\n'
    '          )\n'
    '          assert report["temporalConvergence"]["checkpointFrames"] == [\n'
    '              100, 150, 200, 250\n'
    '          ]\n'
    '          assert len(report["temporalConvergence"]["records"]) == 6\n'
    '          assert all(\n'
    '              record["runtime"]["elasticScale"]\n'
    '              == report["selectedDiagnosticElasticScales"][record["materialId"]]\n'
    '              for record in report["records"]\n'
    '          )\n',
    "workflow diagnostic assertions",
)
WORKFLOW.write_text(workflow, encoding="utf-8")
