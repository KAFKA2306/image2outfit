# Marvelous Designer backend

Issue: #518

This backend converts the existing repository-owned garment contracts into a replayable request for Marvelous Designer's official Python API. It does not create a second product schema, state database, completion authority, or release path.

## Ownership

- canonical inputs remain `config/products/<product>/job.json`, `pattern-draft.json`, `stitch-graph.json`, `construction.json`, and `material-recipe.json`
- repository-side conversion lives in `src/image2outfit/marvelous_designer.py`
- request preparation helper lives in `tools/prepare_marvelous_designer.py`
- the script that must run inside Marvelous Designer lives in `tools/marvelous_designer_execute.py`
- existing validators and ProductManifest remain the completion authority after export

`tools/prepare_marvelous_designer.py` only prepares a request artifact. It cannot mark a product complete. `tools/marvelous_designer_execute.py` only executes the external DCC boundary and records MD-local evidence. Neither replaces `tools/manage.py`, the canonical production gate, or the existing verifier.

## Flow

1. Read the canonical job and bound pattern, stitch, material, and optional Stage 06 initialization evidence.
2. Convert meters to Marvelous Designer millimeters and map each named canonical edge to explicit MD boundary line indices.
3. Reject ambiguous edges and seam pairs whose line segmentation cannot be mapped without guessing.
4. Record an immutable request hash and source hashes.
5. Inside Marvelous Designer, create the project/avatar/patterns, apply an explicit canonical arrangement, create sewing, construct/assign ZFAB materials, simulate, and export ZPRJ/OBJ/FBX.
6. Hash exported artifacts and write `execution-result.json`.
7. Return the exported mesh to the existing image2outfit verifier. MD execution success is not product PASS.

## Fail-closed rules

- no canonical Stage 06 placement: simulation remains `UNVERIFIED`
- no explicit `arrangementIndex`: do not guess a Marvelous Designer arrangement point
- ambiguous named pattern edge: reject the request
- unequal seam segmentation: reject until the canonical edge is explicitly subdivided
- missing required Base Color / Normal / Roughness textures for a bound material: stop before simulation
- no Marvelous Designer runtime: execution stays `UNVERIFIED`, never fabricated `PASS`

## Official API surface

The implementation is limited to documented functions from Marvelous Designer:

- `CreatePatternWithPoints`
- `SetPatternPieceName`
- `SetPatternPieceGrainDirection`
- `SetArrangement` / arrangement position and orientation setters
- `AddSeamlinePairGroup`
- `CreateZfabFromTextures`
- `AddFabric`
- `AssignFabricToPattern`
- `SetSimulationQuality`, `SetSimulationTimeStep`, `SetSimulationNumberOfSimulation`, `Simulate`
- `ExportZPrj`, `ExportOBJ`, `ExportFBX`

Primary references:

- https://developer.marvelousdesigner.com/list.html
- https://developer.marvelousdesigner.com/scenario.html
- https://developer.marvelousdesigner.com/python.html

## Current vertical slice

The first target is an existing Siroino garment, not a new SKU. Repository-side conversion and tests can run on normal Python. The final execution step requires a real Marvelous Designer runtime, so that stage must remain `UNVERIFIED` in environments where MD is not installed or connected.
