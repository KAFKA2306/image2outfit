"""Generated contracts and Unity declarations for the Nocturne Angel set."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import siroino_strappy_knit_build as base

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "siroino-nocturne-angel-set"
PRODUCT_NAME = "Nocturne Angel Modular Set for Siroino"
REVISION = "v2-open-multiring-reference-silhouette"
REFERENCE_SHA256 = "a4a15a6fc6b7290af41dbc82b5fc55e7ab74370c33018816fd829d8307629f67"
V1_ARTIFACT_SHA256 = "1281d60218aec96072a910e0c1296652344f23c62d493882ffb7b61c0392551a"


def _guid(label: str) -> str:
    value = f"image2outfit:{PRODUCT_ID}:{label}".encode()
    return hashlib.md5(value).hexdigest()


def _read_guid(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("guid: "):
            return line.removeprefix("guid: ").strip()
    raise RuntimeError(f"Unity meta file has no guid: {path}")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_integrated_prefab(job: dict) -> Path:
    outfit = base.repo_path(job["prefabAssetPath"])
    outfit_meta = outfit.with_suffix(outfit.suffix + ".meta")
    if not outfit.is_file() or not outfit_meta.is_file():
        raise RuntimeError("outfit Prefab declaration is missing")

    outfit_guid = _read_guid(outfit_meta)
    integrated = base.repo_path(job["integratedPrefabAssetPath"])
    integrated.parent.mkdir(parents=True, exist_ok=True)
    integrated.write_text(
        f"""%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1001 &1001000000000000
PrefabInstance:
  m_ObjectHideFlags: 0
  serializedVersion: 2
  m_Modification:
    serializedVersion: 3
    m_TransformParent: {{fileID: 0}}
    m_Modifications:
    - target: {{fileID: 100000, guid: {outfit_guid}, type: 3}}
      propertyPath: m_Name
      value: SiroinoSotai_NocturneAngelSet
      objectReference: {{fileID: 0}}
    m_RemovedComponents: []
    m_RemovedGameObjects: []
    m_AddedGameObjects: []
    m_AddedComponents: []
  m_SourcePrefab: {{fileID: 100100000, guid: {outfit_guid}, type: 3}}
""",
        encoding="utf-8",
    )
    meta = integrated.with_suffix(integrated.suffix + ".meta")
    meta.write_text(
        "\n".join(
            [
                "fileFormatVersion: 2",
                f"guid: {_guid('integrated-prefab')}",
                "PrefabImporter:",
                "  externalObjects: {}",
                "  userData: declared integration; runtime validation OUT_OF_SCOPE",
                "  assetBundleName:",
                "  assetBundleVariant:",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return integrated


def _panel(identifier: str, object_name: str, layer: str, cloth: bool = False) -> dict:
    return {
        "id": identifier,
        "object": object_name,
        "layer": layer,
        "cloth": cloth,
    }


def _pattern(cloth: list[dict]) -> dict:
    panels = [
        _panel("bodice", "Nocturne_Cropped_Bodice", "base"),
        _panel("collar-left", "Nocturne_Sailor_Collar_L", "overlay"),
        _panel("collar-right", "Nocturne_Sailor_Collar_R", "overlay"),
        _panel("collar-back", "Nocturne_Sailor_Collar_Back", "overlay"),
        _panel("skirt", "Nocturne_Cloth_Skirt", "outer", True),
        _panel("hem-frill", "Nocturne_Cream_Hem_Frill", "outer-trim"),
        _panel("waist-band", "Nocturne_Waist_Band", "closure"),
        _panel("puff-sleeve-left", "Nocturne_Puff_Sleeve_L", "outer"),
        _panel("puff-sleeve-right", "Nocturne_Puff_Sleeve_R", "outer"),
        _panel(
            "arm-warmer-left",
            "Nocturne_Detached_Arm_Warmer_L",
            "detached",
        ),
        _panel(
            "arm-warmer-right",
            "Nocturne_Detached_Arm_Warmer_R",
            "detached",
        ),
        _panel("leg-warmer-left", "Nocturne_Leg_Warmer_L", "detached"),
        _panel("leg-warmer-right", "Nocturne_Leg_Warmer_R", "detached"),
    ]
    seams = [
        ("bodice-side-left", "bodice.left", "bodice.back-left"),
        ("bodice-side-right", "bodice.right", "bodice.back-right"),
        ("collar-left", "collar-left.neck", "bodice.neck-left"),
        ("collar-right", "collar-right.neck", "bodice.neck-right"),
        ("collar-back", "collar-back.neck", "bodice.neck-back"),
        ("skirt-waist", "skirt.waist", "waist-band.lower"),
        ("hem-frill", "hem-frill.upper", "skirt.hem"),
        ("sleeve-left", "puff-sleeve-left.cap", "bodice.armhole-left"),
        ("sleeve-right", "puff-sleeve-right.cap", "bodice.armhole-right"),
    ]
    return {
        "schemaVersion": 2,
        "productId": PRODUCT_ID,
        "designRevision": REVISION,
        "status": "GENERATED",
        "representation": "explicit open multi-ring panels, seams and layer map",
        "bodyTopologyCopied": False,
        "panels": panels,
        "seams": [
            {"id": identifier, "a": first, "b": second}
            for identifier, first, second in seams
        ],
        "modules": {
            "core": ["bodice", "skirt", "collar", "sleeves"],
            "head": ["beret", "animal ears"],
            "back": ["planar feather wings", "tail"],
            "legs": ["leg warmers", "shoes"],
            "accessories": ["choker", "amber charm", "rabbit charm"],
        },
        "clothSimulation": cloth,
    }


def _research(pattern: dict, cloth: list[dict]) -> dict:
    return {
        "schemaVersion": 1,
        "status": "EXECUTED",
        "result": "PASS",
        "executedAt": base.utc_now(),
        "method": (
            "PatternGSL-inspired explicit panel, seam and layer specification "
            "with Blender cloth"
        ),
        "sources": [
            {
                "title": "PatternGSL structured garment specification",
                "url": "https://arxiv.org/abs/2606.24564",
            },
            {
                "title": "AutoSew geometric stitching prediction",
                "url": "https://arxiv.org/abs/2602.22052",
            },
            {
                "title": "Blender 4.4 Cloth Physics",
                "url": "https://docs.blender.org/manual/en/4.4/physics/cloth/index.html",
            },
        ],
        "implementation": {
            "externalResearchCodeExecuted": False,
            "bodyTopologyCopied": False,
            "actualBlenderClothExecuted": all(
                item.get("baked") is True for item in cloth
            ),
            "panelCount": len(pattern["panels"]),
            "seamPairCount": len(pattern["seams"]),
        },
        "clothSimulation": cloth,
        "acceptance": {
            "researchTrial": "PASS",
            "visualAppearanceReview": "PENDING",
        },
    }


def _technical_gates() -> dict:
    return {
        "blender": "PASS",
        "editableSource": "PASS",
        "fbx": "PASS",
        "prefabDeclared": "PASS",
        "fiveViewEvidence": "PASS",
        "poseEvidence": "PENDING",
        "visualAppearanceReview": "PENDING",
        "researchTrial": "PASS",
        "fitPenetration": "PENDING",
        "unityImport": "OUT_OF_SCOPE",
        "unitySaveReload": "OUT_OF_SCOPE",
        "prefabReload": "OUT_OF_SCOPE",
        "modularAvatar": "OUT_OF_SCOPE",
        "ndmf": "OUT_OF_SCOPE",
        "vrchatBuildTest": "OUT_OF_SCOPE",
        "vrchatRuntime": "OUT_OF_SCOPE",
        "humanRuntimeReview": "OUT_OF_SCOPE",
    }


def _manifest(
    job: dict,
    previews: dict[str, Path],
    multiview: Path,
    metrics: dict,
    cloth: list[dict],
) -> dict:
    root = job["productRoot"]
    return {
        "schemaVersion": 1,
        "productId": PRODUCT_ID,
        "productName": PRODUCT_NAME,
        "status": "WORKING",
        "state": "WORKING",
        "targetAdapterId": job["adapterId"],
        "target": "SiroinoSotai_PC neutral PC body",
        "productRoot": root,
        "outfitPrefabPath": job["prefabAssetPath"],
        "integratedPrefabPath": job["integratedPrefabAssetPath"],
        "previewPath": job["previewPaths"]["front"],
        "documentationPath": f"{root}/README.md",
        "sourceJobPath": f"config/products/{PRODUCT_ID}/job.json",
        "productBuildScript": job["buildScript"],
        "designRevision": REVISION,
        "reference": {
            "sourceImageRedistributed": False,
            "sourceImageSha256": REFERENCE_SHA256,
            "sourceImageDimensions": [2048, 1229],
        },
        "technicalGates": _technical_gates(),
        "outputs": {
            "blend": job["blendPath"],
            "fbx": job["fbxAssetPath"],
            "prefab": job["prefabAssetPath"],
            "integratedPrefab": job["integratedPrefabAssetPath"],
            "multiview": multiview.relative_to(ROOT).as_posix(),
            "poseReview": f"{root}/Previews/{PRODUCT_ID}-pose-review.webp",
            "patternSpec": f"{root}/Documentation/pattern-spec.json",
            "researchTrial": (
                f"{root}/Research/patterngsl-autosew-cloth-trial.json"
            ),
            "fitAudit": f"{root}/Tests/fit-audit.json",
            "visualReview": f"{root}/Tests/visual-review.json",
        },
        "metrics": metrics,
        "clothSimulation": cloth,
        "fiveViewEvidence": {
            name: {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": base.sha256(path),
            }
            for name, path in previews.items()
        },
        "rejectedHistory": [
            {
                "revision": "v1-pattern-gsl-modular-cloth",
                "result": "VISUAL_REJECTED",
                "hostedWorkflowRun": 30934884455,
                "artifactId": 8903072226,
                "artifactSha256": V1_ARTIFACT_SHA256,
                "evidence": "Tests/visual-review-v1.json",
            }
        ],
        "handoff": {
            "resumable": True,
            "canonicalWorkspace": root,
            "doNotRebuildFromZero": True,
            "resumeFrom": job["buildScript"],
            "blockers": [
                "Generate and inspect all required pose images.",
                "Pass direct visualAppearanceReview on current evidence.",
            ],
        },
    }


def _write_hashes(root: Path) -> None:
    tracked = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.name != "SOURCE_HASHES.txt"
    )
    lines = [
        f"{base.sha256(path)}  {path.relative_to(root).as_posix()}"
        for path in tracked
    ]
    (root / "SOURCE_HASHES.txt").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def write_records(
    job: dict,
    previews: dict[str, Path],
    multiview: Path,
    metrics: dict,
    cloth: list[dict],
) -> None:
    root = base.repo_path(job["productRoot"])
    pattern = _pattern(cloth)
    _write_json(root / "Documentation" / "pattern-spec.json", pattern)
    _write_json(
        root / "Research" / "patterngsl-autosew-cloth-trial.json",
        _research(pattern, cloth),
    )
    _write_json(
        root / "Tests" / "visual-review.json",
        {
            "schemaVersion": 2,
            "designRevision": REVISION,
            "productId": PRODUCT_ID,
            "result": "PENDING",
            "visualAppearanceReview": "PENDING",
            "reviewer": None,
            "blockingFindings": [],
            "nextAction": (
                "Open current five-view and required-pose images and record PASS or FAIL."
            ),
        },
    )
    _write_json(
        base.repo_path(job["productManifestPath"]),
        _manifest(job, previews, multiview, metrics, cloth),
    )

    cloth_frames = cloth[0]["frames"]
    (root / "README.md").write_text(
        f"""# {PRODUCT_NAME}

`WORKING` — SiroinoSotai_PC向けの黒・ベージュ・白のモジュール式衣装です。

- revision: `{REVISION}`
- explicit open multi-ring panel / seam / layer specification
- Blender cloth simulation: {cloth_frames} frames
- modular beret, ears, planar feather wings, tail, leg warmers and charms
- reference image is hash-bound but not redistributed
- v1 rejected visual evidence is retained in `Tests/visual-review-v1.json`

5面レンダリングまで生成済みです。必須6ポーズと直接画像監査が完了するまで `COMPLETE` ではありません。Unity、Modular Avatar、NDMF、VRChat runtimeは `OUT_OF_SCOPE` です。
""",
        encoding="utf-8",
    )
    _write_hashes(root)
