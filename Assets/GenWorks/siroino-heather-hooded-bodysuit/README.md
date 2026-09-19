# Heather Hooded High-Cut Bodysuit for Siroino

Target: `SiroinoSotai_PC` neutral official PC body.

This is a resumable `WORKING` checkpoint for a heather-grey hooded high-cut bodysuit. It contains editable Blender geometry, FBX, Unity handoff Prefabs, procedural PBR maps, actual Blender views, required pose renders and a 2026 seam-graph research trial.

## Authored structure

- separate front/back upper and sharply tapered high-cut lower panels
- continuous fitted shoulder-to-wrist sleeves and separate rib cuffs
- split left/right hood shell, rolled neck edge and central hood seam
- three-button Henley placket
- modeled drawcords and paired side ties
- separate visible center seams
- explicit UV pattern coordinates and fine seam-pair graph

## Static metrics

- mesh objects: 14
- vertices: 21762
- triangles: 43618
- material slots: 14
- exported shape keys: 210
- maximum bone influences: 4

## Research trial

The 2026 source is **Learning-based Seam Correspondence Reconstruction in Sewing Patterns**, submitted 2026-07-23. An independent deterministic ablation compares global edge-length pairing with semantic panel-graph filtering. The authors' model, code, dataset and weights are not used or redistributed. See `Research/seam-correspondence-graph-trial.json` for measured precision, recall and F1.

## Remaining gates

- inspect the exact five-view and required-pose renders for silhouette and penetration
- import/save/reload both Prefabs in pinned Unity
- validate Modular Avatar/NDMF and VRChat Build & Test
- capture runtime evidence and complete human review

Until those gates pass, the product remains `WORKING`, not released.
