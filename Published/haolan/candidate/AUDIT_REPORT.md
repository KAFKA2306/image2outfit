# Delivery audit

**Decision: NO-GO**

## Static results

- Exact supplied target skeleton inspected: True
- Mesh objects: 13
- Vertices: 3,738
- Triangles: 7,176
- Watertight meshes: 13 / 13
- Non-manifold edges: 0
- Degenerate triangles: 0
- Unweighted vertices: 0
- Weight-sum errors: 0
- Maximum bone influences: 4
- FBX array/count and brace validation: PASS
- Prefab/FBX/material GUID static validation: PASS
- Independent GLB geometry round trip: PASS (3,738 vertices, 7,176 triangles)

## Failed release gates

- Unity 2022.3.22f1 ModelImporter was not executed for this candidate.
- The prefab was not saved and reloaded by `PrefabUtility` for this candidate.
- VRChat SDK Build & Test was not run.
- Animated crouch, sit, prone, arm-crossing, and full-body tracking intersection tests were not run.

The files are a target-fitted delivery candidate. They must not be represented as a runtime-verified Unity/VRChat release until the failed gates pass.
