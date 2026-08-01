# HAOLAN Bordeaux Knit Set — delivery candidate

This directory contains the generated garment candidate and its audit evidence. The licensed HAOLAN avatar source is not included.

## Current status

**Decision: NO-GO for customer delivery.**

Static geometry, skin-weight, FBX structure, prefab GUID, and independent geometry round-trip checks passed. Unity 2022.3.22f1 import/save-reload, VRChat SDK Build & Test, animated intersection checks, and the required actual five-direction preview have not all passed yet.

## Mandatory five-direction preview

The candidate must include actual renders of the same imported FBX and HAOLAN source in these five directions:

1. front
2. back
3. left side
4. right side
5. three-quarter angle

The five images must use the same candidate, rest pose, framing, lighting, camera projection, and 1024 × 1024 resolution. An AI-generated illustration, concept sheet, duplicated view, or unrelated replacement asset is not accepted as verification.

Expected files:

- `Previews/front.png`
- `Previews/back.png`
- `Previews/left.png`
- `Previews/right.png`
- `Previews/three-quarter.png`
- `Previews/HAOLAN_BordeauxKnitSet_multiview.webp`
- `Previews/preview-manifest.json`

The manifest binds the preview to the SHA-256 hashes of the actual avatar source and outfit FBX while keeping the licensed avatar file out of the repository.

## Included now

- `HAOLAN_BordeauxKnitSet.prefab`: generated Unity prefab candidate
- `AUDIT_REPORT.md`: explicit release-gate result
- `audit-summary.json`: machine-readable metrics and failed gates
- `preview-requirements.json`: machine-readable five-view contract
- `SOURCE_HASHES.txt`: hashes of the generated FBX, prefab, and delivery archive held by the pipeline

## Preview generation

`Render HAOLAN Bordeaux five-view preview` runs on the Windows self-hosted runner. It locates the exact local HAOLAN source, finds or reproducibly rebuilds `HAOLAN_BordeauxKnitSet.fbx`, renders the five required views in Blender, writes a hash-bound manifest, composes the WebP sheet, and commits only the generated preview evidence.

## Generated asset publication

The pipeline must explicitly reject the original `HAOLAN_Lowpoly.fbx` and `HAOLAN_Lowpoly Variant.prefab` from the publish tree. Preview evidence may identify the source by SHA-256 but must not redistribute the licensed avatar source.

Credit required by the HAOLAN creator: かなﾘぁさんち / HAOLAN.
