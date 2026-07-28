# image2outfit execution contract

This repository is a working Unity project, not a documentation project.

When the user requests an outfit from an image or description, execute the complete job in this repository. Do not only explain how to do it.

## Required flow

1. Resolve the requested avatar, outfit parts, references, and requested deliverables from the prompt.
   The customer validation target is HAOLAN v1.6. Do not substitute another avatar without an explicit request.
2. Verify the current official avatar page, license, supported Unity/SDK versions, and required shaders. Record only source URLs and facts needed for the audit.
3. Put purchased, licensed, reference, and generated working files only under the existing ignored paths:
   - `Assets/_Reference/` target avatar and reference assets
   - `Assets/_Local/Jobs/<job-id>/` task-specific Blender scripts, `.blend`, configuration, and temporary files
   - `Assets/_Local/Generated/<job-id>/` FBX, materials, textures, and prefab source folder
   - `Artifacts/<job-id>/` machine-readable validation evidence
   - `Delivery/<job-id>/` customer deliverables
4. Never commit avatar source files, generated models, textures, previews, delivery files, credentials, or task-specific scripts.
5. Create the model in Blender. Do not substitute placeholder primitives, renamed existing assets, or fabricated metrics.
6. Create `Assets/_Local/Jobs/<job-id>/job.json` and a task-specific Blender build script. Run:
   `python tools/pipeline.py --job Assets/_Local/Jobs/<job-id>/job.json`
7. The pipeline must produce the requested FBX and Unity prefab, run Blender and Unity gates, and write `Delivery/<job-id>/audit.json`.
8. Report `GO` only when every requested deliverable exists, Blender and Unity gates pass, the exact target avatar source was tested, licensing permits the intended delivery, and any required VRChat SDK Build & Test evidence exists. Otherwise report `NO-GO` with the exact failed gates.
9. Do not silently replace the requested avatar. If its source data is unavailable, produce only work that can be honestly validated and keep the release `NO-GO`.
10. Final user response must contain only: decision, deliverable paths, key measured metrics, failed gates, and the commit/PR when repository code changed. Do not create a long report unless requested.

## job.json

Use repository-relative paths.

```json
{
  "id": "job-id",
  "productName": "Outfit name",
  "buildScript": "Assets/_Local/Jobs/job-id/build.py",
  "blendPath": "Assets/_Local/Jobs/job-id/outfit.blend",
  "fbxAssetPath": "Assets/_Local/Generated/job-id/outfit.fbx",
  "prefabAssetPath": "Assets/_Local/Generated/job-id/outfit.prefab",
  "targetAvatarAssetPath": "Assets/_Reference/avatar.prefab",
  "artifactDir": "Artifacts/job-id",
  "deliveryDir": "Delivery/job-id",
  "licenseEvidence": "Artifacts/job-id/license.json",
  "allowedExtraBones": [],
  "requiredEvidence": ["Artifacts/job-id/vrchat-build-test.json"]
}
```

The license evidence must contain `sourceUrl`, `checkedAt`, `commercialOutfitAllowed: true`, and `avatarFilesRedistributed: false`.

The Blender build script must accept `--job <absolute-job-json>`, save `blendPath`, and export `fbxAssetPath`. `requiredEvidence` is for checks that cannot be inferred from assets, such as an actual VRChat SDK Build & Test result. Missing evidence forces `NO-GO`.
