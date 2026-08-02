#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json, shutil
from datetime import datetime, timezone
from pathlib import Path

PID = "cow-hood-knit-set-v1"
NAME = "HAOLAN Cow Hood Knit Set"
ROOT = f"Assets/GenWorks/{PID}"
LEGACY = f"Assets/GenWorks/Legacy/Snapshots/haolan/{PID}"
PREFAB = f"{ROOT}/Prefab/HAOLAN_CowHoodKnitSet.prefab"


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--generated", type=Path, required=True)
    ap.add_argument("--repo", type=Path, default=Path("."))
    ns = ap.parse_args()
    src, repo = ns.generated.resolve(), ns.repo.resolve()
    dst = repo / ROOT
    if dst.exists(): shutil.rmtree(dst)
    for d in ("Models", "Prefab", "Previews", "Textures"): (dst / d).mkdir(parents=True, exist_ok=True)

    copies = {
        "HAOLAN_CowHoodKnitSet.fbx": "Models/HAOLAN_CowHoodKnitSet.fbx",
        "HAOLAN_CowHoodKnitSet.fbx.meta": "Models/HAOLAN_CowHoodKnitSet.fbx.meta",
        "HAOLAN_CowHoodKnitSet_preview.glb": "Models/HAOLAN_CowHoodKnitSet_preview.glb",
        "HAOLAN_CowHoodKnitSet.prefab": "Prefab/HAOLAN_CowHoodKnitSet.prefab",
        "HAOLAN_CowHoodKnitSet.prefab.meta": "Prefab/HAOLAN_CowHoodKnitSet.prefab.meta",
        "Preview/front.png": "Previews/front.png",
        "Preview/back.png": "Previews/back.png",
        "Preview/side.png": "Previews/side.png",
        "Preview/three_quarter.png": "Previews/three_quarter.png",
        "HAOLAN_CowHoodKnitSet_preview.webp": "Previews/cow-hood-knit-set-v1-multiview.webp",
    }
    for a, b in copies.items():
        source, target = src / a, dst / b
        if not source.is_file(): raise FileNotFoundError(source)
        shutil.copy2(source, target)
    for source in sorted((src / "Textures").glob("*")):
        if source.is_file(): shutil.copy2(source, dst / "Textures" / source.name)

    audit = json.loads((src / "audit.json").read_text(encoding="utf-8"))
    metrics, static = audit["fbx"], audit["staticGeometry"]["metrics"]
    if (metrics["meshObjects"], metrics["vertices"], metrics["triangles"]) != (24, 18394, 34778):
        raise RuntimeError(f"unexpected geometry: {metrics}")
    if any(static[k] for k in ("nonFiniteValues", "degenerateTriangles", "unweightedVertices", "weightSumErrors")):
        raise RuntimeError(f"static validation failed: {static}")
    now = datetime.now(timezone.utc).isoformat()
    previews = {k: f"{ROOT}/Previews/{v}" for k, v in {
        "front":"front.png", "back":"back.png", "side":"side.png",
        "threeQuarter":"three_quarter.png", "multiview":"cow-hood-knit-set-v1-multiview.webp"}.items()}
    manifest = {
        "schemaVersion":1, "productId":PID, "productName":NAME, "version":"1.1",
        "status":"WORKING", "classification":"PARTIAL_CHECKPOINT", "targetAvatar":"HAOLAN Lowpoly",
        "productRoot":ROOT, "legacySnapshot":LEGACY, "generator":"tools/haolan_cow_generator_hosted.py",
        "modelPath":f"{ROOT}/Models/HAOLAN_CowHoodKnitSet.fbx", "prefabPath":PREFAB,
        "previewPaths":previews,
        "metrics":{k:metrics[k] for k in ("meshObjects","vertices","triangles","materials","bones","maxBoneInfluences")},
        "qualityGates":{"staticGeometry":"PASS","manualVisualCheckpoint":"PASS_WITH_RUNTIME_GATES_OPEN",
            "unityImport":"NOT_RUN","animatedClipping":"NOT_RUN","vrchatBuildTest":"NOT_RUN","inHeadset":"NOT_RUN"},
        "generatedAt":now,
    }
    dump(dst / "ProductManifest.json", manifest)
    (dst / "README.md").write_text(f'''# HAOLAN Cow Hood Knit Set v1.1

Canonical resumable checkpoint. The old blockout remains only as evidence at `{LEGACY}/`.

- Model: `Models/HAOLAN_CowHoodKnitSet.fbx`
- Prefab: `Prefab/HAOLAN_CowHoodKnitSet.prefab`
- Corrected views: `Previews/front.png`, `back.png`, `side.png`, `three_quarter.png`
- Multiview: `Previews/cow-hood-knit-set-v1-multiview.webp`

Static geometry and regenerated visual evidence pass. Customer release remains **NO-GO** until Unity 2022.3.22f1 import/save-reload, animated clipping, VRChat Build & Test and in-headset review pass.

HAOLAN credit: かなﾘぁさんち / HAOLAN. HAOLAN source files are not redistributed.
''', encoding="utf-8")
    (dst / "VISUAL_REVIEW.md").write_text(f'''# HAOLAN Cow Hood Knit Set v1.1 — Visual Review

**Canonical checkpoint: PASS. Customer release: NO-GO.**

Fixed from Legacy:
- moved the active checkpoint to `{ROOT}/` and retained Legacy as historical evidence;
- corrected front/back semantics so `Previews/back.png` shows the closed hood and rear tail;
- rebuilt sleeves with curved centerlines, elbow drop, bell flare, gathering and shaped cuffs;
- rebuilt the hood as a dense inner/outer shell with thickness, controlled opening, back drape and ribbed edge;
- resized the crop top, added top/skirt hems, twelve broad skirt pleats, subdivided ears and drawstrings;
- removed engineering wire edges from the review render.

Static result: 24 objects, 18,394 vertices, 34,778 triangles; non-finite, degenerate, unweighted and weight-sum errors are all zero.

Unity import, animation clipping, VRChat Build & Test and in-headset material review remain open.
''', encoding="utf-8")
    audit.update({"product":"HAOLAN Cow Hood Knit Set v1.1","productRoot":ROOT,"decision":"NO-GO",
        "decisionScope":"customer/product release; canonical checkpoint PASS","legacySnapshot":LEGACY,
        "pathReview":{"canonicalRoot":"PASS","canonicalPrefabPattern":"PASS","legacyPreservedAsEvidence":True,
                      "frontBackLabelsCorrected":True}})
    audit["deliverables"] = {}
    dump(dst / "audit.json", audit)
    (dst / "AUDIT_REPORT.md").write_text((src / "AUDIT_REPORT.md").read_text(encoding="utf-8").replace("v1.0","v1.1"), encoding="utf-8")

    config = repo / f"config/products/{PID}"
    config.mkdir(parents=True, exist_ok=True)
    delivery = [p.relative_to(repo).as_posix() for p in sorted(dst.rglob("*")) if p.is_file()]
    dump(config / "job.json", {"schemaVersion":2,"renderLoopRevision":"v1.1-curved-sleeves-thick-hood-corrected-views",
        "id":PID,"productName":NAME,"adapterId":"haolan-v1.6-lowpoly","productRoot":ROOT,
        "productManifestPath":f"{ROOT}/ProductManifest.json","buildScript":"tools/haolan_cow_generator_hosted.py",
        "hostedPoseScript":"tools/haolan_cow_generator_hosted.py","blendPath":"Assets/_Local/Resolved/HAOLAN_CowHoodKnitSet.blend",
        "fbxAssetPath":f"{ROOT}/Models/HAOLAN_CowHoodKnitSet.fbx","prefabAssetPath":PREFAB,"integratedPrefabAssetPath":PREFAB,
        "targetAvatarAssetPath":"Assets/_Local/Resolved/HAOLAN_Lowpoly Variant.prefab","targetSourcePath":"Assets/_Local/Resolved/HAOLAN_Lowpoly.fbx",
        "artifactDir":f"Artifacts/{PID}","candidateDir":f"Candidates/{PID}","releaseDir":f"Release/{PID}",
        "licenseEvidence":f"config/products/{PID}/license.json","privateSourceRoots":["Assets/_Local","Assets/_Vendor"],
        "deliveryAssets":delivery,"previewPaths":previews,"humanEvidence":{"visual-review":f"{ROOT}/VISUAL_REVIEW.md",
        "pose-penetration-review":f"Assets/_Local/Evidence/{PID}/pose-penetration-review.json",
        "vrchat-runtime-review":f"Assets/_Local/Evidence/{PID}/vrchat-runtime-review.json"},"allowedExtraBones":[]})
    dump(config / "license.json", {"schemaVersion":1,"adapterId":"haolan-v1.6-lowpoly",
        "sourceUrl":"https://booth.pm/ja/items/3818504","license":"Creator terms: credited asset/product distribution allowed",
        "checkedAt":now,"commercialOutfitAllowed":True,"avatarFilesRedistributed":False,
        "notes":"Only original garment outputs are committed; HAOLAN source files are excluded."})

    catalog_path = repo / "Assets/GenWorks/OutfitCatalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    entry = {"productId":PID,"productName":NAME,"status":"WORKING","classification":"PARTIAL_CHECKPOINT",
             "productRoot":ROOT,"configuredPrefabPaths":[PREFAB],"trackedPrefabs":[PREFAB]}
    active = [x for x in catalog.get("activeProducts",[]) if x.get("productId") != PID] + [entry]
    backed = [x for x in catalog.get("assetBackedProducts",[]) if x.get("productId") != PID] + [entry]
    planned = [x for x in catalog.get("plannedProducts",[]) if x.get("productId") != PID]
    legacy_count = len(catalog.get("legacySnapshots",[]))
    catalog.update({"canonicalPattern":"Assets/GenWorks/{slug}/Prefab/*.prefab","activeProducts":active,
        "assetBackedProducts":backed,"plannedProducts":planned,"configuredProductCount":len(active),
        "activeAssetBackedCount":len(backed),"plannedContractCount":len(planned),"legacySnapshotCount":legacy_count,
        "assetBackedOutfitCount":len(backed)+legacy_count,"knownOutfitConceptCount":len(active)+legacy_count})
    dump(catalog_path, catalog)

    audit = json.loads((dst / "audit.json").read_text(encoding="utf-8")); audit["deliverables"] = {}
    for p in sorted(dst.rglob("*")):
        if p.is_file() and p.name not in {"audit.json","SOURCE_HASHES.txt"}:
            audit["deliverables"][p.relative_to(dst).as_posix()] = {"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"bytes":p.stat().st_size}
    dump(dst / "audit.json", audit)
    files = [p for p in sorted(dst.rglob("*")) if p.is_file() and p.name != "SOURCE_HASHES.txt"]
    (dst / "SOURCE_HASHES.txt").write_text("\n".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(dst).as_posix()}" for p in files)+"\n", encoding="utf-8")
    print(json.dumps({"productRoot":ROOT,"metrics":manifest["metrics"],"status":"PASS"}, indent=2))
    return 0

if __name__ == "__main__": raise SystemExit(main())
