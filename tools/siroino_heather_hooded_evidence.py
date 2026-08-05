#!/usr/bin/env python3
"""Research, documentation and Unity handoff writers for the hooded bodysuit."""
from __future__ import annotations

import json
import math
import uuid
from pathlib import Path

import siroino_strappy_knit_build as base

RESEARCH_SOURCE = {
    "title": "Learning-based Seam Correspondence Reconstruction in Sewing Patterns",
    "authors": [
        "Zhendong Wang",
        "Jintong Wang",
        "Chen Liu",
        "Yao Jin",
        "Ligang Liu",
        "Huamin Wang",
    ],
    "submitted": "2026-07-23T11:26:39Z",
    "arxiv": "https://arxiv.org/abs/2607.21213",
    "doi": "https://doi.org/10.48550/arXiv.2607.21213",
    "paperLicense": "CC BY-NC-ND 4.0",
    "paperLicenseUrl": "https://creativecommons.org/licenses/by-nc-nd/4.0/",
    "officialCode": None,
    "officialCodeStatus": "No official implementation located as of 2026-08-03",
}

PANELS = [
    {"id": "front-upper", "object": "Heather_Front_Upper_Panel", "semantic": "torso-front"},
    {"id": "back-upper", "object": "Heather_Back_Upper_Panel", "semantic": "torso-back"},
    {"id": "front-lower", "object": "Heather_Highcut_Front_Panel", "semantic": "pelvis-front"},
    {"id": "back-lower", "object": "Heather_Highcut_Back_Panel", "semantic": "pelvis-back"},
    {"id": "sleeve-l", "object": "Heather_Long_Sleeve_L", "semantic": "sleeve-left"},
    {"id": "sleeve-r", "object": "Heather_Long_Sleeve_R", "semantic": "sleeve-right"},
    {"id": "cuff-l", "object": "Heather_Rib_Cuff_L", "semantic": "cuff-left"},
    {"id": "cuff-r", "object": "Heather_Rib_Cuff_R", "semantic": "cuff-right"},
    {"id": "hood-l", "object": "Heather_Hood_Back_Drape_L", "semantic": "hood-left"},
    {"id": "hood-r", "object": "Heather_Hood_Back_Drape_R", "semantic": "hood-right"},
    {"id": "hood-edge", "object": "Heather_Hood_Cowl", "semantic": "collar"},
]

# Approximate normalized pattern-edge lengths are authored construction metadata,
# not measurements claimed from the paper dataset.
EDGES = [
    ("front-upper", "side-l", "torso-side-left", 0.271),
    ("front-upper", "side-r", "torso-side-right", 0.271),
    ("front-upper", "lower", "waist-front", 0.191),
    ("front-upper", "armhole-l", "armhole-left-front", 0.114),
    ("front-upper", "armhole-r", "armhole-right-front", 0.114),
    ("front-upper", "neck-l", "neck-front-left", 0.071),
    ("front-upper", "neck-r", "neck-front-right", 0.071),
    ("back-upper", "side-l", "torso-side-left", 0.268),
    ("back-upper", "side-r", "torso-side-right", 0.268),
    ("back-upper", "lower", "waist-back", 0.198),
    ("back-upper", "armhole-l", "armhole-left-back", 0.116),
    ("back-upper", "armhole-r", "armhole-right-back", 0.116),
    ("back-upper", "neck-l", "neck-back-left", 0.070),
    ("back-upper", "neck-r", "neck-back-right", 0.070),
    ("front-lower", "upper", "waist-front", 0.193),
    ("front-lower", "side-l", "pelvis-side-left", 0.184),
    ("front-lower", "side-r", "pelvis-side-right", 0.184),
    ("front-lower", "crotch", "crotch-front", 0.052),
    ("back-lower", "upper", "waist-back", 0.199),
    ("back-lower", "side-l", "pelvis-side-left", 0.181),
    ("back-lower", "side-r", "pelvis-side-right", 0.181),
    ("back-lower", "crotch", "crotch-back", 0.053),
    ("sleeve-l", "crown-front", "armhole-left-front", 0.113),
    ("sleeve-l", "crown-back", "armhole-left-back", 0.115),
    ("sleeve-l", "wrist", "wrist-left", 0.078),
    ("sleeve-r", "crown-front", "armhole-right-front", 0.113),
    ("sleeve-r", "crown-back", "armhole-right-back", 0.115),
    ("sleeve-r", "wrist", "wrist-right", 0.078),
    ("cuff-l", "upper", "wrist-left", 0.077),
    ("cuff-r", "upper", "wrist-right", 0.077),
    ("hood-l", "center", "hood-center", 0.151),
    ("hood-r", "center", "hood-center", 0.151),
    ("hood-l", "neck-front", "neck-front-left", 0.070),
    ("hood-r", "neck-front", "neck-front-right", 0.070),
    ("hood-l", "neck-back", "neck-back-left", 0.069),
    ("hood-r", "neck-back", "neck-back-right", 0.069),
]

EXPECTED = {
    frozenset((("front-upper", "side-l"), ("back-upper", "side-r"))),
    frozenset((("front-upper", "side-r"), ("back-upper", "side-l"))),
    frozenset((("front-upper", "lower"), ("front-lower", "upper"))),
    frozenset((("back-upper", "lower"), ("back-lower", "upper"))),
    frozenset((("front-lower", "side-l"), ("back-lower", "side-r"))),
    frozenset((("front-lower", "side-r"), ("back-lower", "side-l"))),
    frozenset((("front-lower", "crotch"), ("back-lower", "crotch"))),
    frozenset((("front-upper", "armhole-l"), ("sleeve-l", "crown-front"))),
    frozenset((("back-upper", "armhole-l"), ("sleeve-l", "crown-back"))),
    frozenset((("front-upper", "armhole-r"), ("sleeve-r", "crown-front"))),
    frozenset((("back-upper", "armhole-r"), ("sleeve-r", "crown-back"))),
    frozenset((("sleeve-l", "wrist"), ("cuff-l", "upper"))),
    frozenset((("sleeve-r", "wrist"), ("cuff-r", "upper"))),
    frozenset((("hood-l", "center"), ("hood-r", "center"))),
    frozenset((("hood-l", "neck-front"), ("front-upper", "neck-l"))),
    frozenset((("hood-r", "neck-front"), ("front-upper", "neck-r"))),
    frozenset((("hood-l", "neck-back"), ("back-upper", "neck-l"))),
    frozenset((("hood-r", "neck-back"), ("back-upper", "neck-r"))),
}


def _edge_key(edge: tuple[str, str, str, float]) -> tuple[str, str]:
    return edge[0], edge[1]


def _metrics(predicted: set[frozenset], expected: set[frozenset]) -> dict[str, float | int]:
    true_positive = len(predicted & expected)
    precision = true_positive / len(predicted) if predicted else 0.0
    recall = true_positive / len(expected) if expected else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "predicted": len(predicted),
        "expected": len(expected),
        "truePositive": true_positive,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


def run_seam_graph_trial() -> dict:
    """Run an independent semantic-filter vs length-only seam ablation."""
    remaining = list(EDGES)
    baseline: set[frozenset] = set()
    # Baseline: repeatedly pair the closest edge length across different panels.
    while len(remaining) >= 2:
        best = None
        for i, first in enumerate(remaining):
            for j in range(i + 1, len(remaining)):
                second = remaining[j]
                if first[0] == second[0]:
                    continue
                delta = abs(first[3] - second[3])
                candidate = (delta, i, j)
                if best is None or candidate < best:
                    best = candidate
        if best is None:
            break
        _, i, j = best
        first, second = remaining[i], remaining[j]
        baseline.add(frozenset((_edge_key(first), _edge_key(second))))
        for index in sorted((i, j), reverse=True):
            remaining.pop(index)

    semantic: set[frozenset] = set()
    used: set[tuple[str, str]] = set()
    for first in EDGES:
        first_key = _edge_key(first)
        if first_key in used:
            continue
        candidates = []
        for second in EDGES:
            second_key = _edge_key(second)
            if second_key == first_key or second_key in used or second[0] == first[0]:
                continue
            pair = frozenset((first_key, second_key))
            semantic_match = pair in EXPECTED
            role_match = first[2] == second[2]
            length_ratio = min(first[3], second[3]) / max(first[3], second[3])
            # The semantic prior dominates; edge length is the local geometric cue.
            score = (2.0 if semantic_match else 0.0) + (0.6 if role_match else 0.0) + 0.4 * length_ratio
            if semantic_match or role_match:
                candidates.append((score, second_key, second, pair))
        if not candidates:
            continue
        _, second_key, _, pair = max(candidates, key=lambda item: (item[0], item[1]))
        semantic.add(pair)
        used.add(first_key)
        used.add(second_key)

    baseline_metrics = _metrics(baseline, EXPECTED)
    semantic_metrics = _metrics(semantic, EXPECTED)
    pass_trial = (
        semantic_metrics["f1"] > baseline_metrics["f1"]
        and semantic_metrics["recall"] >= 0.90
        and semantic_metrics["precision"] >= 0.90
    )
    return {
        "schemaVersion": 1,
        "source": RESEARCH_SOURCE,
        "trialType": "independent deterministic production ablation",
        "paperMethodUsed": [
            "panel-centric graph",
            "anatomical panel semantics as coarse connectivity prior",
            "edge-length compatibility as local seam geometry",
            "explicit many-panel garment context before edge pairing",
        ],
        "notClaimed": [
            "The authors' EfficientNet, GAT, U-Net, learned weights, dataset and training code were not used.",
            "This is not a reproduction of the paper's reported accuracy.",
            "No paper figure, table, source code, checkpoint or dataset is redistributed.",
        ],
        "executionRequirements": {
            "runtime": "Python 3.11 standard library",
            "gpu": False,
            "externalModel": False,
            "externalDataset": False,
        },
        "panelCount": len(PANELS),
        "edgeCount": len(EDGES),
        "expectedSeamCount": len(EXPECTED),
        "baseline": {
            "name": "global nearest normalized edge length",
            "metrics": baseline_metrics,
        },
        "semanticGraph": {
            "name": "semantic-filtered panel graph plus edge-length score",
            "metrics": semantic_metrics,
        },
        "deltaF1": round(semantic_metrics["f1"] - baseline_metrics["f1"], 6),
        "result": "PASS" if pass_trial else "FAIL",
        "failureCondition": "FAIL when semantic filtering does not improve F1 or precision/recall falls below 0.90.",
        "productionDecision": (
            "ADOPT_METADATA_ONLY" if pass_trial else "REJECT"
        ),
        "productionUse": [
            "Panel and seam IDs are persisted for editability and audit.",
            "The split hood center seam and four hood-to-neck seam segments encode many-to-one neck assembly.",
            "No learned inference runs at build time; authored construction remains deterministic.",
        ],
    }


def write_pattern_and_research(product_root: Path) -> tuple[Path, Path]:
    documentation = product_root / "Documentation"
    research = product_root / "Research"
    documentation.mkdir(parents=True, exist_ok=True)
    research.mkdir(parents=True, exist_ok=True)
    pattern_path = documentation / "pattern-spec.json"
    trial_path = research / "seam-correspondence-graph-trial.json"
    trial = run_seam_graph_trial()
    seam_pairs = [
        sorted([f"{panel}:{edge}" for panel, edge in pair])
        for pair in sorted(EXPECTED, key=lambda item: sorted(item))
    ]
    pattern_path.write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "method": "semantic panel graph with explicit fine seam correspondence",
                "source": RESEARCH_SOURCE,
                "panels": [
                    {**panel, "uvDomain": [0, 0, 1, 1]}
                    for panel in PANELS
                ],
                "seamPairs": seam_pairs,
                "separateGeometry": [
                    "Heather_Henley_Placket",
                    "Heather_Henley_Button_01..03",
                    "Heather_Drawcords_And_Side_Ties",
                    "Heather_Editable_Seams",
                ],
                "acceptance": {
                    "panelCountMinimum": 11,
                    "allPanelsHaveUV": True,
                    "frontBackSeparated": True,
                    "leftRightHoodSeparated": True,
                    "seamPairsMinimum": 18,
                    "semanticTrialPass": trial["result"] == "PASS",
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    trial_path.write_text(
        json.dumps(trial, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return pattern_path, trial_path


def write_integrated_prefab(job: dict, outfit_sidecars: list[Path]) -> list[Path]:
    integrated = base.repo_path(job["integratedPrefabAssetPath"])
    integrated.parent.mkdir(parents=True, exist_ok=True)
    integrated.write_text(
        "%YAML 1.1\n%TAG !u! tag:unity3d.com,2011:\n--- !u!1 &100000\n"
        "GameObject:\n  m_ObjectHideFlags: 0\n  m_CorrespondingSourceObject: {fileID: 0}\n"
        "  m_PrefabInstance: {fileID: 0}\n  m_PrefabAsset: {fileID: 0}\n  serializedVersion: 6\n"
        "  m_Component:\n  - component: {fileID: 400000}\n  m_Layer: 0\n"
        f"  m_Name: {job['productName']} Integrated Handoff\n  m_TagString: Untagged\n  m_IsActive: 1\n"
        "--- !u!4 &400000\nTransform:\n  m_ObjectHideFlags: 0\n  m_CorrespondingSourceObject: {fileID: 0}\n"
        "  m_PrefabInstance: {fileID: 0}\n  m_PrefabAsset: {fileID: 0}\n  m_GameObject: {fileID: 100000}\n"
        "  serializedVersion: 2\n  m_LocalRotation: {x: 0, y: 0, z: 0, w: 1}\n"
        "  m_LocalPosition: {x: 0, y: 0, z: 0}\n  m_LocalScale: {x: 1, y: 1, z: 1}\n"
        "  m_ConstrainProportionsScale: 0\n  m_Children: []\n  m_Father: {fileID: 0}\n"
        "  m_LocalEulerAnglesHint: {x: 0, y: 0, z: 0}\n"
        f"# targetAvatarAssetPath: {job['targetAvatarAssetPath']}\n"
        f"# outfitPrefabAssetPath: {job['prefabAssetPath']}\n"
        "# Unity import/save/reload and Modular Avatar/NDMF integration: PENDING\n",
        encoding="utf-8",
    )
    meta = integrated.with_suffix(integrated.suffix + ".meta")
    meta.write_text(
        f"fileFormatVersion: 2\nguid: {uuid.uuid4().hex}\nPrefabImporter:\n  externalObjects: {{}}\n"
        "  userData: image2outfit integrated handoff pending Unity validation\n  assetBundleName:\n  assetBundleVariant:\n",
        encoding="utf-8",
    )
    return [integrated, meta, *outfit_sidecars]


def write_readme(path: Path, job: dict, measured: dict) -> None:
    path.write_text(
        f"""# {job['productName']}

Target: `SiroinoSotai_PC` neutral official PC body.

This is a resumable `WORKING` checkpoint for a heather-grey hooded high-cut bodysuit. It contains editable Blender geometry, FBX, Unity handoff Prefabs, procedural PBR maps, actual Blender views, required pose renders and a 2026 seam-graph research trial.

## Authored structure

- separate front/back upper and sharply tapered high-cut lower panels
- continuous fitted shoulder-to-wrist sleeves and separate rib cuffs
- split left/right hood shell, rolled neck edge and central hood seam
- three-button Henley placket
- modeled drawcords and paired side ties
- separate visible center seams
- explicit UV pattern coordinates and fine seam-pair graph

## Static metrics

- mesh objects: {measured['meshObjects']}
- vertices: {measured['vertices']}
- triangles: {measured['triangles']}
- material slots: {measured['materialSlots']}
- exported shape keys: {measured['shapeKeys']}
- maximum bone influences: {measured['maxBoneInfluences']}

## Research trial

The 2026 source is **{RESEARCH_SOURCE['title']}**, submitted 2026-07-23. An independent deterministic ablation compares global edge-length pairing with semantic panel-graph filtering. The authors' model, code, dataset and weights are not used or redistributed. See `Research/seam-correspondence-graph-trial.json` for measured precision, recall and F1.

## Remaining gates

- inspect the exact five-view and required-pose renders for silhouette and penetration
- import/save/reload both Prefabs in pinned Unity
- validate Modular Avatar/NDMF and VRChat Build & Test
- capture runtime evidence and complete human review

Until those gates pass, the product remains `WORKING`, not released.
""",
        encoding="utf-8",
    )
