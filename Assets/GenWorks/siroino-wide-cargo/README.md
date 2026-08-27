# Siroino Wide Cargo

`Assets/GenWorks/siroino-wide-cargo/ProductManifest.json`

`config/genworks-handoff-policy.json`

Original, logo-free wide cargo outfit for SiroinoSotai v1.0. The tracked garment has 1,168 vertices, 2,040 triangles, and up to 3 bone influences per vertex.

## Current repository state

The product remains `WORKING` under the current eight-gate completion policy.

Tracked evidence currently satisfies:

- Blender geometry/build state
- editable `.blend` source
- FBX export
- declared outfit Prefab
- five-view render evidence
- pose render evidence

The remaining repository-completion blockers are:

- direct visual appearance review evidence for the current revision is not independently readable from merged `main`;
- the required research trial is not declared/persisted by the legacy product job.

Unity import/save/reload, Modular Avatar/NDMF processing, VRChat Build & Test, and VRChat runtime are explicitly outside repository `COMPLETE` in `config/genworks-handoff-policy.json`. They remain unverified and must not be claimed as supported without external Unity/VRChat evidence.

## Tracked asset

The canonical outfit Prefab is:

`Assets/GenWorks/siroino-wide-cargo/Prefab/SiroinoWideCargo.prefab`

The repository does not currently track the declared integrated Prefab `Assets/GenWorks/siroino-wide-cargo/Prefab/SiroinoSotai_WideCargo.prefab`, so do not describe the current artifact as verified drag-and-drop avatar integration.

For Modular Avatar clothing setup, use the upstream `Setup Outfit` / `Merge Armature` workflow rather than repository-specific setup logic:

https://modular-avatar.nadena.dev/docs/tutorials/clothing
