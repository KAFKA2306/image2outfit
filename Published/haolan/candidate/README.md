# HAOLAN Bordeaux Knit Set — delivery candidate

This directory contains the generated garment candidate and its audit evidence. The licensed HAOLAN avatar source is not included.

## Current status

**Decision: NO-GO for customer delivery.**

Static geometry, skin-weight, FBX structure, prefab GUID, and independent geometry round-trip checks passed. Unity 2022.3.22f1 import/save-reload, VRChat SDK Build & Test, and animated intersection checks have not yet passed.

## Included now

- `HAOLAN_BordeauxKnitSet.prefab`: generated Unity prefab candidate
- `AUDIT_REPORT.md`: explicit release-gate result
- `audit-summary.json`: machine-readable metrics and failed gates
- `SOURCE_HASHES.txt`: hashes of the generated FBX, prefab, and delivery archive held by the pipeline

## Generated asset publication

The `Remote static verification` workflow has been configured to publish generated garment assets to `Published/haolan/latest` only after the Blender/Unity static verification command succeeds. The workflow explicitly rejects the original `HAOLAN_Lowpoly.fbx` and `HAOLAN_Lowpoly Variant.prefab` from the publish tree.

Credit required by the HAOLAN creator: かなﾘぁさんち / HAOLAN.
