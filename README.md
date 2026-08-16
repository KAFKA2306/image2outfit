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

## QualitySpec

品質診断の正本は `contracts/quality/quality-spec.json`、評価実装は `src/image2outfit/quality.py` です。既存の8完成ゲートは変更せず、`visualAppearanceReview` の内訳を次の10軸へ分離します。

- topology
- seam
- fit
- material-response
- layering
- skinning
- collision
- silhouette
- styling-fidelity
- evidence-completeness

各軸は、指標名、比較演算子、閾値、観測値、対象view／pose、判定方法、判定者、証拠path、SHA-256、defect code、正規13工程への戻り先を保存します。証拠欠損、path逸脱、SHA-256不一致はPASSを禁止します。許可された `OUT_OF_SCOPE` は理由を必須とし、FAILへ数えません。

`visualAppearanceReview` は `DIRECT_IMAGE_REVIEW` と、hash検証済みの5方向・必須ポーズ画像がある場合だけPASSになります。自動監査は個別軸を補助できますが、外観レビュー自体をPASSにできません。

release gateは `visual-review.qualitySpec` を評価し、`.image2outfit/products/<slug>/reports/customer-quality.json` の `evidence.qualitySpec` に正規化結果を書きます。Review Consoleは同じprojectionから品質gate、defect、戻り先、証拠hash、candidate hashを表示し、独自閾値を持ちません。

2026年の設計根拠は次の一次情報です。

- ReWeaver: topology、geometry alignment、seam-panel consistency — <https://arxiv.org/abs/2601.16672>
- AutoSew — <https://arxiv.org/abs/2602.22052>
- Learning-based Seam Correspondence Reconstruction — <https://arxiv.org/abs/2607.21213>
- EASE: local ease field — <https://arxiv.org/abs/2606.29419>
- MV-Fashion: multilayer outfitとstyling detail — <https://arxiv.org/abs/2603.08147>
- Image2Garment: material／physical parameter inference — <https://arxiv.org/abs/2601.09658>
- C2PA 2.2 hard binding — <https://spec.c2pa.org/specifications/specifications/2.2/specs/C2PA_Specification.html>

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
