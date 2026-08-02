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

- mesh objects: 17
- vertices: 18056
- triangles: 35750
- material slots: 17
- exported shape keys: 255
- maximum bone influences: 4

## Research trial

The 2026 source is **Learning-based Seam Correspondence Reconstruction in Sewing Patterns**, submitted 2026-07-23. An independent deterministic ablation compares global edge-length pairing with semantic panel-graph filtering. The authors' model, code, dataset and weights are not used or redistributed. See `Research/seam-correspondence-graph-trial.json` for measured precision, recall and F1.

## Current review result

The v6 multiview and required-pose evidence was reviewed on 2026-08-03 and rejected for shoulder/underarm gaps, rigid waist fins, detached hood-back panels and intersections in every required pose. The files are preserved as a resumable `WORKING` checkpoint, not a completed outfit.

## Remaining gates

- rebuild the shoulder/underarm, waist transition and hood geometry
- import/save/reload both Prefabs in pinned Unity
- validate Modular Avatar/NDMF and VRChat Build & Test
- capture runtime evidence and complete human review

Until those gates pass, the product remains `WORKING`, not released.
