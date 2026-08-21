# image2outfit

SiroinoSotai_PC 向け衣装を Blender で制作し、編集可能ソース、FBX、Prefab 宣言、実レンダリング、研究記録を再現可能な製品ワークスペースとして管理するプロジェクトです。

## 正本

Markdown は入口と設計説明に限定します。変更され得る要件は、次の機械可読ファイルと実装を正本とします。

- PR merge 境界: `config/pr-merge-policy.json`
- 製品 completion 境界: `config/genworks-handoff-policy.json`
- 製品 release 境界: `config/release-policy.json`
- 製品入力・出力: `config/products/<slug>/job.json`
- 製品状態・gate・hash: `Assets/GenWorks/<slug>/ProductManifest.json`
- 品質仕様: `contracts/quality/quality-spec.json`
- パイプライン工程: `src/image2outfit/pipeline.py`
- 工程別要件: `config/pipeline-profiles/garment-reconstruction-v1.json`
- 操作用コマンド: `Taskfile.yml` / `tools/manage.py`

設計上の責務とデータフローは [`ARCHITECTURE.md`](ARCHITECTURE.md)、AI coding agent の作業規約は [`AGENTS.md`](AGENTS.md) を参照してください。

## 完了境界

製品状態は `WORKING` / `COMPLETE` / `REJECTED` です。`COMPLETE` の判定は `config/genworks-handoff-policy.json` の required completion gates のみを基準にします。

画像の存在、ファイルサイズ、hash、CI 成功だけでは visual appearance review の PASS にはなりません。completion gate と現在の `OUT_OF_SCOPE` 項目の一覧は policy を正本として確認します。

## PR merge と製品 release

PR merge と product release は別判定です。

```text
repository change
  → task merge:check
  → PR merge

product candidate
  → review / completion
  → task release PRODUCT=<slug>
  → customer release artifact
```

`task merge:check` は repository integration の contract を検証し、product release eligibility を評価しません。影響製品が `WORKING` / `REJECTED` のままでも、pipeline/build が有効な境界まで到達し、repository の merge 条件を満たしていれば PR を merge できます。

`task release` は別の product release validator を実行します。PR merge は release を実行せず、製品を `COMPLETE` に変更せず、visual/runtime/customer-quality PASS を暗黙に主張しません。

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

PR の repository-level merge contract は次で確認します。

```powershell
task merge:check
```

レビュー済み candidate を product release validator に通す場合だけ次を使用します。

```powershell
task release PRODUCT=<slug>
```

repository 全体の監査と Python 検証は次で実行します。

```powershell
task audit:all
task check:python
```

個別監査は `task --list` または `Taskfile.yml` を正本として確認してください。Markdown にコマンド一覧を複製しません。

## Blender / Unity MCP

OpenAI CodexからローカルのBlenderとUnityをMCP経由で操作する開発支援を用意しています。これは任意のauthoring adapterであり、製品の`COMPLETE`条件は変更しません。

Windowsでは次を使用します。

```powershell
task mcp:setup
task mcp:doctor
```

`task mcp:setup` は Codex 用に Blender MCP `1.8.0` と Unity MCP `10.1.2` のlocalhost接続を登録します。Blenderは `localhost:9876`、Unityは `http://127.0.0.1:8080/mcp` を使い、MCP状態そのものを製品証拠や `requiredCompletionGates` にはしません。

Unity側のpackage導入はローカルUnity projectを変更するためsetup scriptでは自動実行しません。確認済みpinを明示的に導入します。

```text
Window > Package Manager > + > Add package from git URL
https://github.com/CoplayDev/unity-mcp.git?path=/MCPForUnity#v10.1.2
```

Blender側には `View3D > Sidebar > Image2Outfit > OpenAI Assistant` の薄いprompt UIを用意します。bridgeはlocalhost限定とし、OpenAI/API/provider secrets、`.codex`、`.image2outfit/` のローカル状態をcommitしません。外部Blender連携は明示的に有効化した場合だけ使用します。

確認済みupstream:

- Blender MCP `1.8.0`: <https://github.com/ahujasid/blender-mcp/commit/3ab892510cc0e5435ba5e611c01fb1021fbde8de>
- Unity MCP `v10.1.2`: <https://github.com/CoplayDev/unity-mcp/releases/tag/v10.1.2>
- Codex MCP CLI: <https://github.com/openai/codex/blob/main/codex-rs/cli/src/mcp_cmd.rs>

## 実行結果と証拠

パイプラインの計画状態 `PLANNED`、実行状態 `EXECUTED` は製品状態 `COMPLETE` とは別です。工程は終了コード 0 だけで成功にはなりません。

各工程は `.image2outfit/` 以下へ result JSON と evidence を出力し、runner が stage、product ID、必須フィールド、ファイル存在、SHA-256 を検証します。詳細は [`ARCHITECTURE.md`](ARCHITECTURE.md) を参照してください。

## Documentation policy

- `README.md`: 利用者向け入口、正本への導線、最小操作
- `ARCHITECTURE.md`: 責務境界、パイプライン、状態・証拠 contract
- `AGENTS.md`: coding agent の作業・検証・Git 運用規約
- `Assets/GenWorks/<slug>/README.md`: 製品固有の記録。project-level document の代替にしない

数値、gate、pose、schema、path rule を Markdown だけで所有しないでください。実装や policy と食い違った場合は、正本を確認して Markdown 側を修正します。
