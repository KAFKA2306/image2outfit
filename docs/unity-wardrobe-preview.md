# Unity wardrobe preview workflow

This workflow makes the Unity-side outfit collection easier to browse without changing the existing Blender/evidence pipeline.

## 1. Assets visibility: Rainbow Folders 2

Rainbow Folders 2 is intentionally **not** added to `Packages/manifest.json` in this change.

The publisher's current Git UPM instructions use:

```text
https://github.com/Borod4r/Rainbow-Folders-2.git?path=Assets/Plugins/Borodar/RainbowFolders
```

However, the current upstream package metadata is `com.borodar.rainbow-folders` version `2.4.5` and declares `"unity": "6000.3"`, while this repository is pinned to Unity `2022.3.22f1`. Committing that UPM dependency would therefore create an unverified/incompatible package boundary for this project.

Use the publisher's Unity Asset Store distribution only after its Unity 2022.3 compatibility is confirmed in the actual Editor environment. Do not copy Asset Store package contents into this public repository.

Official sources:
- https://github.com/Borod4r/Rainbow-Folders-2
- https://assetstore.unity.com/packages/tools/utilities/rainbow-folders-2-143526

The publisher documents Alt-click on a folder to configure its icon/background. The GitHub repository states that code is Apache-2.0 and bundled artwork is CC BY-NC 4.0.

## 2. Preview camera, pose presets, and isolation

Open:

`GenWorks > Wardrobe Preview`

The window discovers the existing `Assets/GenWorks/**/ProductManifest.json` files and uses them as the wardrobe collection. Each card can show the product's `previewPath`, and selecting an item loads `integratedPrefabPath` first, falling back to `outfitPrefabPath`.

The 3D view is isolated: it renders a hidden clone in `PreviewRenderUtility`; selecting or posing an outfit does not mutate the open Scene. Drag in the preview to orbit and use the mouse wheel to zoom.

`GenWorksPreviewPreset` stores:
- camera orbit
- camera distance
- field of view
- pivot offset
- child transform pose data by hierarchy path

A preset can capture a Scene avatar pose and apply that pose only to the isolated preview clone.

This behavior is intentionally a project-owned implementation informed by Pumkin's Avatar Tools rather than a source copy. The upstream project is MIT-licensed and documents camera presets, hiding other avatars, and pose presets:
- https://github.com/rurre/PumkinsAvatarTools
- https://github.com/rurre/PumkinsAvatarTools/wiki
- https://github.com/rurre/PumkinsAvatarTools/blob/master/LICENSE

## 3. Wardrobe collection model

The UI keeps the repository's existing data contract instead of importing another wardrobe schema:

- collection discovery: `Assets/GenWorks/**/ProductManifest.json`
- identity: `productId`, `productName`
- compatibility grouping: `targetAdapterId`
- lifecycle/status: `status`
- visual card: `previewPath`
- isolated full preview: `integratedPrefabPath`
- install source: `outfitPrefabPath`

This follows the useful AvatarWardrobe interaction pattern—manage multiple clothes as a collection—while keeping GenWorks manifests canonical. The upstream AvatarWardrobe documentation describes multi-outfit management and one-click export of animation/controller/VRC menu/parameters:
- https://gitee.com/kunkan/vrchat-avatar-toolkit/blob/v2.0/Example/AvatarWardrobe/main.md

## 4. Apply with Modular Avatar

The repository already declares these VPM dependencies in `Packages/vpm-manifest.json`:

- `com.vrchat.base` 3.10.4
- `com.vrchat.avatars` 3.10.4
- `nadena.dev.modular-avatar` 1.17.1
- `nadena.dev.ndmf` 1.14.1

The Apply flow is explicit and Scene-mutating:

1. Select an outfit in `GenWorks > Wardrobe Preview`.
2. Assign an avatar instance from the open Scene.
3. Confirm or override `Merge Target`; the UI tries to infer the humanoid armature from Hips.
4. Click `Apply selected outfit with Modular Avatar`.
5. The backend instantiates the canonical `outfitPrefabPath` as a connected prefab under the avatar, finds or adds `nadena.dev.modular_avatar.core.ModularAvatarMergeArmature`, and configures its `mergeTarget` through `AvatarObjectReference.Set(GameObject)`.
6. All Scene changes are registered with Unity Undo.

Official Modular Avatar documentation and source:
- https://modular-avatar.nadena.dev/docs/intro
- https://github.com/bdunderscore/modular-avatar
- https://github.com/bdunderscore/modular-avatar/blob/main/Runtime/ModularAvatarMergeArmature.cs
- https://github.com/bdunderscore/modular-avatar/blob/main/Runtime/AvatarObjectReference.cs

If the window says `Modular Avatar: unresolved`, resolve the existing VPM project dependencies with ALCOM or VRChat Creator Companion before using Apply. The official Modular Avatar documentation recommends ALCOM and also supports VCC.

## Validation boundary

The implementation is Editor-only and leaves Preview non-destructive. Only the explicit Apply button changes the Scene. Unity package resolution, C# compilation, and a real avatar Apply/build test must still be executed in Unity 2022.3.22f1 before merge if no Unity Editor run is attached to the PR evidence.
