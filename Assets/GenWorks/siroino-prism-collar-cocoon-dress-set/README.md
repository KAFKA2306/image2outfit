# Prism Collar Cocoon Dress Set

Canonical workline: issue #500.

This workspace contains the manufacturing reference and a panel-first prototype checkpoint for the Siroino target. The hero requirement is a four-piece folded prism collar represented by separate geometry, plus a short cocoon skirt whose lateral volume comes from bounded inverted box pleats.

Current produced artifacts:
- `References/prism-collar-cocoon-manufacturing-sheet.svg`
- `Source/Patterns/pattern-spec.json`
- `Source/Prototype/prism-collar-cocoon.obj`
- `Source/Prototype/prism-collar-cocoon.mtl`

Prototype scope: 48 vertices, 48 UV coordinates, 12 named geometry groups and 12 polygon faces, with four collar groups explicitly separated. This is a construction checkpoint, not a fitted or rigged final asset.

Unverified until actually executed: Blender import/build, Siroino fit, rig/weight transfer, editable `.blend`, FBX, Prefab, five-view render, required poses, Unity import/save-reload, VRChat build/runtime.

Do not infer PASS from file declaration or CI alone. Continue from ProductManifest and issue #500; do not rebuild from a different product concept.
