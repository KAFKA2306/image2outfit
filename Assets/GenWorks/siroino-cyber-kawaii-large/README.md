# Cyber Kawaii Layered Set for Siroino _Large

Target: **Siroino `_Large`**, baked from the official shape keys on `SiroinoSotai_PC.fbx`.

## Visual revision v6

- waist and hip sections are measured from the baked target body
- the four skirt layers are resolved from the tracked pattern contract
- front/back ease is lower than side ease to correct the oversized right-view silhouette
- skirt weights follow the hips and side-specific upper legs with at most four influences
- Blender, FBX, five-view, and six-pose evidence are generated from the same checkpoint

## Reviewed evidence

- Hosted Blender run `30741167087`
- Release policy run `30741167081`
- body-clearance p01: approximately 5.2 mm
- unweighted vertices: 0
- weight-sum errors: 0
- degenerate triangles: 0
- maximum bone influences: 4

## Pattern-first production stages

1. GarmentCode-compatible editable pattern and seam contract
2. ZOZO Contact Solver sewing/contact output before release
3. Material Maker editable `.ptex` cloth sources and PBR exports before release
4. Blender rig transfer, pose verification, FBX, Prefab, and render evidence

The current checkpoint passes Blender generation, topology, weighting, clearance, five-view, and pose-render gates. ZOZO solved-mesh evidence, editable Material Maker sources, Unity import/reload, Modular Avatar/NDMF, VRChat Build & Test, and human runtime review remain explicit pending gates.
