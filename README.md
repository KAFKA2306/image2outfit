# image2outfit

SiroinoSotai_PC 向け衣装を Blender で制作し、編集可能ソース、FBX、Prefab 宣言、実レンダリング、研究記録を再現可能な製品ワークスペースとして管理するプロジェクトです。

## 正本

Markdown は入口と設計説明に限定します。変更され得る要件は、次の機械可読ファイルと実装を正本とします。

- 完了境界: `config/genworks-handoff-policy.json`
- 必須 view / pose: `config/release-policy.json`
- 製品入力・出力: `config/products/<slug>/job.json`
- 製品状態・gate・hash: `Assets/GenWorks/<slug>/ProductManifest.json`
- 品質仕様: `contracts/quality/quality-spec.json`
- パイプライン工程: `src/image2outfit/pipeline.py`
- 工程別要件: `config/pipeline-profiles/garment-reconstruction-v1.json`
- 操作用コマンド: `Taskfile.yml` / `tools/manage.py`

設計上の責務とデータフローは [`ARCHITECTURE.md`](ARCHITECTURE.md)、AI coding agent の作業規約は [`AGENTS.md`](AGENTS.md) を参照してください。

## 完了境界

製品状態は `WORKING` / `COMPLETE` / `REJECTED` です。`COMPLETE` の判定は `config/genworks-handoff-policy.json` の `requiredCompletionGates` のみを基準にします。

現在の必須 gate は次の8件です。

- Blender 生成
- 編集可能ソース
- FBX
- Prefab 宣言
- 5方向 render evidence
- 必須 pose evidence
- 実画像を直接確認した visual appearance review
- research trial

画像の存在、ファイルサイズ、hash、CI 成功だけでは visual appearance review の PASS にはなりません。

Unity import/save/reload、Modular Avatar / NDMF、VRChat Build & Test、VRChat runtime、人間による runtime visual review は現在 `OUT_OF_SCOPE` です。外部検証なしに、それらが動作確認済みとは表現しません。

## ワークスペース

製品の正規配置は次の2か所です。

```text
config/products/<slug>/
  job.json
  construction.json
  license.json

Assets/GenWorks/<slug>/
  ProductManifest.json
  Source/
  Models/
  Textures/
  Materials/
  Prefab/
  Previews/
  Research/
  Tests/
  Documentation/
```

`Assets/GenWorks/<slug>/` が製品成果物の canonical workspace です。ローカル監査、candidate copy、任意の外部検証結果は `.image2outfit/products/<slug>/{reports,candidate,release}` に置き、Git 管理しません。

## 必要環境

Python は `pyproject.toml` に従い **3.11.x** を使用します。Python 依存関係は `uv.lock` で固定されています。

基本操作には次を使用します。

- `uv`
- [Task](https://taskfile.dev/)
- Blender を必要とする生成工程では、repository contract が指定する Blender 実行環境

## 基本操作

依存関係を同期します。

```powershell
uv sync --locked
```

製品の契約を確認してから candidate を生成します。

```powershell
task explain PRODUCT=<slug>
task candidate PRODUCT=<slug>
```

既存 defect を診断し、実験・再生成・再評価を進める場合は次を使用します。

```powershell
task improve PRODUCT=<slug>
```

レビュー済み candidate を release validator に通す場合は次を使用します。

```powershell
task release PRODUCT=<slug>
```

repository 全体の監査と Python 検証は次で実行します。

```powershell
task audit:all
task check:python
```

個別監査は `task --list` または `Taskfile.yml` を正本として確認してください。Markdown にコマンド一覧を複製しません。

## 実行結果と証拠

パイプラインの計画状態 `PLANNED`、実行状態 `EXECUTED` は製品状態 `COMPLETE` とは別です。工程は終了コード 0 だけで成功にはなりません。

各工程は `.image2outfit/` 以下へ result JSON と evidence を出力し、runner が stage、product ID、必須フィールド、ファイル存在、SHA-256 を検証します。詳細は [`ARCHITECTURE.md`](ARCHITECTURE.md) を参照してください。

## Documentation policy

- `README.md`: 利用者向け入口、正本への導線、最小操作
- `ARCHITECTURE.md`: 責務境界、パイプライン、状態・証拠 contract
- `AGENTS.md`: coding agent の作業・検証・Git 運用規約
- `Assets/GenWorks/<slug>/README.md`: 製品固有の記録。project-level document の代替にしない

数値、gate、pose、schema、path rule を Markdown だけで所有しないでください。実装や policy と食い違った場合は、正本を確認して Markdown 側を修正します。
