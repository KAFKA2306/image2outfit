# Cyber Kawaii Layered Set for Siroino `_Large`

Status: **WORKING**

This product is tracked as a resumable GenWorks workspace. It is not complete and must not be restarted from an unrelated seed or another product's generated Blender file.

## Current source of truth

- Product contract: `config/products/siroino-cyber-kawaii-large/job.json`
- Product generator: `tools/siroino_cyber_kawaii_large_build.py`
- Product manifest: `Assets/GenWorks/Products/siroino-cyber-kawaii-large/ProductManifest.json`
- Intended target: official Siroino `_Large` Prefab and compatible complete body/armature FBX

## Rejected hosted attempt

PR #21 attempted to use `Assets/GenWorks/Products/siroino-wide-cargo/Source/Blender/SiroinoWideCargo.blend` as a hosted target seed. That file was a generated product scene, not a complete Siroino body source. The selected mesh covered only the cargo pelvis region, so the blouse torso extraction produced no faces. This attempt is retained as a diagnosed failure and must not be repeated.

## Required continuation

1. Resolve the complete official Siroino `_Large` target from private/local assets.
2. Run the existing product generator against that target.
3. Track the resulting Blender source, FBX, textures, materials, five-view renders, pose renders, and technical audit under this product directory.
4. Create `Prefabs/Outfit/SiroinoCyberKawaiiLarge.prefab`.
5. Create `Prefabs/Integrated/Siroino_Large/Siroino_Large_CyberKawaii.prefab` with the required Unity settings serialized.
6. Pass Unity import, save, reload, Prefab integrity, Modular Avatar/NDMF, and other applicable automated checks.
7. Change the manifest to `HUMAN_REVIEW_PENDING` only after the full technical checkpoint is present here.
8. Perform final human visual, pose, and VRChat runtime reviews before release.

Actions artifacts are supporting evidence only. The handoff is complete only when the tracked GenWorks workspace contains the usable Prefabs and Unity settings.
