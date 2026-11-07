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

## Shape model

The reconstruction now models the visually important upholstery structure explicitly instead of relying on a generic inflated beanbag volume:

- broad, flattened seat depression
- low front rail and side walls
- asymmetric rear ridge with the left-rear peak dominant and the right side lower
- seat/back transition trough
- fan-shaped backrest folds
- front-panel seam cue and side-panel pinches
- restrained compression wrinkles around the front corners
- black PU/PVC-like PBR material with moderate roughness

The surface details are deterministic vertex displacements applied after SDF polygonization, so the same input resolution reproduces the same mesh.

## Current review state

Status is **WORKING**. The main silhouette, asymmetric back, flatter seat, seam cues, and broad folds are now represented. Remaining fidelity work is concentrated in fine upholstery behavior: exact seam routing, softer high-frequency creasing, and sitting-state bead/cover deformation.

`evidence/reference.json` is the machine-readable source/target record. This example does not claim garment lifecycle `COMPLETE` or `visualAppearanceReview: PASS`.
