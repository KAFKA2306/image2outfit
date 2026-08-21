# image2outfit アーキテクチャ

## 目的

衣装ごとの巨大な Blender script に知識を埋め込まず、参照画像から candidate の監査までを、製品非依存の contract と製品固有 adapter に分離します。

変更され得る gate、schema、path、工程要件は Markdown ではなく、対応する JSON / Python 実装を正本とします。

## 依存方向

```text
config / product data
        ↓
tools
        ↓
src/image2outfit
```

責務は次の通りです。

### `src/image2outfit/`

製品非依存で、Blender を import せずに検証できる安定ロジックを置きます。

- garment / body location vocabulary
- pattern / seam の中間表現
- canonical pipeline と状態遷移
- stage result / evidence contract
- SHA-256 検証
- quality evaluation
- research から抽出した再利用可能な原則
- `src` / `tools` 境界監査

`src` から `tools`、`bpy`、`bmesh`、`mathutils` を import しません。

### `tools/`

外部実行と製品固有処理を担当します。

- CLI entry point
- Blender 実行
- subprocess / filesystem access
- 製品固有 build / simulation / export / render
- 実験中の adapter

複数製品で反復される製品非依存ロジック、または完成判定に必要な安定処理は、test とともに `src` へ昇格させます。

### `config/` / `contracts/`

実行時の宣言と machine-readable contract を置きます。主要な正本は次です。

| 責務 | 正本 |
|---|---|
| PR merge 境界 | `config/pr-merge-policy.json` |
| 製品 completion 境界 | `config/genworks-handoff-policy.json` |
| 製品 release 境界 | `config/release-policy.json` |
| 製品 job | `config/products/<slug>/job.json` |
| construction | `config/products/<slug>/construction.json` |
| stage profile | `config/pipeline-profiles/garment-reconstruction-v1.json` |
| stage result schema | `config/pipeline/stage-result.schema.v1.json` |
| audit record schema | `config/pipeline/stage-audit-record.schema.v1.json` |
| run audit schema | `config/pipeline/run-audit-manifest.schema.v1.json` |
| quality | `contracts/quality/quality-spec.json` |

## 正規パイプライン

工程順の正本は `src/image2outfit/pipeline.py`、工程別要件は `config/pipeline-profiles/garment-reconstruction-v1.json` です。

1. `ingest-reference`
2. `normalize-view`
3. `decompose-garment`
4. `draft-patterns`
5. `infer-stitches`
6. `initialize-3d`
7. `build-blender`
8. `simulate-cloth`
9. `skin-and-export`
10. `render-evidence`
11. `audit-geometry`
12. `visual-review`
13. `finalize-candidate`

Markdown の番号や名称が実装と食い違う場合は、実装と profile を確認してこの文書を更新します。

## 状態の所有権

pipeline の実行状態と製品 lifecycle を分離します。

- `PLANNED`: 実行計画を構築した状態
- `EXECUTED`: stage result と evidence の検証を伴って pipeline を実行した状態
- `FAILED`: stage、result contract、evidence、hash のいずれかが失敗した状態
- `WORKING` / `COMPLETE` / `REJECTED`: 製品 lifecycle

`PLANNED` や `EXECUTED` を `COMPLETE` の代替にしません。製品 lifecycle と必須 completion gate は `config/genworks-handoff-policy.json` と `ProductManifest.json` が所有します。

## PR merge と製品 release

Repository integration と customer-facing product release は別の state machine として扱います。

```text
PR:      DRAFT → MERGE-ELIGIBLE → MERGED
Product: WORKING / REJECTED → COMPLETE → RELEASE-ELIGIBLE → RELEASED ARTIFACT
```

PR merge はコード、schema、policy、workflow、audit、test と、影響製品の pipeline が有効な境界まで実行できることを検証します。製品が `WORKING` または `REJECTED` であること、visual review が未合格であること、runtime review が未実施であること自体は merge failure にしません。

製品 release は merge 後の revision から明示的に実行し、`config/release-policy.json` と release validator が customer-quality evidence を評価します。merge は release を実行せず、製品 status を `COMPLETE` に昇格させず、release eligibility を暗黙に主張しません。

PR merge の machine-readable rule は `config/pr-merge-policy.json`、製品 release の rule は `config/release-policy.json` がそれぞれ所有します。両者の条件一覧を Markdown 側へ複製しません。

## Stage result contract

実行 binding は shell 文字列ではなく argv と `resultPath` を宣言します。終了コード 0 だけでは stage 成功にはなりません。

stage result は少なくとも次を検証対象にします。

- schema version
- stage name
- product ID
- `status: PASS`
- profile が要求する result field
- evidence 件数
- evidence path が repository 内に収まること
- evidence file の存在
- 宣言 SHA-256 と実ファイル SHA-256 の一致

runner は stale result を実行前に除去し、実行後に再検証します。

## Audit bundle

`PLAN` / `EXECUTE` の stage 記録は `.image2outfit/audit/<productId>/` に保存します。

```text
.image2outfit/audit/<productId>/
├── latest.json
└── <runId>/
    ├── manifest.json
    ├── pipeline-state.json
    └── stages/
        ├── 01-ingest-reference.json
        ├── ...
        └── 13-finalize-candidate.json
```

stage record は前段 record の digest を保持し、chain を構成します。失敗 stage も `FAILED` record と error を残します。

`image2outfit.audit.verify_audit_bundle(run_root)` は stage record、digest chain、pipeline state、manifest を再検証します。保存できたこと自体を成功条件にはしません。

## Pattern / seam 中間表現

pattern は単なる点列ではなく、少なくとも次を識別できる contract とします。

- body location / side / orientation
- panel boundary
- named pattern edge
- seam allowance
- notch / dart
- image / 2D pattern / 3D geometry の対応 ID
- seam graph が参照する pattern edge

これにより Blender geometry から construction knowledge を分離し、別製品・別 executor へ再利用できます。

## Quality contract

品質仕様の正本は `contracts/quality/quality-spec.json`、評価実装は `src/image2outfit/quality.py` です。

自動監査は個別 quality axis の判定を補助できますが、`visualAppearanceReview` 自体を自動 PASS にしません。現在の artifact 画像を直接確認した evidence が必要です。

Review Console などの派生 view は同じ正規化結果を表示し、独自 threshold を所有しません。

## Research contract

採用した一次文献、license、trial の正本は `Assets/GenWorks/Shared/Research/2026-garment-methods.json` です。

`src/image2outfit/research.py` には、実装で再利用する安定原則だけを保持します。論文著者の code、model、checkpoint、dataset を暗黙にコピーしません。

## Workspace と completion boundary

製品成果物の canonical workspace は `Assets/GenWorks/<slug>/` です。ローカルの audit / candidate / release data は `.image2outfit/` 以下に分離します。

completion gate と `OUT_OF_SCOPE` 項目は `config/genworks-handoff-policy.json` の正本を参照してください。Architecture 文書に同じ一覧を複製して所有しません。

## 変更ルール

- contract は一つの owner に集約する
- machine-readable rule を prose に複製しない
- generic defect は generic layer で修正する
- Blender 依存を `src` に逆流させない
- 派生 view に独自 threshold を持たせない
- schema / policy / implementation / tests / docs を同一変更で整合させる
