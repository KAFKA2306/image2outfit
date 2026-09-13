# Runner-only machine audit v1

Runner COMPLETE means completion that can be proven inside a GitHub-hosted Runner. Unity Editor, VRChat Client, local PCs, BOOTH publication, sales, third-party evaluation, and human visual approval are outside this completion boundary.

The canonical threshold profile is `contracts/quality/runner-only-machine-audit-v1.json`. A request is frozen before execution. Its threshold snapshot, fit bands, epsilon values, producer versions, references, target-avatar authority hash, views, poses, seed, Blender version, and budgets are part of the canonical JSON used to calculate the request SHA-256. Threshold changes require a new request revision.

Every required metric has exactly one of `PASS`, `FAIL`, or `UNVERIFIED`. Missing producer declarations, producer/version mismatches, missing evidence, hash mismatches, unmeasurable values, missing candidates, and undefined required evidence are `UNVERIFIED`. `UNVERIFIED` blocks Runner COMPLETE and is never converted to zero or PASS.

Evaluation order is fixed: reproducibility/evidence, geometry, seam/structure, fit/collision, pose robustness, silhouette fidelity, material fidelity. A failure or unverified metric in an earlier stage remains the blocker before lower stages are optimized.

Candidate adoption uses Pareto dominance after hard gates. A candidate must not regress any compared metric beyond its frozen tolerance and must improve at least one metric by its frozen minimum improvement. Equal candidates and improvements that cannot be proven are reverted.

The attempt ledger binds every attempt to the request hash and records blocker, patch ID, before/after candidate hashes, before/after audit hashes, elapsed time, and KEEP/REVERT. Three consecutive reverts set `earlyStopCandidate=true`; this is a diagnostic flag, not a terminal condition. Terminal reasons are only `SUCCESS`, `STALLED`, `BUDGET_EXHAUSTED`, and `FAILED_HARD`. There is no human-decision wait state.

Runner COMPLETE requires all required metrics PASS, verified evidence ratio 1.0, valid artifact identity, matching request and candidate hashes, and a final candidate that is not a reverted attempt. Direct image review may still be performed for customer/runtime review, but it does not block Runner COMPLETE.

Current implementation deliberately fails closed. Generic signed-distance fit, blocking collision, pose/skinning defect, silhouette IoU/Chamfer/landmark, material response, and layering producers are not yet general-purpose repository producers. A new request requiring one of those producers remains UNVERIFIED until a declared producer with a frozen version emits hash-verified evidence. This is intentional and prevents incomplete garments from becoming COMPLETE through missing measurements.

Operator entrypoints are `tools/manage.py runner ...`, `tools/runner_machine_audit.py`, and the `runner:*` Taskfile tasks. `audit-result.json` and `attempt-ledger.json` schemas live under `config/pipeline/`.
