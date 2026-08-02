# image2outfit

**BlenderからUnity／VRChat向け衣装Prefabまでを、再現可能な形で制作・検証・引き継ぐためのUnityプロジェクトです。**

image2outfitは、衣装ごとに編集可能な制作データ、FBX、Unity Prefab、マテリアル、実レンダリング、検証結果を一つの製品ワークスペースへまとめます。試作途中や却下された候補も、再開に必要な情報がある限り同じ場所に残るため、次の作業者がゼロから作り直す必要がありません。

## このプロジェクトで扱うもの

```text
衣装仕様・参照画像
        ↓
Blender制作データ
        ↓
FBX・マテリアル・テクスチャ
        ↓
Unity Prefab・Modular Avatar / NDMF設定
        ↓
5方向レンダリング・ポーズ確認・技術検証
        ↓
人間レビュー
        ↓
顧客向けリリース
```

主な特徴は次のとおりです。

- 衣装ごとに一つの正規ワークスペースを持つ
- Blender、FBX、Prefab、画像、検証状態を同じ製品IDで追跡する
- 技術候補の作成と顧客向けリリース判定を分離する
- Unity Import、Prefab再読込、Modular Avatar／NDMF、見た目、ポーズ、runtimeを別々に確認する
- 失敗時も最後に使えた制作状態と再開地点を保持する
- リポジトリ全体の配置、依存関係、研究基準、残骸を自動監査する

## 読むファイル

| 読者 | ファイル | 内容 |
| --- | --- | --- |
| 利用者・開発者 | `README.md` | プロジェクト概要、構成、セットアップ、基本操作 |
| AIコーディングエージェント | `AGENTS.md` | 調査、変更、検証、証拠、Git運用の実行規約 |
| 製品を確認する人 | `Assets/GenWorks/<slug>/README.md` | 対象衣装の概要、成果物、既知の問題 |
| ツール・自動処理 | `Assets/GenWorks/<slug>/ProductManifest.json` | 状態、ゲート、ハッシュ、欠陥、次の作業 |

リポジトリ共通の説明は、このREADMEとルートの `AGENTS.md` に集約しています。製品固有の内容は各製品ワークスペースにあります。

## 必要な環境

正確な対応バージョンと公式参照先は [`config/toolchain-lock.json`](config/toolchain-lock.json) を正本とします。

主な構成要素は次のとおりです。

- Blender
- Unity 2022.3系
- VRChat SDK Base／Avatars
- Modular Avatar
- NDMF
- Avatar Optimizer
- Python 3.11
- uv
- Task
- VPM CLI

Python依存は [`pyproject.toml`](pyproject.toml)、固定された解決結果は [`uv.lock`](uv.lock) にあります。Unity／VPM依存は `Packages/` 配下で管理します。

## セットアップ

リポジトリを取得し、固定済みのPython環境とVPMパッケージを復元します。

```powershell
git clone https://github.com/KAFKA2306/image2outfit.git
cd image2outfit

uv sync --locked

vpm add repo https://vpm.nadena.dev/vpm.json
vpm add repo https://vpm.anatawa12.com/vpm.json
vpm resolve project .
```

環境とリポジトリ構造を確認します。

```powershell
task audit:repo
task audit:runtime
task audit:genworks
task check:python
```

Unityでは、このリポジトリをプロジェクトとして開きます。購入済み・非公開のアバターやローカル参照データは、製品jobで指定されたGit管理外の `Assets/_Local/`、`Assets/_Vendor/` などへ配置します。

## 製品を確認する

製品IDは `<slug>` で表します。たとえば製品IDが `sample-outfit` の場合、主要ファイルは次の場所にあります。

```text
config/products/sample-outfit/
  job.json
  license.json

Assets/GenWorks/sample-outfit/
  ProductManifest.json
  README.md
  Source/
  Models/
  Textures/
  Materials/
  Prefab/
  Previews/
  Demo/
  Editor/
  Tests/
  Documentation/
```

製品Prefabは `Assets/GenWorks/<slug>/Prefab/`、最新の画像は `Previews/`、編集可能な制作データは `Source/`、現在の状態は `ProductManifest.json` にあります。

**`Assets/GenWorks/<slug>/` が、その衣装について人間とツールが参照する唯一の正規ワークスペースです。** 技術実行中に作られる監査ログ、レビュー用コピー、配布用ZIPなどは `.image2outfit/products/<slug>/{reports,candidate,release}` にまとめられ、Git管理されません。

以前の `Artifacts/`、`Candidates/`、`Release/` は使用しません。旧出力が残っている場合は、最初の実行時に同じ製品IDの内部領域へ移されます。レビュー済みcandidateや既存releaseを黙って破棄する移行は行いません。

Unity Editorでは `GenWorks > Product Catalog` から、製品状態、Prefab、プレビュー、製品READMEを一覧できます。

## 基本操作

### 製品の構成と必要証拠を確認する

```powershell
task explain PRODUCT=<slug>
```

選択された制作方式、必要な入力、利用する研究手法、生成対象、未完了ゲートを表示します。

### 技術候補を作る

```powershell
task candidate PRODUCT=<slug>
```

このコマンドは、正規ワークスペースの制作物を検証し、人間レビューへ進められる技術候補かを判定します。既存の正常な状態を保護しながら、制作、書き出し、監査を実行します。

### リリース判定と配布物を作る

```powershell
task release PRODUCT=<slug>
```

同一候補に対する必要な技術ゲートと人間レビューが揃った場合だけ、配布用パッケージを生成します。技術候補の生成だけではリリース済みになりません。

### リポジトリを監査する

```powershell
task audit:repo
task audit:runtime
task audit:genworks
task audit:tools
task audit:methods
task audit:research
task check:python
```

| コマンド | 確認内容 |
| --- | --- |
| `task audit:repo` | 一時状態、重複管理、自己変更workflowなどのリポジトリ残骸 |
| `task audit:runtime` | 製品job内の一時パス、旧出力ルート、Git ignore設定 |
| `task audit:genworks` | 製品ルート、Manifest、Prefab、アセット配置 |
| `task audit:tools` | ツールの所有関係、重複、循環、過剰な階層 |
| `task audit:methods` | 製品要件から制作方式を選ぶロジック |
| `task audit:research` | 研究基準の鮮度、一次情報、ライセンス |
| `task check:python` | lock、Python構文、監査、unit tests、ruff |

### 旧配置を正規ワークスペースへ移す

```powershell
task maintenance:migrate:genworks
task maintenance:migrate:genworks:apply
```

最初のコマンドは移行計画だけを表示し、`apply`付きのコマンドが実際の移動と監査を行います。

## 製品ライフサイクル

状態名は [`config/genworks-handoff-policy.json`](config/genworks-handoff-policy.json) で定義されています。

```text
WORKING
  ↓
TECHNICAL_READY
  ↓
HUMAN_REVIEW_PENDING
  ↓
RELEASED
```

| 状態 | 意味 |
| --- | --- |
| `WORKING` | Git上に再開可能な制作状態があるが、技術確認が残っている |
| `TECHNICAL_READY` | 必要な自動技術ゲートを通過している |
| `HUMAN_REVIEW_PENDING` | 技術作業と証拠が揃い、人間による見た目・ポーズ・runtime確認待ち |
| `REJECTED` | 問題と再開地点を記録した却下済み候補 |
| `RELEASED` | 同一候補が必要な技術確認と人間レビューをすべて通過した状態 |

`REJECTED`は削除対象を意味しません。再制作や監査に使えるBlend、FBX、Prefab、画像、診断がある場合は、その製品ワークスペースに保持されます。

## 品質確認

顧客向けリリースでは、ファイルが存在するだけでなく、同一候補に対する複数の確認結果を扱います。

### 見た目

- front
- back
- left
- right
- three-quarter
- combined multiview

シルエット、サイズ、体の露出、貫通、UV、法線、マテリアル、金具、見栄えを確認します。

### ポーズ

製品jobで指定されたポーズ画像を使い、ウェイト、変形、脱落、体への貫通を確認します。

### Unity／VRChat

- Unity Import
- Prefab保存と再読込
- Modular Avatar／NDMF統合
- VRChat Build & Test
- runtime表示と操作

具体的なリリース証拠の形式と基準は [`config/release-policy.json`](config/release-policy.json) にあります。

## リポジトリ構成

```text
Assets/GenWorks/          製品ワークスペースと共有Unity実装
config/products/          製品jobとライセンス情報
config/                   スキーマ、配置、状態、リリース、ツールチェーン契約
tools/                    制作入口と汎用監査
Tests / tests/            UnityおよびPythonの検証
.github/workflows/        hosted／self-hostedの自動検証
```

この一覧には、再生成可能な監査ログ、候補コピー、配布パッケージなどのランタイム出力を含めません。それらは `.image2outfit/` 内部に閉じた実行結果であり、開発者が理解すべき恒久的なリポジトリ構造ではないためです。

## 主な契約ファイル

| ファイル | 役割 |
| --- | --- |
| `config/job.schema.v2.json` | 製品jobの形式 |
| `config/products/<slug>/job.json` | 製品の制作・検証・納品定義 |
| `config/products/<slug>/license.json` | 利用権と再配布境界 |
| `config/genworks-layout.json` | Unity内の正規配置 |
| `config/genworks-handoff-policy.json` | 製品状態と引き継ぎ条件 |
| `config/release-policy.json` | 顧客向けリリースの証拠条件 |
| `config/toolchain-lock.json` | 対応ツールと固定バージョン |
| `Assets/GenWorks/OutfitCatalog.json` | 製品カタログ |
| `Assets/GenWorks/<slug>/ProductManifest.json` | 製品の現在状態とハッシュ |
| `Taskfile.yml` | 利用者向けコマンド入口 |

## 開発時の入口

実行入口は `Taskfile.yml` と `tools/manage.py` に集約されています。個別の内部モジュールを直接呼ぶ前に、対応するTaskコマンドがあるか確認してください。

AIエージェントへ作業を依頼する場合は、ルートの [`AGENTS.md`](AGENTS.md) が実行規約です。
