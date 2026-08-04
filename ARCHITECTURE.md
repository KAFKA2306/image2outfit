# image2outfit アーキテクチャ

## 目的

衣装ごとの巨大な Blender スクリプトへ知識を埋め込まず、画像から衣装を分解し、型紙・縫合・三次元初期配置・クロスシミュレーション・スキニング・レンダリング・監査へ進む手順を再利用可能な契約として管理します。

## 依存方向

```text
config / product data
        ↓
tools（実行、Blender、subprocess、個別アダプター）
        ↓
src/image2outfit（製品非依存の安定ロジック）
```

`src` から `tools`、`bpy`、`bmesh`、`mathutils` を import してはいけません。Blender が必要な処理は `src` で実行仕様を表現し、`tools` が実行します。依存方向は `tools → src` の一方向です。

## src に置くもの

- 身体部位、衣装パーツ、構造上の役割、積層位置、素材挙動、フィットの共通語彙
- 二次元型紙、型紙辺、縫合グラフ、画像・型紙・三次元形状の対応識別子
- 正規の工程順と工程状態
- Blender Python 呼び出し仕様
- クロスシミュレーション仕様
- 五面・ポーズのレンダリング証拠仕様
- 最新研究から結晶化した、製品非依存の実装原則
- `src` と `tools` の境界監査

## tools に置くもの

- コマンドライン入口
- Blender 実行環境への接続
- subprocess、ファイルシステム、外部実行
- 製品固有のビルドスクリプト
- 実験中の個別ツール

同じ製品非依存ロジックが複数の衣装で再実装された場合、または完成判定に必須の処理として安定した場合は、テストを付けて `src` へ昇格させます。

## 正規パイプライン

1. 参照画像と来歴を固定
2. 姿勢と視点を正規化
3. 身体部位と構造上の役割で衣装を分解
4. 二次元型紙を作成
5. 型紙辺の縫合グラフを作成
6. 三次元初期配置を作成
7. Blender Python を呼び出して形状を構築
8. クロスシミュレーションを実行
9. スキニングと FBX 出力
10. 五面と必須ポーズをレンダリング
11. 形状、ウェイト、貫通、証拠を監査
12. 実画像を直接確認
13. `WORKING`、`COMPLETE`、`REJECTED` を記録

正規の工程名と順序は `src/image2outfit/pipeline.py`、宣言プロファイルは `config/pipeline-profiles/garment-reconstruction-v1.json` にあります。

## LangChain / LangGraph

同じ工程契約を3種類の実行器で動かします。

- `deterministic`: 外部依存なし。CI、再現試験、計画生成用
- `langchain`: `RunnableLambda` の直列チェーン
- `langgraph`: `StateGraph` の状態付き工程グラフ

LangChain と LangGraph は固定された工程契約の実行器であり、衣装の意味や完成条件の所有者ではありません。工程、状態、語彙、検証規則は `src` が所有します。

```powershell
uv run --locked --no-default-groups python tools/run_garment_pipeline.py `
  --request config/pipeline-request.example.json

uv run --with langchain-core==1.5.0 python tools/run_garment_pipeline.py `
  --engine langchain `
  --request config/pipeline-request.example.json

uv run --with langchain-core==1.5.0 --with langgraph==1.2.9 `
  python tools/run_garment_pipeline.py `
  --engine langgraph `
  --request config/pipeline-request.example.json
```

既定では各工程の呼び出し計画だけを生成します。実処理へ接続する場合は、工程プロファイルへ明示的なコマンドを設定し、`--execute` を付けます。見た目レビューは、現在の実画像を直接開かない限り PASS にしません。

## 研究原則

- PatternGSL: パネル境界、縫合、ステッチ位相を第一級データにする
- AutoSew: 縫合を型紙辺の幾何グラフとして扱う
- DressWild: 姿勢・視点正規化と型紙推定を分離する
- Diffusion Mapping via Pattern Coordinates: 画像、型紙座標、三次元形状の対応を保持する

一次文献URL、日付、実装境界は `src/image2outfit/research.py` に固定します。著者コード、モデル、チェックポイント、データセットはコピーしません。
