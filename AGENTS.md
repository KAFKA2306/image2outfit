# image2outfit Agent Contract

## Short-context start

Read this file, then only the canonical files for the current product/task. Do not preload all product folders, docs, Issues, PR history, renders, or research notes.

For a product task, identify only:

1. product slug
2. requested outcome
3. canonical contract owner
4. current manifest/evidence
5. next verifier and completion condition

Continue an existing workline/checkpoint when it already owns the same outcome. Do not rely on chat history for continuation.

## Canonical owners

Use existing owners; do not duplicate their rules in prose or new files.

- PR merge boundary: `config/pr-merge-policy.json`
- completion boundary: `config/genworks-handoff-policy.json`
- required views/poses/evidence and customer release: `config/release-policy.json`
- product identity/input/output: `config/products/<slug>/job.json`
- construction: `config/products/<slug>/construction.json`
- current state/gates/defects/hashes: `Assets/GenWorks/<slug>/ProductManifest.json`
- quality: `contracts/quality/quality-spec.json`
- merge-policy verification: `tools/pr_merge_gate.py`
- shared validation: `tools/production_contract.py`
- runtime directory transaction and canonical workspace last-good protection: `tools/runtime_transaction.py`
- commands: `Taskfile.yml` / `tools/manage.py`

`README.md` is the user entry point and `ARCHITECTURE.md` describes stable design relationships. Machine-readable owners outrank prose.

## Product workflow

Use the smallest existing command that owns the task:

```powershell
task explain PRODUCT=<slug>
task candidate PRODUCT=<slug>
task improve PRODUCT=<slug>
task release PRODUCT=<slug>
```

For repository-wide checks when needed:

```powershell
task audit:all
task check:python
```

Do not add a second command path when an existing Taskfile/manage entry point can own the behavior.

## Change rules

- one rule, one owner; generic defects belong in the generic layer.
- `DELETE > MERGE > REPLACE > ADD`; remove superseded paths only after current references prove them unused.
- keep `Assets/GenWorks/<slug>/` as the canonical product workspace; do not create alternate tracked product roots.
- keep local reports/candidates/releases under `.image2outfit/products/<slug>/...` and out of Git.
- do not weaken gates to fit failing data or overwrite last-good state with a worse candidate.
- do not commit credentials, private assets, caches, machine state, or unintended Unity `.meta`/GUID changes.
- comments should explain non-obvious rationale/external constraints, not narrate code.
- GitHub Pages が有効な間は、`README.md` の先頭行に `https://...` の正準公開URLを平文で置く。
- 公開製品状態は各 `ProductManifest.json` または既存の正準投影から読み、手書きの製品状態カタログを追加・復活させない。

## Evidence and completion

Generated files, hashes, inventory, CI success, and plausible prose are not visual acceptance evidence. Visual decisions require direct inspection of the current evidence owned by `contracts/quality/quality-spec.json` and `config/release-policy.json`.

Product completion and runtime scope are defined only by `config/genworks-handoff-policy.json`. Do not copy gate lists or scope rules into agent prose, and do not claim PASS without the evidence required by the owning policy.

## PR and continuation

Use one coherent PR workline and verify the exact head for the changed surface. Merge eligibility is owned by `config/pr-merge-policy.json` and `tools/pr_merge_gate.py`; product completion and customer release remain separate policy decisions.

If work stops, persist the current manifest/checkpoint, verified revision, failing stage/visible defect, blocker, and one exact next action in the existing canonical workline. Do not create a second agent-state database.
