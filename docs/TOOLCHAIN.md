# Reproducible avatar toolchain

`config/toolchain-lock.json` is the source of truth. Stable releases are pinned exactly; release candidates and betas are rejected by `tools/audit_toolchain.py`.

| Layer | Pinned version | Why it is in the gate | Official source |
| --- | --- | --- | --- |
| Blender | 4.4.3 | Deterministic generator, Cycles preview, and FBX export baseline | [4.4 corrective releases](https://developer.blender.org/docs/release_notes/4.4/corrective_releases/) |
| Unity | 2022.3.22f1 | VRChat-supported editor baseline | [VPM CLI Unity requirement](https://vcc.docs.vrchat.com/vpm/cli/#install-unity) |
| VRChat SDK | 3.10.4 | Avatar descriptor and Build & Test integration | [SDK 3.10.4 release](https://creators.vrchat.com/releases/release-3-10-4/) |
| Modular Avatar | 1.17.1 | Preset configuration and armature merge | [1.17.1 release](https://github.com/bdunderscore/modular-avatar/releases/tag/1.17.1) |
| NDMF | 1.14.1 | Automated bake validation of the integrated prefab | [AvatarProcessor API](https://ndmf.nadena.dev/api/nadena.dev.ndmf.AvatarProcessor.html) |
| Avatar Optimizer | 1.9.16 | Reproducible avatar-level optimization capability | [1.9.16 release](https://github.com/anatawa12/AvatarOptimizer/releases/tag/v1.9.16) |

The audited upstream repositories are [Modular Avatar](https://github.com/bdunderscore/modular-avatar), [NDMF](https://github.com/bdunderscore/ndmf), and [Avatar Optimizer](https://github.com/anatawa12/AvatarOptimizer).

## Restore and verify

Register the two community repositories once, then resolve the exact project manifest:

```powershell
vpm add repo https://vpm.nadena.dev/vpm.json
vpm add repo https://vpm.anatawa12.com/vpm.json
vpm resolve project .
python tools/audit_toolchain.py
```

The VPM resolver restores the packages listed in `Packages/vpm-manifest.json`; Unity then owns `Packages/packages-lock.json`. Do not hand-edit the Unity lock file. The candidate workflow requires it after Unity resolution, following the [Unity lock-file guidance](https://docs.unity3d.com/2022.3/Documentation/Manual/upm-conflicts-auto.html) and [VPM source-control guidance](https://vcc.docs.vrchat.com/vpm/source-control/).

## Outfit rules encoded in Unity

- The outfit armature object receives a `.1` suffix to avoid Unity hierarchy-name bugs while the merge target keeps the base armature name.
- Merge Armature uses `BaseToMerge` position lock and keeps unique-bone collision avoidance enabled.
- The saved integrated prefab is instantiated and processed with NDMF; unresolved mappings, new missing scripts, renderer loss, or invalid skinned renderers fail the technical gate.
- Avatar Optimizer is installed but no optimizer component is injected automatically. Optimization is an avatar-level decision and cannot substitute for fit, pose, or runtime evidence.

These defaults follow the official [Merge Armature reference](https://modular-avatar.nadena.dev/docs/reference/merge-armature), [outfit-creator guidance](https://modular-avatar.nadena.dev/docs/distributing-prefabs/for-outfit-creators), [Blender command-line documentation](https://docs.blender.org/manual/en/4.4/advanced/command_line/index.html), and [VRChat avatar optimization guidance](https://creators.vrchat.com/avatars/avatar-optimizing-tips/).
