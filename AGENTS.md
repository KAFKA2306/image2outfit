# image2outfit Agent Contract

## Start

For product work, identify the product slug and requested outcome, then read only the relevant canonical owners below plus the current `ProductManifest.json`. Do not preload unrelated product folders, docs, Issues, PR history, renders, or research notes.

Continue an existing checkpoint/workline when it already owns the same outcome.

## Canonical owners

- PR merge: `config/pr-merge-policy.json` and `tools/pr_merge_gate.py`
- completion/runtime scope: `config/genworks-handoff-policy.json`
- required visual evidence and customer release: `config/release-policy.json` and `contracts/quality/quality-spec.json`
- product identity/input/output: `config/products/<slug>/job.json`
- construction: `config/products/<slug>/construction.json`
- current state/gates/defects/hashes: `Assets/GenWorks/<slug>/ProductManifest.json`
- runtime transaction/last-good protection: `tools/runtime_transaction.py`
- commands: `Taskfile.yml` / `tools/manage.py`

`README.md` is the user entry point and `ARCHITECTURE.md` describes stable design relationships. Machine-readable owners outrank prose.

## Product commands

Use the existing command that owns the task:

```powershell
task explain PRODUCT=<slug>
task candidate PRODUCT=<slug>
task improve PRODUCT=<slug>
task release PRODUCT=<slug>
```

Repository-wide checks are `task audit:all` and `task check:python`. Do not add a second command path when the existing Taskfile/manage path owns the behavior.

## Product invariants

- Keep `Assets/GenWorks/<slug>/` as the canonical product workspace.
- Keep local reports/candidates/releases under `.image2outfit/products/<slug>/...` and out of Git.
- Do not weaken gates to fit failing data or overwrite last-good state with a worse candidate.
- Do not commit credentials, private assets, caches, machine state, or unintended Unity `.meta`/GUID changes.
- While GitHub Pages is enabled, keep the canonical public URL as plain text on the first line of `README.md`.
- Read public product state from each `ProductManifest.json` or its existing canonical projection; do not maintain a handwritten state catalog.

## Evidence

Generated files, hashes, inventory, CI success, and plausible prose are not visual acceptance evidence. Visual acceptance requires direct inspection of the current evidence required by `contracts/quality/quality-spec.json` and `config/release-policy.json`.

Merge eligibility, product completion, and customer release are separate decisions owned by their canonical policies.

## Continuation

If work stops, persist the current manifest/checkpoint, verified revision, failing stage or visible defect, blocker, and one exact next action in the existing canonical workline. Do not create a second agent-state database.

## Repository hygiene (mandatory)

- Keep exactly one local working branch and one worktree for this repository. Before ending any task that created a branch or worktree, merge or remove it.
- Leave zero unmanaged state: no uncommitted, untracked, or stashed work at the end of a task. Each change must end as one of: committed (after the secret/private-asset/cache check above), gitignored local output, or archived outside the repository (for example a `git bundle` or patch in the scratchpad), with the choice reported.
- Never delete a branch, worktree, or file that holds unique work until it is verified merged (`git merge-base --is-ancestor`) or backed up.
- When a new kind of local-only output appears, add its path to `.gitignore` in the same change.
- Finish by pushing the single branch and reporting `git status` as clean.
