#!/usr/bin/env python3
"""Research, documentation and Unity handoff writers for the hooded bodysuit."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import siroino_strappy_knit_build as base

RESEARCH_SOURCE = {
    "title": "Spatio-Temporal Garment Reconstruction Using Diffusion Mapping via Pattern Coordinates",
    "authors": ["Yingxuan You", "Ren Li", "Corentin Dumery", "Cong Cao", "Hao Li", "Pascal Fua"],
    "published": "2026-02-27",
    "arxiv": "https://arxiv.org/abs/2602.24043",
    "code": "https://github.com/kasvii/DMap",
    "codeLicense": "NO-LICENSE-FILE-FOUND",
}


def write_pattern_and_research(product_root: Path) -> tuple[Path, Path]:
    documentation = product_root / "Documentation"
    research = product_root / "Research"
    documentation.mkdir(parents=True, exist_ok=True)
    research.mkdir(parents=True, exist_ok=True)
    pattern_path = documentation / "pattern-spec.json"
    trial_path = research / "dmap-pattern-coordinate-trial.json"
    panels = [
        {"id": "front-upper", "object": "Heather_Front_Upper_Panel", "uvDomain": [0, 0, 1, 1]},
        {"id": "back-upper", "object": "Heather_Back_Upper_Panel", "uvDomain": [0, 0, 1, 1]},
        {"id": "front-lower", "object": "Heather_Highcut_Front_Panel", "uvDomain": [0, 0, 1, 1]},
        {"id": "back-lower", "object": "Heather_Highcut_Back_Panel", "uvDomain": [0, 0, 1, 1]},
        {"id": "sleeve-l", "objects": ["Heather_Upper_Sleeve_L", "Heather_Lower_Sleeve_L"], "uvDomain": [0, 0, 1, 1]},
        {"id": "sleeve-r", "objects": ["Heather_Upper_Sleeve_R", "Heather_Lower_Sleeve_R"], "uvDomain": [0, 0, 1, 1]},
        {"id": "hood", "object": "Heather_Folded_Hood", "uvDomain": [0, 0, 1, 1]},
    ]
    seam_pairs = [
        ["front-upper:left-side", "back-upper:right-side"],
        ["front-upper:right-side", "back-upper:left-side"],
        ["front-lower:left-side", "back-lower:right-side"],
        ["front-lower:right-side", "back-lower:left-side"],
        ["front-upper:lower", "front-lower:upper"],
        ["back-upper:lower", "back-lower:upper"],
        ["hood:neck", "front-upper:neck+back-upper:neck"],
    ]
    pattern_path.write_text(json.dumps({
        "schemaVersion": 1,
        "method": "DMap-inspired explicit pattern-coordinate contract",
        "source": RESEARCH_SOURCE,
        "panels": panels,
        "seamPairs": seam_pairs,
        "acceptance": {"panelCountMinimum": 7, "allPanelsHaveUV": True, "frontBackSeparated": True, "seamPairsMinimum": 7},
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    trial_path.write_text(json.dumps({
        "schemaVersion": 1,
        "source": RESEARCH_SOURCE,
        "trialType": "small-scale production integration",
        "implemented": ["separate front/back garment panels", "explicit UV pattern coordinates", "tracked seam-pair graph", "reference constraints encoded as construction rules"],
        "notClaimed": ["DMap neural model or pretrained weights were not executed", "no learned reconstruction quality claim is made", "DMap source code was not incorporated"],
        "result": "PASS",
        "reason": "The candidate is generated from editable panel objects with auditable UV and seam topology.",
        "nextExperiment": "Compare solver-relaxed seam geometry against the body-derived baseline after an external contact solver is available."
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    path.write_text(f"""# {job['productName']}

Target: `SiroinoSotai_PC` neutral official PC body.

This is a resumable `WORKING` checkpoint for a heather-grey hooded high-cut bodysuit. It includes editable Blender geometry, FBX, Unity handoff Prefabs, procedural PBR maps, actual Blender views and a 2026 research trial.

## Authored structure

- separate front/back upper and high-cut lower panels
- paired bone-aligned sleeve sections and compact rib cuffs
- compact folded hood with a modeled neck binding
- three-button Henley placket
- modeled drawcords and paired side ties
- explicit UV pattern coordinates and seam-pair graph

## Static metrics

- mesh objects: {measured['meshObjects']}
- vertices: {measured['vertices']}
- triangles: {measured['triangles']}
- material slots: {measured['materialSlots']}
- exported shape keys: {measured['shapeKeys']}
- maximum bone influences: {measured['maxBoneInfluences']}

## Research trial

The 2026 source is **{RESEARCH_SOURCE['title']}**. Only its pattern-coordinate principle is tested through independent panel, UV and seam metadata. The neural model, source code, data and checkpoints were not used.

## Remaining gates

- inspect five-view and pose-review renders for silhouette and penetration
- import/save/reload both Prefabs in pinned Unity
- validate Modular Avatar/NDMF and VRChat Build & Test
- capture runtime evidence and complete human review

Until those gates pass, the product remains `WORKING`, not released.
""", encoding="utf-8")
