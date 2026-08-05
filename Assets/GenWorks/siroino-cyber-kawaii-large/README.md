# Cyber Kawaii Layered Set for Siroino _Large

Target: **Siroino `_Large`**, baked from the official shape keys on `SiroinoSotai_PC.fbx`.

## Reviewed v6 silhouette

- main skirt: `topScale=0.985`, `bottomScale=0.835`, `pleatScale=0.56`, `zOffset=-0.006`
- narrower waistband and underskirt layers
- stronger Hips and side-specific upper-leg anchors
- maximum four normalized bone influences per vertex
- five-view and six-pose Blender evidence generated from the same checkpoint

## Production contract

The canonical contract is `Source/Patterns/cyber-kawaii-skirt.pattern.json`. It records eight panels, eight side-seam pairs, the reviewed silhouette parameters, required evidence paths, and acceptance thresholds.

1. GarmentCode: editable panel/interface output — **PENDING**
2. ZOZO Contact Solver: solved mesh and penetration report — **PENDING**
3. Material Maker: editable `.ptex` sources and PBR exports — **PENDING**
4. Blender: rig transfer, FBX, Prefab, multiview, and pose verification — **PASS**

## Current gates

Blender generation, topology, weighting, body clearance, five-view rendering, and pose rendering pass. GarmentCode output, ZOZO solved-mesh evidence, Material Maker sources, Unity import/reload, Modular Avatar/NDMF, VRChat Build & Test, and human runtime review remain explicit pending gates.

## Outputs

- Blender source: `Source/Blender/SiroinoCyberKawaii.blend`
- FBX: `Models/SiroinoCyberKawaii.fbx`
- outfit Prefab: `Prefab/SiroinoCyberKawaii.prefab`
- integrated Prefab: `Prefab/SiroinoSotai_CyberKawaii.prefab`
- five-view render: `Previews/siroino-cyber-kawaii-large-multiview.webp`
- pose review: `Previews/siroino-cyber-kawaii-large-pose-review.webp`
