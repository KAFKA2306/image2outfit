# Review evidence contract

A candidate is never a release. `task candidate` can only end in `REVIEW_REQUIRED` or `NO-GO`.
`task release` returns `GO` only when all three human evidence files refer to the exact SHA-256 of the unchanged `candidate-manifest.json`.

## Common fields

Every evidence JSON must contain:

```json
{
  "schemaVersion": 2,
  "kind": "visual-review",
  "jobId": "pochi-shinano-knit-set",
  "adapterId": "pochi-v1.1.0",
  "candidateManifestSha256": "<sha256>",
  "status": "PASS",
  "checkedAt": "2026-07-30T00:00:00Z",
  "reviewer": "human:<name>"
}
```

## visual-review

Requires scores from 1 to 5 for `silhouette`, `fit`, `material`, and `presentation`.
Every score must be at least the policy minimum, currently 4, and `criticalDefects` must be 0.

## pose-penetration-review

Requires `PASS` for `neutral`, `arms-up`, `arm-cross`, `crouch`, `sit`, and `prone`.
`criticalPenetrations` must be 0.

## vrchat-runtime-review

Requires `vrchatBuildAndTest: "PASS"` and `testedInVRChat: true`.

Evidence is rejected when the candidate, job, build script, target avatar, license evidence, policy, or source commit changed after review.
