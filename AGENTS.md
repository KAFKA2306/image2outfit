# image2outfit エージェント契約

## 作業の始め方

- 製品の作業では、まず製品の slug と依頼された成果を特定する。
- 次に、関係する正本（下の「正本の一覧」）と現在の `ProductManifest.json` だけを読む。
- 関係のない製品フォルダ、docs、Issue、PR 履歴、renders、調査メモは事前に読み込まない。
- 同じ成果を担当する既存の checkpoint / workline があれば、それを引き継いで続ける。

## 正本の一覧

- 完了と実行範囲: `config/genworks-handoff-policy.json`
- 必要な見た目の証拠と顧客への公開: `config/release-policy.json` と `contracts/quality/quality-spec.json`
- 製品の識別・入力・出力: `config/products/<slug>/job.json`
- 製品の構成: `config/products/<slug>/construction.json`
- 現在の状態・ゲート・不具合・ハッシュ: `Assets/GenWorks/<slug>/ProductManifest.json`
- 実行のトランザクションと last-good の保護: `tools/runtime_transaction.py`
- コマンド: `Taskfile.yml` / `tools/manage.py`

`README.md` は利用者向けの入口です。`ARCHITECTURE.md` は安定した設計の関係を説明します。機械が読む正本は、文章の説明より優先します。

## 製品のコマンド

その作業を担当する既存のコマンドを使います。

```powershell
task explain PRODUCT=<slug>
task candidate PRODUCT=<slug>
task improve PRODUCT=<slug>
task release PRODUCT=<slug>
```

リポジトリ全体の確認は `task audit:all` と `task check:python` です。既存の Taskfile / manage の経路が担当している処理には、別のコマンド経路を作らないでください。

## 製品のルール

- 製品の作業場所は `Assets/GenWorks/<slug>/` だけにする。
- 認証情報、非公開アセット、キャッシュ、マシン固有の状態、意図しない Unity の `.meta` / GUID の変更はコミットしない。
- GitHub Pages が有効な間は、公開 URL を `README.md` の 1 行目にプレーンテキストで書く。
- 公開される製品の状態は、各 `ProductManifest.json` か、その既存の正本の投影から読む。手書きの状態一覧は作らない。

## dbt の役割

dbt は、製造と製品の証拠を再現可能に変換・テスト・分析するための、リポジトリの正式な役割です。

- 権威は上の正本だけです。dbt は正本の既存の投影を読むだけで、2 つ目の正本にはなりません。
- モデル化してよいのは、製品の識別、製造の実行、ゲートと検証の状態、不具合、成果物、ハッシュ、リリースの観測など、正本の証拠に既にある事実だけです。
- 製造の実行は、既存の正本ファイルを通じて dbt が読める証拠を残す。dbt のためだけに手書きの台帳を新しく作らない。
- dbt のテストは、矛盾した不完全な派生データを拒否してよい。ただし、実行されていない mesh・UV・material・rig・render・Unity・VRChat の工程を dbt が PASS にしてはいけない。
- dbt の抽出・ビルド・テストのコマンドは、既存の `Taskfile.yml` / `tools/manage.py` から実行する。SQL やエクスポートの単発コマンドを作らない。

## 証拠

生成されたファイル、ハッシュ、一覧、CI の成功、もっともらしい説明文は、見た目の合格の証拠になりません。見た目の合格には、`contracts/quality/quality-spec.json` と `config/release-policy.json` が求める現在の証拠を、直接確認する必要があります。

見た目に影響する作業では、次の流れで確認します。

1. Blender / Unity の現在の表示を撮る。
2. シルエット、縫い目、UV・material の見え方、交差、必要なポーズを確認する。
3. 最小限のソース変更をする。
4. 撮り直して、数値の確認をもう一度行う。

## 作業の引き継ぎ

作業が止まったら、次の 5 点を既存の正本の workline に保存します。

- manifest / checkpoint の現在の状態
- 失敗した工程、または見えている不具合
- ブロッカー

## リポジトリの衛生（必須）

- この repository のローカル作業ブランチと worktree は、それぞれ 1 つだけにする。作業でブランチや worktree を作ったら、終了前に merge するか削除する。
- 作業の終わりに、未コミット・未追跡・stash の作業を残さない。各変更は次のどれかにする。
  - コミットする（上の secret / 非公開アセット / キャッシュの確認の後）
  - `.gitignore` で無視されるローカル出力にする
  - リポジトリの外に保管する（例: scratchpad に `git bundle` や patch を置く）
- 新しい種類のローカル専用の出力が出たら、同じ変更でそのパスを `.gitignore` に追加する。
- 最後に 1 つのブランチを push し、`git status` がクリーンであることを報告する。
