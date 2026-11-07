# OSS 3D garment manufacturing comparison — Lily Vapor Yukata

## Scope and comparison structure

This report normalizes the candidate set to seven entries and separates two
different production problems:

1. **Mesh generation benchmark**: image-to-shape or image-to-textured-mesh
   systems that return a surface/mesh.
2. **Garment manufacturing benchmark**: systems that return editable garment
   construction data such as panels, seams, stitches, and cloth-ready pieces.

The seven candidates are TripoSG, Pixal3D, TRELLIS.2, Hunyuan3D-2.1,
Hunyuan3D-2mv, Step1X-3D, and PatternGSL. PatternGSL remains in the candidate
set, but it is not ranked on the same mesh-quality axis as the other six.

Reference inputs are the existing Lily Vapor Yukata set in
`Assets/GenWorks/siroino-lily-vapor-yukata/Previews/`.

- Front-view SHA-256: `487b6fcf485440aa0a24ceda2961d87ec1949b25aa2a65c3b8efade6fcc4cfa7`
- Four-view set: `front`, `left`, `right`, `back`, all 1024×1024 PNGs
- Host: NVIDIA GeForce RTX 3060, 12 GiB VRAM, driver 610.47
- Blender inspection: 4.2.23 LTS

The conditioning is not identical: TripoSG and Hunyuan3D-2.1 Shape use the
front image; Hunyuan3D-2mv and Pixal3D use the four-view set. TRELLIS.2 and
Step1X-3D were stopped at compatibility gates. PatternGSL has no official
same-input Lily inference result in this workspace.

## Mesh generation benchmark

| Candidate | Lily status | Artifact / observed evidence | Production interpretation |
|---|---|---|---|
| **TripoSG** | **Completed front-view run** | `LightBaselines/TripoSG/runs/front/triposg-front.glb`; 109,551 vertices, 219,318 faces; watertight; 0 boundary edges; 0 non-manifold edges; 26 connected shells; no UV/material | Best front-facing garment-feature reference among completed mesh runs: obi, sleeve strips, and long hanging elements are recognizable. Body/feet, detached-looking parts, and simplified back remain; not Unity/VRChat-ready |
| **Pixal3D** | Four-view GLB exported; topology and visual review failed | 714,696 vertices, 971,772 faces, UV + PBRMaterial; 37,338 components, 432,830 boundary edges, 2 non-manifold edges; six Blender views show floating slabs and mesh islands | Best completed UV/PBR starting point in this benchmark, but the fragmented raw output needs remeshing and garment/body separation before production use |
| **TRELLIS.2** | Blocked before inference | No output; the published official gate is 24 GiB-class VRAM | Not rankable on this 12 GiB host |
| **Hunyuan3D-2.1** | **Completed Shape; Paint not run** | `Hunyuan3D/runs/2_1_shape_retry_3/lily_vapor_yukata_2_1_shape.glb`; 279,395 vertices, 558,978 faces; watertight; 0 non-manifold edges; 8 degenerate faces; 3 connected components; no UV/material | Cleanest topology metrics among completed shape runs, but the visual result is still a simplified shape blockout with planar/background slab artifacts and no garment materials |
| **Hunyuan3D-2mv** | **Completed four-view Shape** | `Hunyuan3D/runs/2mv/lily_vapor_yukata_2mv_shape.glb`; 1,078,343 vertices, 2,156,692 faces; 6 non-manifold edges; 13 degenerate faces; 11 connected components; no UV/material | Strongest completed option for backside conditioning. It captures a broad back panel, but needs major artifact cleanup and retopology |
| **Step1X-3D** | Blocked before inference | No output; official geometry+texture path is 27 GiB, label geometry+texture path is 29 GiB | Not rankable on this 12 GiB host |

### Mesh-only reading of the completed results

For this Lily sample, the completed mesh results have different strengths rather
than a single universal winner:

1. **Front garment-feature readability:** TripoSG.
2. **Shape topology and watertightness:** Hunyuan3D-2.1 Shape.
3. **Multi-view/backside coverage:** Hunyuan3D-2mv.
4. **UV/PBR export:** Pixal3D, with severe fragmentation and boundary-edge defects.

These are observed local results, not a claim that the order generalizes to all
subjects. None is a deliverable outfit without body/garment separation,
retopology, UVs, materials, rigging or cloth setup, and pose review.

## Garment manufacturing benchmark

| Candidate / baseline | Lily status | Editable manufacturing evidence | Correct interpretation |
|---|---|---|---|
| **PatternGSL** | No official same-input Lily run | The local `patterngsl-autosew-cloth-trial.json` is explicitly PatternGSL-inspired, not external PatternGSL code: 5 logical panels and a 32-frame Blender Cloth checkpoint; `externalResearchCodeExecuted: false` | PatternGSL belongs on the manufacturing-representation track because its target is panels/seams/stitches and cloth construction, not ordinary surface-mesh quality. The official repository exists, but a runnable same-input inference pipeline is not yet available in the published repository, so Lily cannot yet be evaluated as an official PatternGSL run |
| **image2outfit baseline** | Existing product construction baseline | 21 mesh objects; 31,279 vertices; 60,796 triangles; editable Blender/FBX/prefab outputs; explicit panel layout; textures; cloth-simulation evidence | The only entry here that already follows the intended product handoff. Appearance review remains `REVIEW_REQUIRED`; it is a manufacturing baseline, not an OSS model result |

## Practical OSS combinations

The evidence supports a staged candidate stack, but not an automatic handoff
between these tools:

| Combination | Evidence from this workspace | Use now |
|---|---|---|
| **Pinned GarmentCode/PyGarment boundary exchange → strict edge-stitch mapping → local audits** | Glasshouse v10 on PyGarment 2.0.2: all 29 canonical panel boundaries pass through the adapter and upstream preview with 0 vertex deviation; all 35 stitch references are preserved; no 3D is generated. The product audits report zero planar geometry defects, 35/35 edge-length pairs within tolerance, 33 declared direction checks, six graph components, and 0 unstitched panels. Role audit: `.image2outfit/products/siroino-glasshouse-rain-cape-set/garmentcode-stage-role-audit.json`. | Production use for strict 2D panel/stitch exchange, preview generation, self-intersection rejection, and seam-reference/orientation checks. The upstream run does not synthesize new panel boundaries from avatar measurements; geometry remains authored in `pattern-draft.json`. This replaces manual conversion/preview and seam-mapping checks, not pattern authoring, physical sewing, fit, or appearance review. | Keep PyGarment as the interoperability and validation stage. Benchmark a separate measurement-driven pattern generator before calling the geometry-authoring phase automated. |
| **GarmentCode `pattern_fitter` → parametric 2D pattern** | Pinned GarmentCode/PyGarment 2.0.2 commit `d449629979028123a5c4dc9e732a2ec19b7fce31`: generic `mean_female` controls generated a T-shirt pattern and a composed sleeveless `Shirt + Skirt2 + StraightWB` pattern; the composed run has 8 panels, 16 explicit stitch pairs, specification/SVG/PNG, and no 3D. Glasshouse compatibility remains partial: only five of ten decomposed parts have partial base-program candidates, five have no matching class, and the read-only Siroino coverage audit found 0 exact matches, 9 unaccepted candidates (height, waist, arm_pose_angle, wrist, shoulder_w, shoulder_incl, neck_w, back_width, and hip_inclination), 17 unmapped fields, and 0 accepted values. The arm-pose candidate is a 0.0003° mean upper-arm rest-bone tilt against GarmentCode's 0° T-pose / 40° A40 examples, but axis/sign equivalence is unresolved, so it remains unaccepted. The arm_length audit keeps that field unmapped: sample values range from 51.594 to 80 cm, the sleeve source uses the value as a length scale without defining measurement endpoints, and the Siroino direct-parent rest-bone chain has 9.6 cm and 9.3 cm transition gaps. The wrist candidate is 9.6854 cm on each side; a separate BMesh plane-bisect agrees within 0.0001 cm, but neighboring slices include irregular/open components and GarmentCode gives no anatomical section-plane rule. Simple stature-scaled references are 10.57–11.41 cm and are context only. The shoulder_w candidate is 17.9448 cm from surface projections of Shoulder bone tails, which sit about 2.52 cm from the skin. GarmentCode describes true shoulder width but gives no anatomical endpoints; proportional reference context is 23.13–25.50 cm, so the candidate remains unaccepted. For shoulder_incl, projected neck-base/shoulder surface lines give 17.417°, while rest-bone centerlines give 11.2°; GarmentCode applies the angle as a slope using tan(degrees) but does not define anatomical endpoints, so it remains unaccepted. For armscye_depth, GarmentCode defines nape-to-back-armscye depth, adds 2.5 cm ease and uses the result as a minimum sleeve connecting width. The shaped Siroino FBX has no explicit axilla, underarm, posterior-armscye or nape vertex group/bone; the nearest upper-arm joint projection is 2.8147 cm below the neck projection bilaterally but is not the posterior armhole endpoint, so the field remains unmapped. For neck_w, GarmentCode uses a lateral collar-width lower bound and left/right X anchors; inspected example values range from 15.0 to 20.3361 cm. Glasshouse-profile Siroino BMesh cuts yield lateral spans of 9.9758 cm at 25% and 4.0342–4.1764 cm at 50–100% of Neck-bone length. The root cut spans 76.4685 cm because it remains connected to the shoulders and T-pose arms. Since no measurement height is specified, these remain unaccepted candidates. For back_width, BodiceBackHalf uses half of the value and BodiceFrontHalf takes half of the remaining bust circumference, supporting a posterior-arc interpretation. At GarmentCode-derived bust-height fractions 0.709–0.719, the shaped Siroino mesh gives posterior arcs of 21.7288–22.3569 cm and posterior/total ratios of 0.509496–0.511364, overlapping the example ratios 0.473938–0.52. The body-bone-tail plane at fraction 0.849433 instead gives 0.362023, so the measurement line matters; height transfer and endpoint protocol remain unverified, and back_width stays unaccepted. For hip_back_width, GarmentCode uses posterior/anterior hip-circumference shares in pants, with sample ratios 0.514019–0.534905. Mapping the six sample hip-level fractions to Siroino stature (0.495056–0.512633) produces two closed leg contours at every plane; no unique pelvis contour or posterior arc is supported, so the field remains unmapped. For hip_inclination, GarmentMeasurements defines the angle from its hips_side_right-to-waist_side_right landmark vector relative to an X-normal plane. Pinned GarmentCode halves that angle, then uses tan(half-angle) × hip depth for a pants/fitted-skirt side-seam shift, capped by the hip-to-waist circumference difference; sample values are 4.0–12.6783°. Siroino has no bound equivalent surface landmarks. Hips-to-UpperLeg bone proxies are ±48.6445°, with endpoints 0.041057–0.051767 m from the surface, so they are not comparable and remain unmapped. A read-only Blender 4.4.3 BMesh transfer experiment selected a candidate waist section at stature fraction 0.742: convex-hull perimeter 39.5772 cm versus the existing 360-ray estimate 39.7183 cm at the identical z=0.856912 m plane (difference 0.1411 cm, 0.3553%). The hip initialization used the first single-contour transition from the prior coarse profile, not GarmentMeasurements' registered topology selection; it yielded a 79.141 cm contour and a rightmost-hull proxy angle of -20.6208°. The source landmark IDs belong to the 23,752-vertex mean.obj and cannot transfer by index to the 8,421-vertex Siroino mesh. Y-up to Z-up conversion, uniform stature scaling, bounding-center translation, and nearest-surface projection produce a provisional right hip/waist angle of 9.2028° with four surface distances of 0.006012-0.011250 m. The interpolated rig weights expose semantic mismatch: the projected hips_side_left/right points are 0.958 weighted to UpperLeg_L/R, while waist_side_left/right are 0.976/0.980 weighted to Hips and 0 to Spine. The projection is geometrically close but places both landmarks in adjacent deformation regions, so it remains unaccepted. A target-section height remap to the selected Siroino BMesh cuts moves the right-pair candidate from 9.2028° to 13.5896° and increases maximum surface distance from 1.125 cm to 2.803 cm; target-side contour proxies remain 2.251-6.915 cm from projected points, so this remap also remains exploratory. Same-depth lateral raycasts at those section heights then hit all four single-loop cuts with zero plane residual; signed left/right candidates were -14.3011° and +15.0393° (0.7382° absolute spread), and hit points were 0.189-3.148 cm from the remapped guesses. This verifies bilateral surface intersection only; semantic labels and angle sign remain unbound. The independent ±0.01 m hip/waist offset grid tested 25 combinations: all raycasts hit, but only 15 kept single-loop sections because hip cuts at -10 mm and -5 mm split into two loops. On the 15 single-loop combinations, absolute left/right candidates ranged 13.4949-14.3964° / 14.1991-15.1345°, with 0.6873-0.8047° bilateral spread; lower offsets cross a topology boundary and remain ambiguous. At both split hip cuts, per-contour ray intersections matched distinct BMesh loops within 0.1 mm; each loop had 48 or 54 section vertices, and positive/negative world-X hits carried dominant UpperLeg_L/UpperLeg_R weights of 0.888-0.902 / 0.886-0.900. This identifies the loops as separate leg deformation regions, but it still does not establish that the generic template's named hip landmark corresponds to these Siroino points. Directly computing the pinned GarmentMeasurements mean.obj landmark vector gives signed left/right values of -9.0892°/+9.9588°; this is closest to GarmentCode mean_all_tpose at 9.8649°, while the mean_female parameter is 12.6783° (2.7195° away). At the pinned revisions, GarmentCode’s body README links its non-SMPL model to GarmentMeasurements, and mean.obj and mean_female.obj have the same ordered face-index topology (23,752 vertices; 47,500 faces; topology SHA-256 736ecae2772e73bf8e56ca210e1e515ca5b140e4305196e0b2d4e7a84ea5860d). Their vertex coordinates differ (RMS 4.3029 cm; maximum component delta 16.6416 cm). The mean_female YAML height agrees with its OBJ height within 0.00000012 m. These sources establish shared model lineage and index topology, but distinct geometry instances; they do not map any landmark onto Siroino. An alternate axis-specific fit to full-body bounds yields 13.9459° (4.7432° change) and 0.031299-0.041260 m projection distances; pose-dependent body extents make this transform exploratory as well. The BMesh waist perimeter still agrees with the 360-ray check within 0.1411 cm (0.3553%) at the same plane. Coverage remains 0 accepted, 9 unaccepted candidates, 17 unmapped, and unsafe for pattern fitting. Angle sign and anatomical point identity remain unverified; the earlier -20.6208° contour-only estimate is not used by coverage. The inspected repository is GPL-3.0; its mean mesh and landmark table were read as reference data, without copying source code or running its measurement executable. See the [GarmentCodeData measurement supplement](https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/07721-supp.pdf) and [inspected GarmentMeasurements revision](https://github.com/mbotsch/GarmentMeasurements/tree/04e9197c37197c5b05c1c86abf5ac503864e0d8f). Evidence: `.image2outfit/products/siroino-glasshouse-rain-cape-set/garmentcode-parametric-pattern-trial.json`, `.image2outfit/products/siroino-glasshouse-rain-cape-set/garmentcode-measurement-coverage.json`, `.image2outfit/products/siroino-glasshouse-rain-cape-set/garmentcode-arm-length-audit.json`, `.image2outfit/products/siroino-glasshouse-rain-cape-set/garmentcode-wrist-section-audit.json`, `.image2outfit/products/siroino-glasshouse-rain-cape-set/garmentcode-shoulder-width-audit.json`, `.image2outfit/products/siroino-glasshouse-rain-cape-set/garmentcode-shoulder-inclination-audit.json`, and `.image2outfit/products/siroino-glasshouse-rain-cape-set/garmentcode-neck-width-audit.json`, `.image2outfit/products/siroino-glasshouse-rain-cape-set/garmentcode-back-width-audit.json`. | GarmentCode can replace manual drafting for designs represented by its parametric programs when accepted body measurements exist. The composed control does not establish Glasshouse construction or Siroino fit; no current product component is an exact match. | Candidate for compatible products. Glasshouse requires a reviewed measurement adapter and custom/hybrid programs for the cape, wrap overlap, closures, pouch, and binding before substitution.
| **GarmentCode/PyGarment → seam and pattern audits → BalsaNest marker trial** | Glasshouse v10 real data on BalsaNest `90ae59f3061701c9cf5aab8f037fb5cfb9d84df8`: 10 partId layouts and a second run joined by the decomposition material hypotheses (6 layouts); both placed all 29 cut units using the same provisional 1.5 m roll, 10 mm margin, and 5 mm spacing. Grouping reduced candidate roll length versus summing separate partId layouts by 52.34% for the pale-sage shell group (4 partIds) and 49.94% for the warm-cream group (2 partIds). The independent SVG audit verified all 29 paths, 1:1 scale, margins, and 92 within-group spacing pairs; maximum Hausdorff deviation was 2.18e-6 px. Evidence: `.image2outfit/products/siroino-glasshouse-rain-cape-set/balsanest-marker-trial/balsanest-marker-trial.json` and its ten layout summaries. | Feasibility only. The pattern has no explicit material ID; the grouped run joined decomposition material hypotheses through partId. These remain hypotheses, the belt textile recipe is missing, and the mixed placket remains separate. Seam allowance, physical grain, roll width, and material are unreviewed; candidate length reductions are not a yardage estimate. BalsaNest is GPL-3.0; license compatibility needs review. | Candidate for a future marker step after material/grain/stock fields become canonical. There is no current marker operation to replace. Do not use these outputs as cutting or customer-release evidence. [BalsaNest upstream](https://github.com/RU-Airborne/BalsaNest) |
| **OpenSew-2 Blender add-on** | Isolated author sample completed on Blender 5.2.2: trousers (6 pieces / 12 seams), tank top (2 / 4), and jacket (5 / 11). Cloth cache point-count warnings appeared for all three garments; direct image review found shoulder/chest bunching and overlap. On pinned Blender 4.4.3, add-on registration passes but the bundled `default_character.blend` cannot be read. Evidence: `OpenSew2/report.json`, render, and run logs. Upstream says Blender 5.2 only, one-way layered collision, no darts/pleats/seam allowance; GPL-3.0-or-later. [Upstream](https://github.com/MarcelloMorettoni/opensew-2) | Research-only. The sample works on an unpinned newer Blender but has cache and appearance defects, so it is not a production replacement. Keep the project's 4.4.3 pin and current visual gate unchanged; revisit after a deliberate version decision, clean cache/appearance results, and license review. |
| **Pixal3D multi-view → Blender cleanup** | Lily four-view run exports UV + PBR, but has 37,338 components and 432,830 boundary edges | Textured blockout candidate; test cleanup and garment/body separation on an isolated benchmark copy |
| **TripoSG single-view → Blender Siroino rig / FBX** | FBX readback: 60 deform bones, 62,058 weighted vertices, one armature modifier; 0 unweighted or non-normalized vertices. A 10° Hips rotation moved the evaluated mesh after readback | Reusable skeleton/weight/export stage; garment/body separation and Unity/VRChat runtime remain unverified |
| **GarmentCode → Pixal3D → Blender** | No joint run or direct seam-to-mesh binding exists; current evidence comes from separate pattern and image-mesh runs | Next stack to prototype after a product passes its visual gate; not a canonical production replacement yet |

For commercial packaging, the pinned GarmentCode source and Pixal3D source
carry MIT licenses, while Pixal3D's NOTICE assigns separate terms to bundled
third-party components. Hunyuan3D-2.1 uses Tencent's Community License, which
limits use and distribution to its defined territory and includes copy/notice
conditions for third-party distribution. Resolve the license for the exact
code, checkpoint, and dependencies before selecting a release stack.
Sources: [GarmentCode license](https://github.com/maria-korostoleva/GarmentCode/blob/d449629979028123a5c4dc9e732a2ec19b7fce31/LICENSE), [Pixal3D license](https://github.com/TencentARC/Pixal3D/blob/f7cf38429b0bd264f1995f0f8743a88b1c728b94/LICENSE), [Pixal3D third-party notices](https://github.com/TencentARC/Pixal3D/blob/f7cf38429b0bd264f1995f0f8743a88b1c728b94/NOTICE), [Hunyuan3D-2.1 license](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/blob/main/LICENSE).

PatternGSL therefore should not be assigned a numeric position inside the mesh
ranking. Its relevant metrics are panel recoverability, seam/stitch
recoverability, body/garment separability, editable manufacturing
representation, and cloth readiness.

## Manufacturing-oriented metrics

The next comparison pass should record these fields for every candidate. A
blocked or unexecuted field stays `unavailable`; it must not be inferred from a
paper score or from another candidate's run.

- Garment Appearance Fidelity
- Geometry Quality
- Backside Recovery
- Panel Recoverability
- Seam/Stitch Recoverability
- UV/Material Readiness
- Body/Garment Separability
- Retopology Cost
- Rigging/Cloth Readiness
- Unity/VRChat Handoff
- Editable Manufacturing Representation

The current evidence already supports the following qualitative observations:

| Metric group | Current evidence |
|---|---|
| Appearance / front detail | TripoSG preserves the most readable Lily front garment cues among completed mesh runs |
| Geometry quality | Hunyuan3D-2.1 Shape is watertight with no non-manifold edges in the inspected output; its visual slab artifacts still matter |
| Backside recovery | Hunyuan3D-2mv is the only completed mesh run conditioned on four views and provides a continuous backside panel |
| UV/material readiness | Pixal3D exported UVs and a PBR material; its inspected surface is severely fragmented. TripoSG and Hunyuan outputs in the completed benchmark have no UV/materials/textures |
| Panel/seam editability | Only the local image2outfit baseline has product-side editable construction evidence; the PatternGSL-inspired trial is not an official Lily inference |
| Unity/VRChat handoff | No completed OSS mesh has passed the outfit handoff; the image2outfit baseline has the required artifact classes but still needs appearance review |

## Hardware and compatibility boundary

- **TRELLIS.2**: the official environment gate is 24 GiB-class VRAM; the
  RTX 3060 run was stopped before inference.
- **Step1X-3D**: the official full geometry+texture paths are 27 GiB and
  29 GiB; the run was stopped before inference.
- **Hunyuan3D-2.1**: Shape completed on this 12 GiB host with the isolated
  low-memory run path; Paint was not run because its approximately 21 GiB
  requirement exceeds the device, and the full shape+texture path is outside
  this host's practical budget.
- **Pixal3D**: an early low-VRAM run failed on NAF/NATTEN/CUDA compatibility.
  A later four-view run completed with a benchmark-local attention path and
  exported a UV/PBR GLB at texture-conditioning 512; topology inspection then
  found severe fragmentation. Do not classify it as impossible on 12 GiB, or
  treat its raw mesh as production-ready.
- **TripoSG**: the official runtime is in the 8 GiB-class range, so the
  completed RTX 3060 run is a valid local result.

## Evidence paths

- GarmentCode/PyGarment role and boundary round-trip audit: `.image2outfit/products/siroino-glasshouse-rain-cape-set/garmentcode-stage-role-audit.json`
- GarmentCode parametric fitter control and Glasshouse compatibility audit: `.image2outfit/products/siroino-glasshouse-rain-cape-set/garmentcode-parametric-pattern-trial.json`
- GarmentCode measurement-coverage adapter report: `.image2outfit/products/siroino-glasshouse-rain-cape-set/garmentcode-measurement-coverage.json`
- GarmentCode arm-length endpoint semantics audit: `.image2outfit/products/siroino-glasshouse-rain-cape-set/garmentcode-arm-length-audit.json`
- GarmentCode wrist cross-section and independent BMesh check: `.image2outfit/products/siroino-glasshouse-rain-cape-set/garmentcode-wrist-section-audit.json`
- GarmentCode shoulder-width landmark audit: `.image2outfit/products/siroino-glasshouse-rain-cape-set/garmentcode-shoulder-width-audit.json`
- GarmentCode shoulder-inclination landmark audit: `.image2outfit/products/siroino-glasshouse-rain-cape-set/garmentcode-shoulder-inclination-audit.json`
- GarmentCode armscye-depth endpoint audit: `.image2outfit/products/siroino-glasshouse-rain-cape-set/garmentcode-armscye-depth-audit.json`
- GarmentCode neck-width surface-section audit: `.image2outfit/products/siroino-glasshouse-rain-cape-set/garmentcode-neck-width-audit.json`
- GarmentCode hip-inclination landmark and side-seam audit: `.image2outfit/products/siroino-glasshouse-rain-cape-set/garmentcode-hip-inclination-audit.json`
- GarmentCode hip-back-width surface-section audit: `.image2outfit/products/siroino-glasshouse-rain-cape-set/garmentcode-hip-back-width-audit.json`
- GarmentCode back-width posterior-arc audit: `.image2outfit/products/siroino-glasshouse-rain-cape-set/garmentcode-back-width-audit.json`
- GarmentCode read-only Siroino rig/surface alignment report: `.image2outfit/products/siroino-glasshouse-rain-cape-set/stages/garmentcode-landmark-alignment.json`
- BalsaNest Glasshouse feasibility report: `.image2outfit/products/siroino-glasshouse-rain-cape-set/balsanest-marker-trial/balsanest-marker-trial.json`
- BalsaNest independent output geometry audit: `.image2outfit/products/siroino-glasshouse-rain-cape-set/balsanest-marker-trial/balsanest-marker-geometry-audit.json`
- BalsaNest material-hypothesis grouping run: `.image2outfit/products/siroino-glasshouse-rain-cape-set/balsanest-material-group-trial/balsanest-material-group-trial.json`
- BalsaNest material-grouping comparison: `.image2outfit/products/siroino-glasshouse-rain-cape-set/balsanest-material-group-comparison.json`
- BalsaNest grouped-output geometry audit: `.image2outfit/products/siroino-glasshouse-rain-cape-set/balsanest-material-group-trial/balsanest-material-group-geometry-audit.json`
- BalsaNest per-partId trial layouts and summaries: `.image2outfit/products/siroino-glasshouse-rain-cape-set/balsanest-marker-trial/`
- Hunyuan3D-2.1 run metadata: `Hunyuan3D/runs/2_1_shape_retry_3/run.json`
- Hunyuan3D-2.1 mesh inspection: `Hunyuan3D/runs/2_1_shape_retry_3/mesh_inspection.json`
- Hunyuan3D-2.1 Blender views: `Hunyuan3D/runs/2_1_shape_retry_3/blender_handoff/views/`
- Hunyuan3D-2mv report: `Hunyuan3D/reports/hunyuan3d_oss_benchmark.md`
- TripoSG report: `LightBaselines/benchmark-report.md`
- Pixal3D report: `Pixal3D/report.md`
- TRELLIS.2 report: `TRELLIS2/REPORT.md`
- Step1X-3D report: `Step1X-3D/compatibility-report.md`
- PatternGSL-inspired trial: `Assets/GenWorks/siroino-nocturne-angel-set/Research/patterngsl-autosew-cloth-trial.json`
- Lily product baseline: `Assets/GenWorks/siroino-lily-vapor-yukata/ProductManifest.json`

## 3/4 screenshots

All generated mesh outputs and the product baseline now have a front-right
3/4 screenshot at 640×640. The OSS mesh renders use the neutral benchmark
material; the image2outfit baseline render keeps its product materials.

- TripoSG: `LightBaselines/TripoSG/runs/front/blender_handoff/views/three_quarter.png`
- Hunyuan3D-2.1 Shape: `Hunyuan3D/runs/2_1_shape_retry_3/blender_handoff/views/three_quarter.png`
- Hunyuan3D-2mv Shape: `Hunyuan3D/runs/2mv/blender_handoff/views/three_quarter.png`
- image2outfit baseline: `LightBaselines/image2outfit-baseline-three-quarter.png`

## Reproducibility pins

The following pins describe the actual local runs. A candidate stopped before
source/checkpoint acquisition is marked as unavailable rather than being
assigned a later repository HEAD.

| Candidate | Repository / branch | Source commit | Model checkpoint or revision |
|---|---|---|---|
| TripoSG | `VAST-AI-Research/TripoSG`, `main` | `fc5c40990181e2a756c4e0b1c2f4d6b5202faf8c` | `VAST-AI/TripoSG`; RMBG `briaai/RMBG-1.4` |
| Pixal3D | `TencentARC/Pixal3D`, `master` | `f7cf38429b0bd264f1995f0f8743a88b1c728b94` | Pixal3D model revision `b0cb2e1b794cab9aa0ac38a95d794a4d9337437f`; DINOv3 revision `3c276edd87d6f6e569ff0c4400e086807d0f3881` |
| TRELLIS.2 | `microsoft/TRELLIS.2`, `main` | Reference HEAD `75fbf0183001ed9876c8dbb35de6b68552ee08bd` checked 2026-09-22; not acquired for the run | `microsoft/TRELLIS.2-4B`; not downloaded |
| Hunyuan3D-2.1 | `Tencent-Hunyuan/Hunyuan3D-2.1`, `main` | `82920d643c0dc2f7bfd7255f45f62d386edfe60c` | `tencent/Hunyuan3D-2.1`, subfolder `hunyuan3d-dit-v2-1`; checkpoint SHA-256 `6b519fc7242f78e9b5f47ea4d55668fe3d944a2d27332f4ca68d29a6ff603f5e` |
| Hunyuan3D-2mv | `Tencent-Hunyuan/Hunyuan3D-2`, `main` | `f8db63096c8282cb27354314d896feba5ba6ff8a` | `tencent/Hunyuan3D-2mv`, subfolder `hunyuan3d-dit-v2-mv`; checkpoint SHA-256 `d36f5881bcdc56726b73e517cd444c13c60732431622da7268145355c8d38e9c` |
| Step1X-3D | `stepfun-ai/Step1X-3D`, `main` | Reference HEAD `cb5ac944709c6c913109070c7b90c3447f57f3d4` checked 2026-09-22; not acquired for the run | `stepfun-ai/Step1X-3D` subfolders `Step1X-3D-Geometry-1300m`, `Step1X-3D-Geometry-Label-1300m`, and `Step1X-3D-Texture`; not downloaded |
| PatternGSL | `Lagrangeli/PatternGSL`, `master` | Repository inspection HEAD `8348a844e9d6353923332c58f7aaa8cf02811523` checked 2026-09-22; no official local checkout used | No public checkpoint/inference run recorded |

The TRELLIS.2, Step1X-3D, and PatternGSL SHAs above are source-reference
pins, not successful inference pins: the first two were stopped before source
or checkpoint acquisition, and PatternGSL has no official same-input run.

Official repository references:

- Pixal3D: https://github.com/TencentARC/Pixal3D
- Hunyuan3D-2.1: https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1
- Hunyuan3D-2mv: https://github.com/Tencent-Hunyuan/Hunyuan3D-2
- TRELLIS.2: https://github.com/microsoft/TRELLIS.2
- Step1X-3D: https://github.com/stepfun-ai/Step1X-3D
- TripoSG: https://github.com/VAST-AI-Research/TripoSG
- PatternGSL: https://github.com/Lagrangeli/PatternGSL

## Completion boundary

The candidate matrix is not a seven-way successful same-input manufacturing
bake. Four mesh candidates have completed local outputs (TripoSG,
Hunyuan3D-2.1 Shape, Hunyuan3D-2mv, and Pixal3D); TRELLIS.2 and Step1X-3D are
blocked by host compatibility or VRAM gates, and PatternGSL has no official
same-input Lily run. Pixal3D has UV/PBR evidence, but its topology fails a
production-quality reading.

The official PatternGSL repository exists, but a runnable same-input inference
pipeline is not yet available in the published repository, so Lily cannot yet
be evaluated as an official PatternGSL run.
