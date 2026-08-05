# QualitySpec v1

`QualitySpec` is the diagnostic source of truth beneath the existing eight
completion gates. It does not add Unity, NDMF, Modular Avatar, VRChat runtime,
or any other permanently out-of-scope gate.

## Why the quality axes are separate

The 2026 research baseline supports cause-specific evaluation rather than one
appearance average:

- ReWeaver separates topology accuracy, geometry alignment, and seam-panel
  consistency for simulation-ready garment reconstruction.
  <https://arxiv.org/abs/2601.16672>
- AutoSew and Learning-based Seam Correspondence Reconstruction model seam
  connectivity and detailed edge correspondence as explicit graph problems.
  <https://arxiv.org/abs/2602.22052>
  <https://arxiv.org/abs/2607.21213>
- EASE treats local ease as an explicit spatial field, supporting fit diagnosis
  independently of final drape.
  <https://arxiv.org/abs/2606.29419>
- MV-Fashion records multilayer outfits, material properties, and styling such
  as rolled sleeves and tucked shirts, so layering and styling fidelity cannot
  be collapsed into silhouette alone.
  <https://arxiv.org/abs/2603.08147>
- Image2Garment predicts material composition, fabric attributes, and physical
  parameters, motivating a separate material-response axis.
  <https://arxiv.org/abs/2601.09658>

Evidence bindings follow the same tamper-evident principle as C2PA hard
bindings: a declared artifact is not accepted until its cryptographic hash
matches the bytes that were reviewed.
<https://spec.c2pa.org/specifications/specifications/2.2/specs/C2PA_Specification.html>

## Contract

The canonical definition is `config/quality-spec.json`. Every assessment stores:

- metric name, operator, threshold, and observed value;
- target views and poses;
- review method and reviewer;
- evidence path, kind, and SHA-256;
- completion gate, defect code, and recommended return stage.

The ten axes are `topology`, `seam`, `fit`, `material-response`, `layering`,
`skinning`, `collision`, `silhouette`, `styling-fidelity`, and computed
`evidence-completeness`.

`visualAppearanceReview` is a separate direct-image gate. Automated checks can
support individual axes but can never set this gate to PASS. Required views and
poses must each be represented by a hash-verified render.

## Release and Review Console projection

`tools/release_orchestrator.py` evaluates the assessment embedded at
`visual-review.qualitySpec` and writes the normalized result into
`customer-quality.json` under `evidence.qualitySpec`. The Review Console reads
that normalized projection rather than implementing separate thresholds.

A failed axis expands to a defect with a stable code and one canonical pipeline
return stage. An allowed `OUT_OF_SCOPE` result is listed separately and is not
counted as a failure. Missing evidence, path traversal, unsupported image
formats, and SHA-256 mismatch force both the affected axis and
`evidence-completeness` to FAIL.
