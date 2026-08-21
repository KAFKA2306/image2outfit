<!-- workstream: product slug または repository scope -->
<!-- supersedes: #123 など、既存 workstream を置換する場合だけ記載 -->
<!-- branch prefix: agent/, fix/, feat/, work/, release/, ops/, chore/, ci/, dependabot/ -->

## Scope

- 目的:
- 主要変更:
- 変更しない範囲:

## Contract impact

- [ ] machine-readable policy / schema / product contract の変更有無を確認した
- [ ] rule を prose や別実装へ重複所有させていない
- [ ] product task の場合、既存 canonical checkpoint を継続している

影響する正本:

- 

## Validation

実際に実行・確認したものだけ記載します。

- [ ] 変更に必要な repository / contract checks
- [ ] 変更に必要な build / render / artifact checks
- [ ] visual gate を変更・判定する場合、current artifact を直接確認
- [ ] exact head の required CI を確認

結果:

- 

## Merge readiness

PR merge は repository integration の判定です。製品の `COMPLETE`、visual PASS、runtime PASS、release eligibility は merge の前提にしません。

- [ ] `config/pr-merge-policy.json` の merge 条件を満たした
- [ ] 影響製品がある場合、pipeline / build は有効な checkpoint boundary まで到達した
- [ ] product failure / `REJECTED` がある場合、隠さず state / evidence / blocker を記録した
- [ ] non-default branch はこの open PR の head としてのみ存在している
- [ ] merge / close 後に head branch が削除される
- [ ] merge 後の `main` を readback する

`main` 以外の branch は same-repository open PR の head である間だけ許可します。PR が merge / close された時点で head branch は削除し、open PR に紐づかない orphan branch は unique commit の有無に関係なく残しません。

## Product state / release

- product state: `N/A` / `WORKING` / `COMPLETE` / `REJECTED`
- release eligibility: `N/A` / `NOT_READY` / `READY`
- remaining product blockers:
  - 

`COMPLETE` を主張する場合は `config/genworks-handoff-policy.json`、customer release を実行する場合は `config/release-policy.json` と dedicated release validator の evidence を示します。PR merge 自体は release を実行しません。

## Out of scope

現在の policy で `OUT_OF_SCOPE` の Unity / Modular Avatar / NDMF / VRChat runtime 検証は、今回明示的に scope へ追加した場合を除き、未完了 blocker として扱いません。外部 evidence がない項目を PASS とも表現しません。
