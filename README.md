https://kafka2306.github.io/image2outfit/

# image2outfit

SiroinoSotai_PC 向け衣装を Blender で制作し、編集可能ソース、FBX、Prefab 宣言、実レンダリング、研究記録を再現可能な製品ワークスペースとして管理するプロジェクトです。

GitHub Pages は `tools/review_console.py` が各製品の `ProductManifest.json` と現在の証拠から生成します。別の手書き製品台帳は使いません。

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

製品状態は `WORKING` / `COMPLETE` / `REJECTED` です。`COMPLETE` の判定は `config/genworks-handoff-policy.json` の `requiredCompletionGates` のみを基準にします。必須 gate の一覧は README に複製せず、この policy を直接確認してください。

画像の存在、ファイルサイズ、hash、CI 成功だけでは visual appearance review の PASS にはなりません。

Unity 2022.3.22f1 import/save/reload、Modular Avatar / NDMF bake、VRChat Build & Test / avatar dry-run は `task avatar:preflight` と Unity MCP の検証経路で確認します。VRChat実公開、VRChat runtime、人間による runtime visual review は `OUT_OF_SCOPE` とし、外部検証なしに動作確認済みとは表現しません。

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

複数のcanonical requestを直列で実行・再開する場合は次を使用します。成功済み製品は既存terminal checkpointを再利用し、失敗製品は既存checkpointから再開します。

```powershell
task batch:status
task batch:run
```

Docker coordinatorの境界と実行方法は [`ops/docker/README.md`](ops/docker/README.md) を参照してください。

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

## CI と GitHub Actions

PR・pushごとの自動テストと毎時のブランチ管理ワークフローは廃止しました。マージ前に担当エージェントがローカルで `task audit:all` と `task check:python` を実行し、結果をPRに記録してください。失敗や未実行の検証を成功扱いしてはいけません。

GitHub Actionsは必要時に手動実行する製品ビルド（hosted / self-hosted）、製品のrelease、全体品質検証（`Production contract quality`）として残しています。公開サイトの更新だけは、製品job、ProductManifest、preview、site、公開用ツールの変更時に自動実行します。その他のソース・設定変更後に再公開が必要な場合は、`Render all current products to Pages` を手動起動してください。

PRの自動マージ・ブランチ自動削除も廃止したため、マージと不要ブランチの整理は担当エージェントが実施し、結果を確認してください。製品のvisual / pose / 権利確認などのrelease gateは従来どおりです。

## Unity MCP と VRChat 公開

Unity MCP（upstream `v2.6.8`）は `Packages/manifest.json` の commit 固定で導入されます。Unity MCP の状態は製品の `COMPLETE` 条件や `requiredCompletionGates` には含めません。

VRChatアバターの連続公開にはAnatawa12 Continuous Avatar Uploader `0.3.12`を使用します。設定済みの9件は `Assets/UnityMCP_CAU/siroino-all-outfits.asset` にまとめ、各Prefabは個別の `Avatar Upload Setting` としてPC向けだけを有効化しています。アップロード開始はUnityの `Tools > Continuous Avatar Uploader` から行います。

生成済みアバターの開発者向け自動化入口は `task avatar:cloth`、`task avatar:plan`、`task avatar:preflight`、`task avatar:visual`、`task avatar:visual-diff`、`task avatar:ledger`、`task avatar:run` です。Blender 4.4.3 のnative Cloth証拠は各製品の `Evidence/Build/cloth-simulation.json` に保存し、Unityシーンは `Assets/Scenes/Avatar/` に個別配置します。`task avatar:visual-diff` は9着×11ビューのbefore/after比較と、各個別Unity衣装Sceneを1着ずつ開いたcloth後キャプチャ、差分画像、各製品の `Evidence/Build/cloth-visual-diff.json` を生成します。Unityのafterキャプチャは各Sceneの `AvatarPreviewStage/PreviewCamera` を camera view で使用し、カメラ位置・回転・正投影サイズとSceneのPrefab GUIDは `task avatar:preflight` で検査します。Workbenchの重ね表示はafter証拠に使用しません。差分は可視性のための非ブロッキング警告として扱います。ローカルの検査結果とアップロード台帳は `.image2outfit/avatar-workflow/` に保存し、認証情報は保存しません。NDMF bakeとVRChat監査はUnity MCP、CAU実公開はUnityログインを必要とする外部境界として扱います。

確認済みupstream:

- Unity MCP `v2.6.8`: <https://github.com/TunaSync-Studio/UnityMCP-VCC/tree/50597089589137c5186f5badbde1d72f5d335243>

## 実行結果と証拠

パイプラインの計画状態 `PLANNED`、実行状態 `EXECUTED` は製品状態 `COMPLETE` とは別です。工程は終了コード 0 だけで成功にはなりません。

各工程は `.image2outfit/` 以下へ result JSON と evidence を出力し、runner が stage、product ID、必須フィールド、ファイル存在、SHA-256 を検証します。詳細は [`ARCHITECTURE.md`](ARCHITECTURE.md) を参照してください。

## Documentation policy

- `README.md`: 利用者向け入口、正本への導線、最小操作
- `ARCHITECTURE.md`: 責務境界、パイプライン、状態・証拠 contract
- `AGENTS.md`: coding agent の作業・検証・Git 運用規約
- `Assets/GenWorks/<slug>/README.md`: 製品固有の記録。project-level document の代替にしない

数値、gate、pose、schema、path rule を Markdown だけで所有しないでください。実装や policy と食い違った場合は、正本を確認して Markdown 側を修正します。
