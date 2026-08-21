#!/usr/bin/env python3
"""Stable product entrypoint for the Siroino heather hooded bodysuit."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import siroino_heather_hooded_bodysuit_build as build
import siroino_heather_hooded_v11_support as support

support.install()

import siroino_heather_hooded_pattern as pattern
import siroino_heather_manifold_yoke_v29 as manifold_yoke


# The v27-v29 geometry helpers need the stable base-pattern aliases formerly
# exposed by a compatibility layer. Install them directly without another
# production import level.
pattern.v9 = pattern


def _move_modifier_before_armature(
    obj: bpy.types.Object,
    modifier: bpy.types.Modifier,
) -> None:
    while obj.modifiers.find(modifier.name) > 0:
        bpy.ops.object.modifier_move_up(modifier=modifier.name)


pattern._move_modifier_before_armature = _move_modifier_before_armature
manifold_yoke.install(pattern)

DESIGN_REVISION = manifold_yoke.DESIGN_REVISION
RESEARCH_TRIAL = str(manifold_yoke.RESEARCH_OUTPUT).replace("\\", "/")
ACTUAL_SEPARATE_GEOMETRY = [
    "Heather_Body_Shell",
    "Heather_Long_Sleeve_L",
    "Heather_Long_Sleeve_R",
    "Heather_Rib_Cuff_L",
    "Heather_Rib_Cuff_R",
    "Heather_Hood_Folded_Roll",
    "Heather_Henley_Placket",
    "Heather_Henley_Button_01",
    "Heather_Henley_Button_02",
    "Heather_Henley_Button_03",
    "Heather_Hood_Drawcord_L",
    "Heather_Hood_Drawcord_R",
]

REJECTED_REVISIONS = [
    {
        "revision": "v26-angular-polar-yoke-hood",
        "reason": (
            "direct review found upper-back holes, open sleeve roots, a dome hood, "
            "pointed crotch panels and 14,192 overlaps across six required poses"
        ),
    },
    {
        "revision": "v27-closed-saddle-sleevecap-folded-hood",
        "reason": (
            "direct review found a rectangular neckline, bulky folded sleeve roots, "
            "a broad shoulder flap instead of a hood, pointed lower panels and "
            "15,753 overlaps across six required poses"
        ),
    },
    {
        "revision": "v28-flat-saddle-contoured-cap-hood-roll",
        "reason": (
            "pose framing and intersections improved, but direct review still found "
            "a low rectangular neckline, rounded shoulder bulbs, jagged underarm "
            "seams, a padded-tube hood, pointed lower wedges and 12,494 overlaps"
        ),
    },
]


def normalize_four_influences(
    objects: list[bpy.types.Object],
    maximum: int = 4,
) -> dict[str, int]:
    """Normalize every vertex, pruning to the VRChat four-influence limit."""
    changed: dict[str, int] = {}
    for obj in objects:
        if obj.type != "MESH":
            continue
        fallback = obj.vertex_groups.get("Hips")
        if fallback is None:
            fallback = obj.vertex_groups.new(name="Hips")
        affected = 0
        for vertex in obj.data.vertices:
            assignments = [
                (obj.vertex_groups[item.group].name, float(item.weight))
                for item in list(vertex.groups)
                if item.weight > 1e-10
            ]
            ranked = sorted(
                assignments,
                key=lambda item: item[1],
                reverse=True,
            )[:maximum]
            if not ranked:
                ranked = [(fallback.name, 1.0)]
            total = sum(weight for _, weight in ranked)
            if total <= 1e-12:
                ranked = [(fallback.name, 1.0)]
                total = 1.0
            requires_change = (
                len(assignments) != len(ranked)
                or abs(sum(weight for _, weight in assignments) - 1.0) > 1e-6
            )
            for group_name, _ in assignments:
                obj.vertex_groups[group_name].remove([vertex.index])
            for group_name, weight in ranked:
                obj.vertex_groups[group_name].add(
                    [vertex.index],
                    weight / total,
                    "REPLACE",
                )
            if requires_change:
                affected += 1
        changed[obj.name] = affected
    return changed


def preserve_authored_weights(
    garments: list[bpy.types.Object],
    _body: bpy.types.Object,
) -> dict[str, object]:
    """Preserve garment-native weights transferred during construction."""
    return {
        "objects": [obj.name for obj in garments if obj.type == "MESH"],
        "weightSource": (
            "the validated polar profile remains the shape reference; v29 uses a "
            "four-iteration smoothed clearance displacement capped at 12 mm, a "
            "five-ring tapered yoke, a seventeen-column shallow saddle, fitted "
            "sleeves and a compact rear-neck hood; four normalized influences are "
            "enforced after construction"
        ),
        "bodyTopologyCopied": False,
        "boundedClearanceProjection": True,
        "clearanceDisplacementSmoothing": 4,
        "pelvicSaddleColumns": 17,
        "taperedYokeRings": 5,
        "visualMechanismRevision": DESIGN_REVISION,
        "rebound": False,
    }


def wrap_pattern_writer(original):
    def wrapped(*args, **kwargs):
        pattern_path, research_path = original(*args, **kwargs)
        contract = json.loads(pattern_path.read_text(encoding="utf-8"))
        contract["separateGeometry"] = ACTUAL_SEPARATE_GEOMETRY
        contract["designRevision"] = DESIGN_REVISION
        contract["representation"] = {
            "canonical": (
                "polar torso with tapered yoke, shallow saddle, fitted sleeves and compact hood"
            ),
            "bodyTopologyCopied": False,
            "boundedClearanceProjection": True,
            "clearanceDisplacementSmoothing": 4,
            "components": [
                "smoothed height-by-angle torso field",
                "five-ring tapered shoulder yoke and fitted neck",
                "seventeen-column shallow pelvic saddle",
                "small-root fitted sleeve tubes",
                "left and right fitted cuffs",
                "compact six-row folded hood shell at rear neck",
            ],
            "bodyRole": (
                "polar statistics, smoothed bounded clearance and skin-weight reference"
            ),
        }
        contract["researchTrialEvidence"] = RESEARCH_TRIAL
        pattern_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return pattern_path, research_path

    return wrapped


def enforce_manifest_contract(original):
    """Keep generated reports truthful about the lifecycle boundary."""

    def wrapped(*args, **kwargs):
        result = original(*args, **kwargs)
        job = args[0]
        root = Path(__file__).resolve().parents[1]
        trial_path = root / RESEARCH_TRIAL
        trial = (
            json.loads(trial_path.read_text(encoding="utf-8"))
            if trial_path.is_file()
            else {"result": "FAIL", "status": "MISSING"}
        )

        manifest_path = root / job["productManifestPath"]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["schemaVersion"] = 1
        manifest["designRevision"] = DESIGN_REVISION
        manifest["status"] = "WORKING"
        manifest["technicalGates"]["researchTrial"] = trial.get("result", "FAIL")
        manifest["technicalGates"]["visualAppearanceReview"] = "PENDING"
        manifest["technicalGates"]["fitPenetration"] = "NON_BLOCKING_PENDING"
        for key in (
            "unityImport",
            "unitySaveReload",
            "prefabReload",
            "modularAvatar",
            "ndmf",
            "vrchatBuildTest",
            "vrchatRuntime",
            "humanRuntimeReview",
        ):
            manifest["technicalGates"][key] = "OUT_OF_SCOPE"
        manifest["outputs"]["researchTrial"] = RESEARCH_TRIAL
        manifest["research"] = {
            "result": trial.get("result", "FAIL"),
            "evidence": RESEARCH_TRIAL,
            "representation": (
                "polar torso with tapered yoke, shallow saddle, fitted sleeves and compact hood"
            ),
            "authorsImplementationExecuted": False,
            "authorsCodeCopied": False,
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        report_path = (
            root
            / ".image2outfit"
            / "products"
            / job["id"]
            / "reports"
            / "product-build-report.json"
        )
        if report_path.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["designRevision"] = DESIGN_REVISION
            report["researchTrial"] = manifest["research"]
            rejected = report.setdefault("rejectedHistory", [])
            existing = {item.get("revision") for item in rejected}
            rejected.extend(
                item for item in REJECTED_REVISIONS if item["revision"] not in existing
            )
            report["notes"] = [
                "The validated height-by-angle torso field is retained.",
                "Clearance displacements are capped at 12 mm and smoothed through "
                "four adjacency iterations before application.",
                "A five-ring yoke closes continuously from the torso shoulder line "
                "to a fitted 57 by 45 mm neck ellipse.",
                "The lower front/back difference is reduced to 55 mm and a "
                "seventeen-column saddle uses only 4 mm central sag.",
                "Sleeve roots begin at 27 mm radius and never exceed 33 mm.",
                "The hood is a compact six-row rear-neck fold rather than a tube or "
                "a shoulder-wide sheet.",
                "Full-subject pose framing remains active.",
                "Visual review remains blocking; runtime systems are OUT_OF_SCOPE.",
            ]
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return result

    return wrapped


def update_panel_object_contract() -> None:
    replacements = {
        "Heather_Front_Upper_Panel": "Heather_Body_Shell",
        "Heather_Back_Upper_Panel": "Heather_Body_Shell",
        "Heather_Highcut_Front_Panel": "Heather_Body_Shell",
        "Heather_Highcut_Back_Panel": "Heather_Body_Shell",
        "Heather_Long_Sleeve_L": "Heather_Long_Sleeve_L",
        "Heather_Long_Sleeve_R": "Heather_Long_Sleeve_R",
        "Heather_Rib_Cuff_L": "Heather_Rib_Cuff_L",
        "Heather_Rib_Cuff_R": "Heather_Rib_Cuff_R",
        "Heather_Hood_Back_Drape_L": "Heather_Hood_Folded_Roll",
        "Heather_Hood_Back_Drape_R": "Heather_Hood_Folded_Roll",
        "Heather_Hood_Outer_L": "Heather_Hood_Folded_Roll",
        "Heather_Hood_Outer_R": "Heather_Hood_Folded_Roll",
        "Heather_Hood_Cowl": "Heather_Hood_Folded_Roll",
    }
    for panel in build.evidence.PANELS:
        panel["object"] = replacements.get(panel["object"], panel["object"])


def main() -> int:
    build.geometry = pattern
    build.DESIGN_REVISION = DESIGN_REVISION
    build.limit_bone_influences = normalize_four_influences
    build.rebind_dynamic_parts = preserve_authored_weights
    update_panel_object_contract()
    build.evidence.write_pattern_and_research = wrap_pattern_writer(
        build.evidence.write_pattern_and_research
    )
    build.write_report_and_manifest = enforce_manifest_contract(
        build.write_report_and_manifest
    )
    return build.main()


if __name__ == "__main__":
    raise SystemExit(main())
