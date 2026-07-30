# image2outfit

`image2outfit` is a customer-delivery pipeline for VRChat avatar garments. It is not a mesh generator demo and it does not equate structural validity with product quality.

## Product contract

A garment can be released only after all of the following are true:

1. The exact private target avatar and license evidence are present locally and are never redistributed.
2. Blender creates an editable `.blend` and exportable FBX without structural failures.
3. Unity 2022.3.22f1 imports the FBX, saves the outfit Prefab, and validates integration with the exact target avatar.
4. Five full-quality previews exist: front, back, left, right, and three-quarter.
5. A human approves silhouette, body fit, material expression, and presentation quality.
6. Neutral, arms-up, arm-cross, crouch, sit, and prone tests have no critical penetration.
7. VRChat SDK Build & Test and an in-client human runtime check pass.
8. Every review is bound to the exact candidate manifest hash.

The current primary adapter is `pochi-v1.1.0`. `haolan-v1.6` is blocked from release by `config/release-policy.json` and remains legacy research only.

## State machine

```text
SPECIFIED
  -> MODELED
  -> TECHNICAL_PASS
  -> REVIEW_REQUIRED
  -> VISUAL_PASS
  -> POSE_PASS
  -> RUNTIME_PASS
  -> GO / RELEASED
```

Any failed or missing gate produces `NO-GO`. There is no automatic path from `TECHNICAL_PASS` to `GO`.

## Two workflows

### 1. Build a candidate

```powershell
task candidate JOB=Assets/_Local/Jobs/<job-id>/job.json
```

This runs Blender and Unity static validation, validates five preview files, copies only the explicit `deliveryAssets`, and writes an immutable candidate manifest. The final decision is always `REVIEW_REQUIRED` when technical checks pass. It never writes `Release/`.

### 2. Promote a reviewed release

```powershell
task release JOB=Assets/_Local/Jobs/<job-id>/job.json
```

This does not rebuild. It verifies that the reviewed candidate and every input hash remain unchanged, validates the three mandatory human evidence files, then writes `Release/<job-id>/` and a ZIP only when the decision is `GO`.

## Rights separation

Private or purchased avatar data stays under ignored local roots such as `Assets/_Local/`, `Assets/_Vendor/`, `Assets/PochibyKT/`, and other roots listed in `privateSourceRoots`. A job must explicitly enumerate every output file in `deliveryAssets`. The pipeline rejects any delivery file located under a private source root.

## Evidence and audit

- `Artifacts/<job-id>/audit.json`: current decision and stage results
- `Candidates/<job-id>/candidate-manifest.json`: exact candidate lineage and hashes
- `Release/<job-id>/release-manifest.json`: immutable GO release record
- `docs/REVIEW_EVIDENCE.md`: mandatory human evidence schema
- `config/job.schema.v2.json`: job contract
- `config/release-policy.json`: non-waivable release policy

Checked-in files under `Published/` are legacy snapshots, not customer releases. New generated garments are distributed only as release workflow artifacts after `GO`.
