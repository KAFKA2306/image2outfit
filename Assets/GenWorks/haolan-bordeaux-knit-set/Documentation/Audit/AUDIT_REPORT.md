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

## Five-direction preview gate

**Status: FAIL / pending evidence**

The candidate must provide actual 1024 × 1024 renders of the same imported FBX and HAOLAN source from front, back, left side, right side, and a three-quarter angle. The view set must be accompanied by `Previews/preview-manifest.json`, binding it to the source-avatar and outfit-FBX SHA-256 hashes. AI-generated illustrations and duplicated views do not satisfy this gate.

## Failed release gates

- Actual front/back/left/right/three-quarter preview evidence has not yet been committed.
- Unity 2022.3.22f1 ModelImporter was not executed for this candidate.
- The prefab was not saved and reloaded by `PrefabUtility` for this candidate.
- VRChat SDK Build & Test was not run.
- Animated crouch, sit, prone, arm-crossing, and full-body tracking intersection tests were not run.

The files are a target-fitted delivery candidate. They must not be represented as a runtime-verified Unity/VRChat release until the failed gates pass.
