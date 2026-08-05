# image2outfit アーキテクチャ

## 目的

衣装ごとの巨大なBlenderスクリプトへ知識を埋め込まず、参照画像から衣装要素、型紙、縫合、三次元初期配置、クロスシミュレーション、スキニング、レンダリング、監査へ進む手順を再利用可能な契約として管理します。

## 依存方向

```text
config / product data
        ↓
tools（実行、Blender、subprocess、製品固有アダプター）
        ↓
src/image2outfit（製品非依存の安定ロジック）
```

`src`から`tools`、`bpy`、`bmesh`、`mathutils`をimportしてはいけません。Blenderが必要な処理は`src`で実行仕様を表現し、`tools`が実行します。

## srcに置くもの

- 身体部位と、左・右・中央・両側、前・後・内・外・上・下の位置語彙
- 衣装パーツ、構造上の役割、積層位置、素材挙動、フィットの語彙
- 二次元型紙境界、名前付き型紙辺、縫い代、ノッチ、ダーツ
- 型紙辺を参照する縫合グラフ
- 画像領域、型紙座標、三次元形状の対応識別子
- 正規工程順と計画・実行状態
- Blender Python、クロスシミュレーション、レンダリング証拠の仕様
- 工程結果とSHA-256証拠の検証
- 研究から結晶化した製品非依存原則
- `src`と`tools`の境界監査

## toolsに置くもの

- コマンドライン入口
- Blender実行環境への接続
- subprocess、ファイルシステム、外部実行
- 製品固有のビルド、クロス、出力、レンダリングスクリプト
- 実験中の個別ツール

複数製品で反復された製品非依存ロジック、または完成判定に必須の安定処理は、テストを付けて`src`へ昇格させます。

## 正規パイプライン

1. 参照画像と来歴を固定
2. 姿勢と視点を正規化
3. 身体位置と構造上の役割で衣装を分解
4. 二次元型紙を作成
5. 型紙辺の縫合グラフを作成
6. 三次元初期配置を作成
7. Blender Pythonで形状を構築
8. クロスシミュレーションを実行
9. スキニングとFBXを出力
10. 五面と必須ポーズをレンダリング
11. 形状、ウェイト、貫通、証拠を監査
12. 現在の実画像を直接確認
13. `WORKING`、`COMPLETE`、`REJECTED`を既存の候補ゲートへ記録

正規工程は`src/image2outfit/pipeline.py`、工程別要件は`config/pipeline-profiles/garment-reconstruction-v1.json`にあります。

## 状態の境界

- `PLANNED`: 13工程の呼び出し計画を構築した。実処理の成功ではない
- `EXECUTED`: 工程別結果と証拠を検証し、13工程を実行した。製品完成の主張ではない
- `FAILED`: 工程、結果契約、証拠、hashのいずれかが失敗した
- `WORKING` / `COMPLETE` / `REJECTED`: 正準の製品状態。既存候補・完成ゲートだけが決定する

LangChainとLangGraphは固定工程の実行器であり、製品完成状態の所有者ではありません。

## 工程結果契約

実行バインディングはシェル文字列ではなくargv配列と、`.image2outfit/`以下の`resultPath`を宣言します。終了コード0だけでは工程は成功しません。

```json
{
  "stageBindings": {
    "render-evidence": {
      "command": ["python", "tools/render_product.py", "--job", "{jobPath}"],
      "resultPath": ".image2outfit/products/{productId}/reports/render-evidence.json"
    }
  }
}
```

工程コマンドは`schemaVersion`、正しい`stage`と`productId`、`status: PASS`、hash付き`evidence`を持つJSONを新規作成します。スキーマは`config/pipeline/stage-result.schema.v1.json`です。

ランナーは古い結果ファイルを実行前に削除し、実行後に次を確認します。

- 正しい工程名と製品ID
- `status: PASS`
- 工程プロファイルで要求された結果フィールド
- 最低証拠件数
- 証拠パスがリポジトリ内にあること
- 証拠ファイルが存在すること
- 実ファイルから再計算したSHA-256が宣言値と一致すること

`visual-review`は少なくとも五面のhash付き証拠と`reviewMethod: direct-image-inspection`を要求します。ただし最終的な`visualAppearanceReview`判定は既存の製品完成契約が所有します。

## 型紙中間表現

型紙は単なる点列ではなく、パーツの身体部位・左右・前後内外位置、パネル境界、名前付き型紙辺、縫い代、ノッチ、ダーツ、画像・型紙・三次元形状の対応識別子、縫合が参照する正確な型紙辺を明示します。

## 研究原則

一次文献の採用判断と本番要件の正本は`Assets/GenWorks/Shared/Research/2026-garment-methods.json`です。`src/image2outfit/research.py`は実装に直接利用する少数の安定原則を保持し、著者コード、モデル、チェックポイント、データセットはコピーしません。
