"""Generated records and Unity declarations for the Nocturne Angel set."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import siroino_strappy_knit_build as base

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ID = "siroino-nocturne-angel-set"
PRODUCT_NAME = "Nocturne Angel Modular Set for Siroino"
REVISION = "v6-welded-projected-pleats"
REFERENCE_SHA256 = "a4a15a6fc6b7290af41dbc82b5fc55e7ab74370c33018816fd829d8307629f67"
REJECTED_HISTORY = [
    {
        "revision": "v1-pattern-gsl-modular-cloth",
        "result": "VISUAL_REJECTED",
        "hostedWorkflowRun": 30934884455,
        "artifactId": 8903072226,
        "artifactSha256": "1281d60218aec96072a910e0c1296652344f23c62d493882ffb7b61c0392551a",
        "evidence": "Tests/visual-review-v1.json",
    },
    {
        "revision": "v2-open-multiring-reference-silhouette",
        "result": "VISUAL_REJECTED",
        "hostedWorkflowRun": 30937377321,
        "artifactId": 8904078622,
        "artifactSha256": "5f3465dc50486b627df520142a7a74fa2b5b98d22089a509d124a5d1936be3fc",
        "evidence": "Tests/visual-review-v2.json",
    },
    {
        "revision": "v3-sewn-v-neck-stable-modules",
        "result": "VISUAL_REJECTED",
        "hostedWorkflowRun": 30957408404,
        "artifactId": 8911782998,
        "artifactSha256": "0921d4d449985ef757db808dc9b316421f1a70374f8cd5c4f75d562f254f3d2b",
        "evidence": "Tests/visual-review-v3.json",
    },
    {
        "revision": "v4-clearance-articulated-silhouette",
        "result": "VISUAL_REJECTED",
        "hostedWorkflowRun": 30959394549,
        "artifactId": 8912558603,
        "artifactSha256": "086c1fa3ab50d37d6f44bd1af2605d45800a4973623434a405fc2224d15d94c1",
        "evidence": "Tests/visual-review-v4.json",
    },
    {
        "revision": "v5-skinweighted-pleated-volume",
        "result": "VISUAL_REJECTED",
        "hostedWorkflowRun": 30961445364,
        "artifactId": 8913291340,
        "artifactSha256": "316592e0023e924a3b4028c923764047f202c6984d99a88c2f16fa36933fe852",
        "evidence": "Tests/visual-review-v5.json",
    },
]


def _guid(label: str) -> str:
    return hashlib.md5(f"image2outfit:{PRODUCT_ID}:{label}".encode()).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_guid(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("guid: "):
            return line.removeprefix("guid: ").strip()
    raise RuntimeError(f"Unity meta file has no guid: {path}")


def write_integrated_prefab(job: dict) -> Path:
    outfit = base.repo_path(job["prefabAssetPath"])
    meta = outfit.with_suffix(outfit.suffix + ".meta")
    if not outfit.is_file() or not meta.is_file():
        raise RuntimeError("outfit Prefab declaration is missing")
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
    - target: {{fileID: 100000, guid: {_read_guid(meta)}, type: 3}}
      propertyPath: m_Name
      value: SiroinoSotai_NocturneAngelSet
      objectReference: {{fileID: 0}}
    m_RemovedComponents: []
    m_RemovedGameObjects: []
    m_AddedGameObjects: []
    m_AddedComponents: []
  m_SourcePrefab: {{fileID: 100100000, guid: {_read_guid(meta)}, type: 3}}
""",
        encoding="utf-8",
    )
    integrated.with_suffix(integrated.suffix + ".meta").write_text(
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


def _pattern(cloth: list[dict]) -> dict:
    logical_panels = [
        "front-left",
        "front-right",
        "back",
        "side-left",
        "side-right",
    ]
    seams = [
        ("front-center", "front-left.center", "front-right.center"),
        ("left-side-front", "front-left.side", "side-left.front"),
        ("left-side-back", "side-left.back", "back.left"),
        ("right-side-front", "front-right.side", "side-right.front"),
        ("right-side-back", "side-right.back", "back.right"),
    ]
    return {
        "schemaVersion": 2,
        "productId": PRODUCT_ID,
        "designRevision": REVISION,
        "status": "GENERATED",
        "representation": (
            "five logical pattern regions welded into one projected V-neck shell, "
            "zero-force pleated cloth and simplified body-following modules"
        ),
        "bodyTopologyCopied": False,
        "logicalBodicePanels": logical_panels,
        "generatedBodiceObject": "Nocturne_Sewn_Bodice",
        "sewnContinuousShell": True,
        "seams": [
            {"id": identifier, "a": first, "b": second}
            for identifier, first, second in seams
        ],
        "modules": {
            "core": ["sewn bodice", "pleated skirt", "collar", "sleeves"],
            "back": ["three volumetric feathers per side", "tail"],
            "legs": ["body-following warmers", "body-following shoes"],
            "accessories": ["choker", "amber charm", "rabbit charm"],
            "omittedFromReview": [
                "beret and animal ears because the target evidence has no visible head mesh"
            ],
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
            "PatternGSL-inspired logical panels and seams, welded independent shell, "
            "Blender cloth checkpoint and evaluated-body projection"
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
            "logicalPanelCount": len(pattern["logicalBodicePanels"]),
            "generatedBodiceObjects": 1,
            "nearestSurfaceProjection": True,
            "outwardSolidify": True,
            "actualBlenderClothExecuted": all(
                item.get("baked") is True for item in cloth
            ),
            "clothGravityWeight": 0.0,
            "weightTransfer": "four strongest groups from nearest evaluated body vertex",
        },
        "clothSimulation": cloth,
        "acceptance": {
            "researchTrial": "PASS",
            "visualAppearanceReview": "PENDING",
        },
    }


def _gates() -> dict:
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


def _manifest(job, previews, multiview, metrics, cloth):
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
        "technicalGates": _gates(),
        "outputs": {
            "blend": job["blendPath"],
            "fbx": job["fbxAssetPath"],
            "prefab": job["prefabAssetPath"],
            "integratedPrefab": job["integratedPrefabAssetPath"],
            "multiview": multiview.relative_to(ROOT).as_posix(),
            "poseReview": f"{root}/Previews/{PRODUCT_ID}-pose-review.webp",
            "patternSpec": f"{root}/Documentation/pattern-spec.json",
            "researchTrial": f"{root}/Research/patterngsl-autosew-cloth-trial.json",
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
        "rejectedHistory": REJECTED_HISTORY,
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
        f"{base.sha256(path)}  {path.relative_to(root).as_posix()}" for path in tracked
    ]
    (root / "SOURCE_HASHES.txt").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def write_records(job, previews, multiview, metrics, cloth) -> None:
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
    (root / "README.md").write_text(
        f"""# {PRODUCT_NAME}

`WORKING` — SiroinoSotai_PC向けの黒・ベージュ・白のモジュール式衣装です。

- revision: `{REVISION}`
- five logical bodice panels welded into one continuous projected V-neck shell
- outward-only thickness and nearest-body four-influence weight transfer
- short twelve-pleat skirt with a 32-frame zero-force Blender Cloth checkpoint
- unsupported head modules omitted from review because the target has no visible head mesh
- three compact volumetric feathers per wing
- reference image is hash-bound but not redistributed
- rejected v1 through v5 evidence remains under `Tests/`

5面レンダリングまで生成済みです。必須6ポーズと直接画像監査が完了するまで `COMPLETE` ではありません。Unity、Modular Avatar、NDMF、VRChat runtimeは `OUT_OF_SCOPE` です。
""",
        encoding="utf-8",
    )
    _write_hashes(root)
