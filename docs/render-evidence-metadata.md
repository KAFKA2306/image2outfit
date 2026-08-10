# Render evidence metadata

Every direct Blender PNG render under `Assets/GenWorks/<product>/Previews/` has an adjacent sidecar named `<artifact>.render.json`.

The sidecar is written by `tools/render_evidence_bootstrap.py` from Blender's `render_post` handler, so camera values are captured from the scene that actually produced the image rather than reconstructed later.

## Schema version 1

```json
{
  "schemaVersion": 1,
  "kind": "image2outfit-render-evidence-metadata",
  "artifactPath": "Assets/GenWorks/example/Previews/front.png",
  "generatorRevision": "v2-five-view-six-pose",
  "sourceCommit": "0123456789abcdef...",
  "camera": {
    "name": "GenWorks_Product_Camera",
    "type": "ORTHO",
    "location": [0.0, -2.55, 0.7],
    "rotationEulerRadians": [1.2, 0.0, 0.0],
    "lensMm": 72.0,
    "orthoScale": 1.3
  },
  "render": {
    "engine": "CYCLES",
    "resolutionX": 1024,
    "resolutionY": 1024,
    "resolutionPercentage": 100
  }
}
```

`generatorRevision` is copied from the product job's `renderLoopRevision`, falling back to `buildRevision`. A missing revision stops the Blender build rather than creating unverifiable evidence. `sourceCommit` is the current `GITHUB_SHA` when available, otherwise `git rev-parse HEAD`; it may be `null` only when neither source can be resolved.

`camera.location` and `camera.rotationEulerRadians` are three-element Blender-space vectors captured after the render. Camera type, lens, orthographic scale, render engine, and output resolution are stored so two evidence images can be compared without guessing the view setup.

## Audit

Run:

```text
python tools/audit_render_evidence_metadata.py
```

The audit scans direct PNG render evidence below every canonical `Assets/GenWorks/*/Previews/` root. It fails when a sidecar is missing, malformed, points at another artifact, has no generator revision, or lacks required camera/render parameters.

Historical images without a trustworthy sidecar must be regenerated through the canonical Blender build. Do not backfill camera values by inference from filenames or current source code; metadata is evidence about the render that actually happened.
