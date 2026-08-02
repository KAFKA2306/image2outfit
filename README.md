# image2outfit — VRChat衣装の再現可能な制作・納品パイプライン

image2outfitは、衣装仕様からBlender、FBX、Unity Prefab、プレビュー、レビュー証拠、リリースまでを再現可能に管理するUnityプロジェクトです。

メッシュやPrefabが存在するだけでは完成扱いにしません。構造、見た目、ポーズ貫通、VRChat実動作、人間レビューを別々のゲートとして記録し、同一候補のハッシュへ結び付けます。

## 境界

```text
config/
  job.schema.v2.json
  release-policy.json
  genworks-layout.json
  toolchain-lock.json
  blender-python-requirements.txt
  products/<product-id>/
    job.json
    license.json

Assets/GenWorks/
  Products/<product-id>/
  Shared/
  Legacy/Snapshots/

examples/review-approval.json
```

- `config/`直下には全製品共通の契約だけを置きます。
- 製品固有のjobとライセンス証拠は`config/products/<product-id>/`へ分離します。
- 現行製品アセットは`Assets/GenWorks/Products/<product-id>/`へ置きます。
- 共通Unity Editorコードは`Assets/GenWorks/Shared/Editor/`へ置きます。
- 過去候補は`Assets/GenWorks/Legacy/Snapshots/`に限定し、自動的に販売対象へ昇格させません。
- 非公開アバター、ローカルjob、人間レビュー証拠、キャッシュは`Assets/_Local/`、`Assets/_Vendor/`、`Assets/_Reference/`へ置き、Git管理しません。
- GitHub Actionsの実行状態、トリガーマーカー、生成途中の成果物を`main`へコミットしません。

## 基本操作

```powershell
task audit:repo
task audit:genworks
```

追跡済み製品jobまたはローカルjobから候補を作ります。

```powershell
task candidate JOB=config/products/<product-id>/job.json
task candidate JOB=Assets/_Local/Jobs/<job-id>/job.json
```

技術検証に成功しても判定は`REVIEW_REQUIRED`で、`Release/`は生成しません。レビュー証拠を同一candidate manifest hashへ結び付けた後、変更されていない候補を昇格します。

```powershell
task release JOB=<same-job-path>
```

保守操作は明示的に分離します。

```powershell
task maintenance:migrate:genworks
task maintenance:migrate:genworks:apply
task audit:snapshot SNAPSHOT=<snapshot-path> SOURCE=<local-source-path>
task package:snapshot SNAPSHOT=<snapshot-path>
```

## GitHub Actions

- `Build product with hosted Blender`は`config/products/<product-id>/job.json`を入力として、製品名をハードコードせずBlender生成とプレビューを実行します。
- 生成物はActions artifactへ保存し、workflow自身は`main`を変更しません。
- Unity、ローカルアバター、VRChat検証が必要な場合はself-hosted candidate/release workflowを使います。
- policy workflowはPython、JSON契約、ツールチェーン、GenWorks配置、リポジトリ衛生、unit testsを横断検証します。

## リリース条件

`GO / RELEASED`には、権利証拠、編集可能なBlend、構造エラーのないFBX、固定Unity環境でのImport・Prefab統合、5方向プレビュー、人間の見た目承認、必須ポーズでの重大貫通なし、VRChat Build & Test、全証拠とcandidate manifest hashの一致が必要です。

```text
SPECIFIED
  → MODELED
  → TECHNICAL_PASS
  → REVIEW_REQUIRED
  → VISUAL_PASS
  → POSE_PASS
  → RUNTIME_PASS
  → GO / RELEASED
```

証拠不足、権利不明、候補変更、重大な貫通、Import・runtime失敗は`NO-GO`です。

## 主な契約と証拠

- `config/job.schema.v2.json` — job必須フィールドの唯一の情報源
- `config/products/<product-id>/job.json` — 製品固有の生成・検証・納品定義
- `config/release-policy.json` — 共通リリース条件
- `config/genworks-layout.json` — Unity可視アセット配置
- `tools/release_gate.py` — candidate／review／release境界
- `tools/audit_repository_hygiene.py` — 残骸と汎用性違反の再発防止
- `Artifacts/<job-id>/audit.json` — 現在の判定
- `Candidates/<job-id>/candidate-manifest.json` — 候補の入力・出力・ハッシュ
- `Release/<job-id>/release-manifest.json` — GO後の変更不能な記録

詳細は[GenWorks配置仕様](docs/GENWORKS_LAYOUT.md)と[固定ツールチェーン](docs/TOOLCHAIN.md)を参照してください。

**README最終監査:** 2026-08-02
