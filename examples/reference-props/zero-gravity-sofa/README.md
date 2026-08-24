# 0-Gravity XXXL Sofa — black reference reconstruction

Static reference reconstruction of the black **「人を神にするソファ」 / 0-Gravity XXXL**.

## Target

- nominal size: **1120 × 1140 × 650 mm** (W × D × H)
- black cover reference: **PU/PVC synthetic leather**
- fill reference: **5 mm expanded beads**
- silhouette: low, deep single-seat beanbag sofa with an asymmetric raised back

Primary source facts:

- https://item.rakuten.co.jp/e-unit/chot-in/
- https://hinekurebou.crap.jp/?p=28337

## Generate

This example stays outside `config/products/` because the current product contract is avatar-garment specific. The geometry source is instead kept as a reproducible reference-prop example.

```powershell
uv sync --locked --group snapshot
uv run --group snapshot python examples/reference-props/zero-gravity-sofa/generate.py \
  --output .image2outfit/reference-props/zero-gravity-sofa/zero_gravity_sofa_black.glb
```

The generator uses only `numpy` and `trimesh`, both already owned by the repository snapshot dependency group. It creates one watertight static shell scaled to the nominal product dimensions.

## Current review state

Status is **WORKING**. The current geometry reproduces the main inflated volume and asymmetric raised back, but the source image is more slouched: its front cushion is flatter, the left-rear wedge is sharper, and upholstery seam/fold cues are stronger. Sitting-state bead and cover deformation is not simulated yet.

`evidence/reference.json` is the machine-readable source/target record. This example does not claim garment lifecycle `COMPLETE` or `visualAppearanceReview: PASS`.
