# Blue Happi for SiroinoSotai_PC

Product ID: `siroino-blue-happi`  
State: **WORKING**  
Target: **SiroinoSotai_PC**

## Reference boundary

The private reference is represented only by
`private-reference://sha256/9fc40516ae446274dc869cd695ea217fb741089d26dda43d685bba2d82da0423` and audited observations.
The original image is not stored or redistributed in this public product directory.

## Construction

The implementation keeps the garment as explicit, separately auditable panels:

- one back body
- left and right open-front body panels
- left and right loose straight sleeves
- left and right front collar bands plus a back-neck bridge
- finished front edges, cuffs, and hem

The generator must preserve an open front, a continuous collar route, underarm ease,
and no more than four deform-bone influences per vertex.

## Canonical execution

The request at `config/pipeline/requests/siroino-blue-happi.json` executes the standard
13 stages. The product-specific adapter only replaces the privacy-preserving
normalization and initial-placement logic; common build, simulation, export,
render, geometry audit, visual review, and finalization contracts remain in use.

The pipeline is expected to stop after `audit-geometry` until the generated images
are opened directly. Only then may
`config/products/siroino-blue-happi/visual-review.json` be created with a PASS or FAIL
decision. The provided `visual-review.template.json` is not completion evidence.

## Declared outputs

- Blender source: `Assets/GenWorks/siroino-blue-happi/Source/Blender/SiroinoBlueHappi.blend`
- FBX: `Assets/GenWorks/siroino-blue-happi/Models/SiroinoBlueHappi.fbx`
- outfit Prefab declaration: `Assets/GenWorks/siroino-blue-happi/Prefab/SiroinoBlueHappi.prefab`
- integrated Prefab declaration: `Assets/GenWorks/siroino-blue-happi/Prefab/SiroinoSotai_BlueHappi.prefab`
- five-view evidence: `Assets/GenWorks/siroino-blue-happi/Previews/`
- six-pose evidence: `Assets/GenWorks/siroino-blue-happi/Previews/Poses/`
- ten-axis audit: `Assets/GenWorks/siroino-blue-happi/Evidence/Build/quality-audit.json`

Unity import, Modular Avatar, NDMF, VRChat Build & Test, and VRChat runtime are
`OUT_OF_SCOPE` unless separate evidence is recorded.
