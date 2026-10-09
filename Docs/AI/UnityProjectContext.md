# Unity Project Context

<!-- unity-onboarding:generated:start -->

## Project Summary

- Project root: `M:/win11projects/unity/image2outfit`
- Last analyzed: 2026-09-24
- Last analyzed commit: `7553cde58ff9cabf88da255cb2f83a86d66b126d`

## Confirmed Environment

- Unity version: 2022.3.22f1 (`887be4894c44`)
- Render pipeline: likely Built-in; no URP/HDRP package is present, while the Unity CLI reports `Unknown`.
- Input system: likely legacy Input Manager; no Input System package or active-handler override was found.
- Target platforms: Standalone Windows 64-bit is the current project target.

## Important Packages And Frameworks

| Area | Finding | Confidence | Evidence |
| --- | --- | --- | --- |
| VRChat | VRChat Avatars/Base packages are embedded under `Packages/`. | Confirmed | `Packages/` |
| Avatar authoring | Modular Avatar, NDMF, Avatar Optimizer, and Continuous Avatar Uploader are embedded packages. | Confirmed | `Packages/`, `README.md` |
| Editor automation | TunaSync Unity MCP 2.6.8 is connected on the local loopback bridge. | Confirmed | `Packages/manifest.json`, Unity MCP health check |
| Tests | Unity Test Framework 1.1.29 is installed. | Confirmed | `Packages/manifest.json` |

## Directory Structure

| Path | Purpose | Confidence | Evidence |
| --- | --- | --- | --- |
| `Assets/GenWorks/` | Product assets and shared editor pipeline. | Confirmed | `Assets/GenWorks/Shared/Editor/` |
| `Assets/Scenes/Avatar/` | Avatar workbench and product scenes. | Confirmed | `ProjectSettings/EditorBuildSettings.asset` |
| `Assets/OSSBenchmarks/` | Local OSS model benchmark assets and comparison scenes. | Confirmed | `Assets/OSSBenchmarks/` |
| `Assets/UnityMCP_CAU/` | Continuous Avatar Uploader settings assets. | Confirmed | `Assets/UnityMCP_CAU/` |
| `Packages/` | Embedded VPM packages and Unity package manifest. | Confirmed | `Packages/` |

## Assembly Boundaries

| Assembly | Responsibility | Key references | Notes |
| --- | --- | --- | --- |
| `com.vrchat.core.vpm-resolver.Editor` | VPM resolver editor integration. | VRChat VPM tooling | Embedded package assembly. |
| First-party assembly definitions | No first-party `.asmdef` was found under `Assets/`; most shared editor code is compiled by Unity's default editor assembly. | `Assets/GenWorks/Shared/Editor/` | Confirmed by repository scan. |

## Scenes And Startup Flow

- Build scenes: the enabled scenes are listed in `ProjectSettings/EditorBuildSettings.asset`, beginning with `Assets/Scenes/Avatar/00_SiroinoOutfitWorkbench.unity` and the numbered avatar scenes.
- Likely startup scene: `Assets/Scenes/Avatar/00_SiroinoOutfitWorkbench.unity`.
- Scene loading flow: not established from the inspected files.
- Current benchmark scene: `Assets/OSSBenchmarks/Blueprint20260922/Blueprint20260922_ScreenshotComparison.unity` is open in the connected Editor for the screenshot comparison.

## Architecture

| Pattern | Finding | Confidence | Evidence |
| --- | --- | --- | --- |
| Editor pipeline | Static editor pipeline code reads job contracts, validates generated assets, and writes reports. | Confirmed | `Assets/GenWorks/Shared/Editor/Image2OutfitPipeline.cs` |
| Asset-driven authoring | ScriptableObject settings and prefab assets drive avatar upload and product workflows. | Confirmed | `Assets/UnityMCP_CAU/`, `Assets/GenWorks/` |
| Runtime architecture | Product runtime composition is not fully established in this read-only pass. | Unknown | Limited representative inspection. |

## Coding Conventions

- Namespace style: `Image2Outfit.Editor` is used by shared editor pipeline code.
- Serialized fields: not established broadly in this pass.
- Async: editor pipeline code uses `Task` for long-running workflow steps.
- Comments/docs: implementation comments and XML-style documentation are used selectively.

## Testing And Validation

- EditMode tests: no first-party `*Tests.cs` files were found in the repository scan.
- PlayMode tests: no first-party `*Tests.cs` files were found in the repository scan.
- CI/build validation: product README documents `task avatar:preflight` and Unity MCP validation; no build was run during onboarding.

## Available Unity Tooling

| Capability | Status | Evidence |
| --- | --- | --- |
| `unity.connection.status` | available | Unity MCP health check connected to image2outfit. |
| `unity.editor.version` | available | Unity MCP health check and `ProjectVersion.txt`. |
| `unity.console.read` | available | Unity MCP `get_logs`. |
| `unity.scene.inspect` | available | Unity MCP `get_editor_state`. |
| `unity.asset.search` | available | Unity Editor eval/AssetDatabase path. |
| `unity.camera.capture` | available | Unity MCP `camera_capture`; verified with the Blueprint comparison scene. |
| `unity.tests.run` | available in package, not exercised | Unity Test Framework is installed; no first-party tests were found. |
| Unity Pipeline CLI bridge | unavailable | `unity status` found no `com.unity.pipeline` editor instance. |

## Important Constraints

- Preserve unrelated existing changes and tracked Unity `.meta`/GUID relationships.
- Treat `Library/`, `Temp/`, `Logs/`, and other generated directories as non-source state.
- Keep OSS benchmark outputs isolated under `Assets/OSSBenchmarks/<benchmark>/`.
- Do not claim VRChat runtime or public-upload validation from local Unity Editor evidence alone.

## Unknowns And Confidence

- Render pipeline and input classification are inferred from package/settings evidence; the Unity CLI surface reports the render pipeline as `Unknown`.
- The full runtime dependency graph and scene-loading implementation were not inspected.
- Visual acceptance of product assets remains governed by the repository's canonical quality policies.

## Source Files Inspected

- `AGENTS.md`
- `README.md`
- `ProjectSettings/ProjectVersion.txt`
- `ProjectSettings/EditorBuildSettings.asset`
- `ProjectSettings/ProjectSettings.asset`
- `Packages/manifest.json`
- `Packages/packages-lock.json`
- `Assets/GenWorks/Shared/Editor/Image2OutfitPipeline.cs`
- `Assets/UnityMCP_CAU/`
- `Assets/OSSBenchmarks/`

<!-- unity-onboarding:generated:end -->
