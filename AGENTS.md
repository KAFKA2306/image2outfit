# AGENTS.md — AI coding agent 作業規約

このファイルは LLM-based coding agent の運用 contract です。利用者向け入口は `README.md`、設計責務は `ARCHITECTURE.md` を参照してください。

## 目的

現在の正準状態を確認し、最小の coherent diff で repository をより正確・再現可能・検証可能・再開可能にします。

生成物の存在、もっともらしい説明、CI 成功、画像 inventory だけを製品完成とは扱いません。製品状態は machine-readable contract と現在の artifact evidence に基づいて決定します。

## 優先順位

1. 現在の user request と acceptance criteria
2. executable schema / policy / test / gate
3. 現在の product job / construction / `ProductManifest.json`
4. `ARCHITECTURE.md` と本ファイル
5. `README.md` と product prose

低い優先順位の文書が正本と食い違う場合は、正本を採用し、同じ coherent change で文書を修正します。

## Contract owner

重複する正本を作らず、既存 owner を更新します。

- `config/genworks-handoff-policy.json`: completion boundary / scope
- `config/release-policy.json`: required view / pose / visual evidence
- `config/products/<slug>/job.json`: product identity / input / output
- `config/products/<slug>/construction.json`: construction contract
- `Assets/GenWorks/<slug>/ProductManifest.json`: current state / gate / defect / hash / continuation point
- `contracts/quality/quality-spec.json`: quality specification
- `tools/production_contract.py`: shared product contract validation
- `tools/workspace_transaction.py`: last-good workspace protection
- `Taskfile.yml` / `tools/manage.py`: supported operator entry point

pose list、product root、lifecycle validator、quality threshold を prose や別実装へ複製しません。

## 作業開始

編集前に次を直接確認します。

1. current `main`
2. open PR / branch と重複 workstream
3. 変更対象の実ファイル
4. product task なら slug / job / construction / manifest / last-good checkpoint / current renders / defects
5. 変更に必要な最小 scope と verification

有効な canonical checkpoint がある場合はそこから継続し、同じ workstream をゼロから作り直しません。

## 変更原則

- generic defect は generic layer で直す
- 一つの rule には一つの owner を持たせる
- superseded code / doc / reference は残さない
- job / schema / manifest / assets / tests / policy / docs を整合させる
- failing data に合わせて gate を弱めない
- last-good checkpoint を悪化した生成物で上書きしない
- 実行していない tool、開いていない画像、未検証 runtime を PASS と表現しない
- private asset、credential、cache、machine state を commit しない
- tracked Unity asset の `.meta` / GUID を意図なく変更しない

## 製品ワークスペース

製品成果物は `Assets/GenWorks/<slug>/` のみを canonical workspace とします。alternate product root を増やしません。

ローカル report / candidate copy / optional external result は `.image2outfit/products/<slug>/{reports,candidate,release}` に置き、Git 管理しません。

詳細な配置は `README.md` と product job を参照し、ここに path tree を複製しません。

## 標準 workflow

product task は、まず契約を説明させます。

```powershell
task explain PRODUCT=<slug>
```

candidate を生成・検証する場合:

```powershell
task candidate PRODUCT=<slug>
```

defect diagnosis、targeted experiment、再生成、再評価を進める場合:

```powershell
task improve PRODUCT=<slug>
```

review 済み candidate を release validator に通す場合:

```powershell
task release PRODUCT=<slug>
```

コマンドの正本は `Taskfile.yml` / `tools/manage.py` です。この文書に全 command を複製しません。

## Evidence と visual review

Blender render evidence は現在の生成物に結びついた metadata と hash を持つ必要があります。historical artifact の camera / generator state を filename や現在コードから推測しません。

`visualAppearanceReview` は実画像を直接開いて確認した場合だけ判定します。少なくとも policy が要求する current view / pose を対象にし、次のような visible defect を確認します。

- body penetration / clipping
- detached geometry / floating part
- wrong scale / broken silhouette
- extreme vertex / asymmetric failure
- UV / normal / material failure
- pose breakage

file existence、dimensions、hash、CI success は visual inspection の代替ではありません。

## Completion boundary

`COMPLETE` の唯一の machine-readable 定義は `config/genworks-handoff-policy.json` の `requiredCompletionGates` です。本ファイルに gate 一覧を複製しません。

Unity import/save/reload、Modular Avatar / NDMF、VRChat Build & Test、VRChat runtime、人間 runtime review は現在 policy 上 `OUT_OF_SCOPE` です。未実行や環境不在を completion blocker にしません。同時に、外部 evidence なしで runtime compatibility を PASS と主張しません。

## Validation

変更量に比例した check に加え、repository contract を壊す可能性がある変更では次を使用します。

```powershell
task audit:all
task check:python
```

より限定した監査が必要な場合は `Taskfile.yml` の individual audit を選択します。

検証不能な boundary がある場合は、未確認事項をそのまま明示します。Unity / VRChat の不在は現在の completion blocker ではありません。

## Failure recovery

失敗時は次を優先します。

1. last-good canonical workspace を保護・復元する
2. diagnostics を canonical output と分離して残す
3. failing stage / hash / visible defect / next action を記録する
4. lifecycle state を実態に合わせる
5. continuation に必要な rejected evidence を保持する

## Git / PR

PR は integration vehicle であり、未完了製品や将来作業を保持する backlog ではありません。workstream の終了時は open PR を原則 0 件にします。

- `main` へ直接 push しない
- coherent change ごとに短命 branch を使う
- intended file だけ commit する
- overlap する workstream がある場合は競合 branch を増やさず、既存 workstream を継続または supersede relationship を明示する
- PR には scope、contract impact、verification、残る blocker を書く
- `requiredCompletionGates`、`visualAppearanceReview`、製品の `COMPLETE` / release 条件は、通常の incremental implementation PR の merge 条件にしない。PR 自身が製品 release / completion を主張する場合だけ、その主張に対応する gate を要求する
- merge blocker は、未解消の merge conflict、当該 diff が原因の required repository CI failure、契約上の不整合、または現在利用可能な環境で直接実行できる必須検証の未実行に限定する
- Unity / VRChat / 外部 runtime など現在利用できない検証は `NOT_RUN` / `OUT_OF_SCOPE` として正確に記録し、それだけを理由に PR を Draft のまま保持しない
- agent / ChatGPT は open PR の blocker を同じ作業線で確認し、実行可能なら head を修正して再検証し merge する。main に既に吸収済み・代替済みなら理由を残して close する
- stale PR を放置しない。有用差分は current `main` へ rebase / port して merge し、不要差分は superseded として close する
- merge / close 後は不要 branch を削除する
- merge 後は `main` を readback して結果を確認する

## Documentation

Markdown の役割は次の3層に限定します。

- `README.md`: user-facing entry point
- `ARCHITECTURE.md`: stable design / contract relationship
- `AGENTS.md`: agent execution rules

product 固有 README は製品記録として扱います。machine-readable rule を Markdown にコピーして別の正本を作りません。

## 最終報告

確認できた事実だけを報告します。

- effective state
- principal changed files / behavior
- executed checks と結果
- evidence link
- commit / PR / merge / branch state
- 残る in-scope blocker

`OUT_OF_SCOPE` 項目は未完了作業として扱いません。
