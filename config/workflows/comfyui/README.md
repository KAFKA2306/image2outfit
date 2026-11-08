# Pinned ComfyUI geometry hypothesis

`pixal3d_trellis2_image_to_model.json` is the official Comfy-Org Pixal3D / TRELLIS.2 image-to-3D template, vendored at the source commit and SHA-256 in its lock file. The adapter selects TRELLIS.2 and caps its shape upsample resolution at 512, matching the resolution used by the repository's local TRELLIS.2 benchmark.

This graph produces a generic textured mesh. It does not produce garment panels, seam topology, a fitted/rigged garment, or Unity/VRChat release evidence. Its output may enter `initialize-3d` only as a non-canonical hypothesis; existing garment construction, cloth, skinning, geometry, visual-review, and release contracts remain authoritative.

## Local execution

The adapter accepts only a loopback ComfyUI URL (`127.0.0.1`, `localhost`, or `::1`). Import the pinned template into ComfyUI once so the UI can check/download its declared model files, then run the workflow with the local ComfyUI server enabled. The request must bind the reference image, blueprint, and target-avatar authority. Missing nodes, models, job errors, or output GLB files fail the stage; there is no fallback generator.

The uploaded reference remains in ComfyUI's local input directory so the ComfyUI history can reopen the run. It is not copied into Git or the product workspace.

Minimal request fields:

```json
{
  "schemaVersion": 1,
  "productId": "example-garment",
  "blueprintPath": "config/products/example-garment/blueprint.json",
  "targetAvatarAuthorityPath": "config/products/example-garment/target-avatar-authority.json",
  "referenceImagePath": "Assets/GenWorks/example-garment/Source/reference.png",
  "comfyuiUrl": "http://127.0.0.1:8188",
  "pollSeconds": 2,
  "timeoutSeconds": 1800
}
```

Bind `tools/comfyui_hypothesis_adapter.py --request {comfyRequest} --result {comfyResult}` to `initialize.external-hypothesis`, then pin that tool and require `generator.comfyui` in the pipeline request. The profile declares a Blender reconciliation option, but this repository currently has no executable binding for it. The generated GLB therefore remains a recorded hypothesis; it does not replace panel drafting or garment build.

The template and code licenses do not establish rights for every model weight or generated product. Keep product license and provenance checks in force before any release.

The local benchmark exercised the official TRELLIS.2 runner, not this ComfyUI API adapter. No ComfyUI server was available for an end-to-end run, so workflow conversion, node compatibility, and GLB retrieval remain unverified.
