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

## Merge readiness

実際に実行・確認したものだけ記載します。

- [ ] 変更に必要な repository / contract checks
- [ ] 変更に必要な build / render / artifact checks
- [ ] visual gate を変更・判定する場合、current artifact を直接確認
- [ ] exact head の required CI を確認

結果:

- 

## Product state / release

- product state: `N/A` / `WORKING` / `COMPLETE` / `REJECTED`
- remaining in-scope blockers:
  - 

`COMPLETE` を主張する場合は `config/genworks-handoff-policy.json` の required completion gates を満たした evidence を示します。

## Out of scope

現在の policy で `OUT_OF_SCOPE` の Unity / Modular Avatar / NDMF / VRChat runtime 検証は、今回明示的に scope へ追加した場合を除き、未完了 blocker として扱いません。外部 evidence がない項目を PASS とも表現しません。

## Merge

- [ ] merge 条件を満たした
- [ ] merge / close 後に不要 branch を削除する
- [ ] merge 後の `main` を readback する
