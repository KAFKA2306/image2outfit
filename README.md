# image2outfit

SiroinoSotai_PC向け衣装をBlenderで制作し、編集可能ソース、FBX、宣言済みPrefab、実レンダリング、研究記録を一つの再現可能な製品ワークスペースで管理するプロジェクトです。

## 完了の定義

正本は `config/genworks-handoff-policy.json` です。製品は次を満たしたとき `COMPLETE` です。

- Blender生成が成功している
- 編集可能な制作ソースとFBXがある
- Prefab資産が正規パスへ宣言されている
- SiroinoSotai_PC装着済みの正面・背面・左・右・斜めレンダリングが現在の生成物である
- 必須ポーズの実レンダリングが現在の生成物である
- 2026年の研究手法の実試行が記録されている
- 実画像を開いて確認した `visualAppearanceReview` が `PASS` である

`visualAppearanceReview` はChatGPTが実artifact画像を直接開いて実施できます。画像の存在、ファイルサイズ、hash、CI成功だけではPASSになりません。

## 再利用可能な衣装パイプライン

共通アーキテクチャは [`ARCHITECTURE.md`](ARCHITECTURE.md) に記載しています。

- `src/image2outfit/`: 製品非依存の語彙、型紙・縫合中間表現、工程順、実行・証拠契約
- `tools/`: Blender、subprocess、ファイルシステム、製品固有スクリプトへの接続
- `config/pipeline-profiles/`: 正規工程と工程別証拠要件

計画モードの最終状態は `PLANNED` です。計画の作成を製品完成とは扱いません。`--execute` の最終状態も製品状態の `COMPLETE` ではなく `EXECUTED` です。製品の `WORKING`、`COMPLETE`、`REJECTED` は既存の候補・完成ゲートだけが決定します。

実行工程は終了コード0だけでは成功になりません。各工程は `.image2outfit/` 以下へ工程結果JSONを書き、工程名、製品ID、`PASS`、必要な結果フィールド、証拠ファイルのSHA-256を宣言します。ランナーは実ファイルのSHA-256を再計算して一致を確認します。

## スコープ外

次は本プロジェクトの完了条件ではありません。

- Unity 2022.3.22f1 import/save/reload
- Modular Avatar／NDMF
- VRChat Build & Test
- VRChat runtime確認
- 人間によるruntime視覚確認

これらは `OUT_OF_SCOPE` です。未実行・失敗・環境不在でも `COMPLETE` を妨げません。一方、外部検証なしにUnityやVRChatで動作確認済みとは表現しません。

## 正準配置

```text
config/products/<slug>/
  job.json
  construction.json
  license.json

Assets/GenWorks/<slug>/
  ProductManifest.json
  README.md
  Source/
  Models/
  Textures/
  Materials/
  Prefab/
  Previews/
    front.png
    back.png
    left.png
    right.png
    three-quarter.png
    Poses/<release-policyの必須ポーズ>.png
  Research/
  Tests/
  Documentation/
```

`Assets/GenWorks/<slug>/` が唯一の正規ワークスペースです。

ローカルの監査ログ、候補コピー、任意の外部検証結果は `.image2outfit/products/<slug>/{reports,candidate,release}` に置き、Git管理しません。以前の `Artifacts/`、`Candidates/`、`Release/` は使用しません。

## 基本操作

```powershell
uv sync --locked

task explain PRODUCT=<slug>
task candidate PRODUCT=<slug>

task audit:repo
task audit:runtime
task audit:genworks
task audit:tools
task audit:methods
task audit:research
task check:python
```

`task candidate` はBlender生成、成果物整合、必須画像、研究記録を検証します。UnityやVRChatの実行環境を要求してはいけません。

## GitHub Actions境界

検証workflowは原則として読み取り専用権限を使います。

```yaml
permissions:
  contents: read
```

ブランチ整理など、明示された保守workflowだけが最小限の書き込み権限を持ちます。

## 状態

- `WORKING`: 再開可能だが、レンダリングまたは見た目の完了ゲートが残る
- `COMPLETE`: 必須レンダリングと見た目レビューを含む全スコープ内ゲートを通過
- `REJECTED`: 問題と再開地点を保持した却下結果

Unity／VRChat関連の結果は状態遷移に使用しません。
