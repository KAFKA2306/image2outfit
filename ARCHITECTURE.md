# image2outfit アーキテクチャ

## 目的

衣装ごとの巨大なBlenderスクリプトへ知識を埋め込まず、参照画像から衣装要素、型紙、縫合、三次元初期配置、クロスシミュレーション、スキニング、レンダリング、監査へ進む手順を再利用可能な契約として管理します。

固定するのは正規工程と入出力契約です。各工程の実装はToolとして登録し、製品が要求するcapability、前工程が提供済みのcapability、明示pin、安定priorityの順で選択します。AgentやLLMは要求capabilityやpinを提案できますが、契約不適合なToolを強制実行することはできません。

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
- Toolのcapability、requires、provides、runtime、priorityと決定論的selector
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
4. 二次元型紙または契約済みの構造表現を作成
5. 型紙辺または構造部品の縫合グラフを作成
6. 三次元初期配置を作成
7. Blender Pythonで形状を構築
8. 選択された縫製・クロス・settling処理を実行
9. スキニングとFBXを出力
10. 型紙、五面、必須ポーズをレンダリング
11. 形状、ウェイト、貫通、証拠を監査
12. 現在の実画像を直接確認
13. `WORKING`、`COMPLETE`、`REJECTED`を既存の候補ゲートへ記録

正規工程は`src/image2outfit/pipeline.py`にあります。従来の単一Toolプロファイルは`config/pipeline-profiles/garment-reconstruction-v1.json`、Tool選択対応の正準モジュラープロファイルは`config/pipeline-profiles/garment-reconstruction-modular-v1.json`です。

## モジュラーTool選択

各Toolは最低限次を宣言します。

```text
ToolDescriptor
├── tool_name
├── purpose
├── output_contract
├── capabilities
├── requires
├── provides
├── runtime
├── priority
└── deterministic
```

選択は`src/image2outfit/tooling.py`の`choose_tool`が行い、順序は固定です。

1. 工程で宣言されたTool候補を取得
2. `toolRequirements`を満たさない候補を除外
3. 前工程までの`provides`で満たせない`requires`を持つ候補を除外
4. `toolPins`があれば、そのToolが1〜3を満たすことを検証して固定
5. 複数残れば`priority`、次に`toolName`で決定論的に選択
6. 0件なら実行前に失敗
7. 選択結果を`toolPlan`として出力し、選択Toolだけを既存`ToolRegistry`へ登録

したがってLLMを使わなくても再実行可能です。LangChainやLangGraphを使う場合も、契約検証済みToolだけが工程実行器へ渡ります。

製品requestは次のように方式を要求・固定できます。

```json
{
  "profilePath": "config/pipeline-profiles/garment-reconstruction-modular-v1.json",
  "toolRequirements": {
    "draft-patterns": ["pattern.explicit-2d", "garment.panel-sewn"],
    "simulate-cloth": ["simulate.sewing-springs"]
  },
  "toolPins": {
    "draft-patterns": "pattern.explicit-2d",
    "simulate-cloth": "simulate.blender.sewing-springs"
  }
}
```

`panel-sewn`製品と`closed-components`製品は同じ13工程を共有しながら、型紙、縫合、Blender構築、settling実装だけを差し替えられます。product-specific scriptは「何を作るか」に限定し、「どう実行・レンダリング・監査するか」はTool側へ集約します。

## 操作入口

通常の利用者やAgentは個別Pythonファイルを直接選びません。

```bash
task plan PRODUCT=siroino-white-ghost-gown
task workflow PRODUCT=siroino-white-ghost-gown
```

`plan`は実処理を行わず13工程のTool選択と理由を`toolPlan`として出します。`workflow`は同じ選択規則で実行し、`.image2outfit/products/<productId>/pipeline-state.json`へcheckpointを保存します。

既存の`candidate`、`improve`、`release`は製品完成状態とリリース境界を所有し続けます。モジュラーworkflowを実行したこと自体は`COMPLETE`を意味しません。

## 状態の境界

- `PLANNED`: 13工程の呼び出し計画を構築した。実処理の成功ではない
- `EXECUTED`: 工程別結果と証拠を検証し、13工程を実行した。製品完成の主張ではない
- `FAILED`: 工程、結果契約、証拠、hashのいずれかが失敗した
- `WORKING` / `COMPLETE` / `REJECTED`: 正準の製品状態。既存候補・完成ゲートだけが決定する

LangChainとLangGraphはTool選択後の工程実行器であり、製品完成状態の所有者ではありません。

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

bindingは後方互換の工程名だけでなくTool名でも指定できます。Tool名bindingがある場合は工程名bindingより優先されます。これにより同じ工程内で実装ごとに別の実行コマンドを持てます。

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

## 工程別監査出力

`PLAN`と`EXECUTE`の双方で、工程の戻り値をメモリ上だけに残さず、実行単位の監査bundleを次へ保存します。

```text
.image2outfit/audit/<productId>/
├── latest.json
└── <runId>/
    ├── manifest.json
    ├── pipeline-state.json
    └── stages/
        ├── 01-ingest-reference.json
        ├── 02-normalize-view.json
        ├── ...
        └── 13-finalize-candidate.json
```

各工程記録は、工程番号、工程名、要求モード、実際の結果、開始・終了時刻、選択済みTool契約、入力ダイジェスト、出力ダイジェスト、前工程記録のダイジェスト、証拠ファイルとSHA-256、工程の完全な出力を保持します。前工程の`recordDigest`を次工程の`previousRecordDigest`へ入れるため、途中の工程記録を変更すると連鎖検証が失敗します。

失敗した工程も`FAILED`記録、エラー型、エラー本文を保存します。失敗工程だけ監査証跡が欠落することはありません。

| 番号 | 工程 | 管理対象 |
|---:|---|---|
| 1 | `ingest-reference` | 参照manifest、原本SHA-256、来歴、対象アバターとの結合 |
| 2 | `normalize-view` | 正規化画像、カメラ姿勢、身体ランドマーク、正規化指標 |
| 3 | `decompose-garment` | 衣装部品グラフ、場所属性、素材領域、曖昧性ログ |
| 4 | `draft-patterns` | 型紙仕様、名前付き型紙辺、縫い代、ノッチ・ダーツ、画像・二次元・三次元対応 |
| 5 | `infer-stitches` | 縫合グラフ、型紙辺の対応、縫合方向、位相検証 |
| 6 | `initialize-3d` | 三次元初期メッシュ、各パネル変換、初期クリアランス監査 |
| 7 | `build-blender` | 編集可能Blend、構築報告、形状指標 |
| 8 | `simulate-cloth` | クロスキャッシュ、シミュレーション設定、衝突報告、評価済みメッシュ |
| 9 | `skin-and-export` | スキニング済みBlend、FBX、ウェイト監査、Prefab宣言 |
| 10 | `render-evidence` | 型紙、五面画像、必須ポーズ画像、レンダリングmanifest |
| 11 | `audit-geometry` | 形状監査、貫通監査、証拠hash監査、ゲート集計 |
| 12 | `visual-review` | 直接画像監査、確認画像hash、阻害事項 |
| 13 | `finalize-candidate` | 候補状態、完成ゲート記録、リリース判断 |

正準名称は工程プロファイルの`managedOutputs`です。工程記録の構造は`config/pipeline/stage-audit-record.schema.v1.json`、実行manifestは`config/pipeline/run-audit-manifest.schema.v1.json`で管理します。

`image2outfit.audit.verify_audit_bundle(run_root)`は各工程ファイル、工程内部の`recordDigest`、工程間連鎖、`pipeline-state.json`、manifestの連鎖終端を再検証します。CLIは保存直後に同じ検証を行い、検証できないbundleを正常終了として扱いません。

## 型紙中間表現

型紙は単なる点列ではなく、パーツの身体部位・左右・前後内外位置、パネル境界、名前付き型紙辺、縫い代、ノッチ、ダーツ、画像・型紙・三次元形状の対応識別子、縫合が参照する正確な型紙辺を明示します。

## 研究原則

一次文献の採用判断と本番要件の正本は`Assets/GenWorks/Shared/Research/2026-garment-methods.json`です。`src/image2outfit/research.py`は実装に直接利用する少数の安定原則を保持し、著者コード、モデル、チェックポイント、データセットはコピーしません。
