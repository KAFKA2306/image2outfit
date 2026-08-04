# image2outfit

Blenderで衣装を制作し、編集可能な`.blend`、FBX、宣言済みPrefab、5方向レンダリング、必須6ポーズの適合監査を、再現可能な製品ワークスペースとして管理するリポジトリです。

## このリポジトリの完了範囲

リポジトリ作業の完了、PRのmerge、作業ブランチ削除は、次の範囲で判定します。

- Blenderでの生成と最終保存
- 主シェルの連結性、境界ループ、意図しない穴の監査
- FBX生成
- Prefabファイルの宣言と配置
- 正面、背面、左右、斜めの5方向レンダリング
- `neutral`、`arms-up`、`arm-cross`、`crouch`、`sit`、`prone`の6ポーズレンダリング
- 衣装と素体の交差監査
- 画像の目視確認
- repository contract、unit test、Ruff lint、Ruff formatter、research contractの成功

次の工程は外部の下流工程であり、このリポジトリの完了条件には含めません。

- Unity import／save／reload
- Modular Avatar／NDMF検証
- VRChat Build & Test
- VRChat runtimeの人手確認

これらが未実施でも、Blender、トポロジー、5方向、6ポーズの範囲が合格していれば、リポジトリ作業は完了としてmergeし、作業ブランチを削除します。これらを「残件」「未完了ゲート」「merge blocker」として扱いません。

## ロジックの正本

同じ判断を複数のファイルへ持たせません。

| 判断 | 唯一の正本 |
| --- | --- |
| 製品ID、入力、正規出力 | `config/products/<slug>/job.json` |
| jobの型・許可フィールド | `config/job.schema.v2.json` |
| 衣装構築方式 | `config/products/<slug>/construction.json` |
| 構築方式の型 | `config/products/construction.schema.v1.json` |
| リポジトリ完了範囲と外部工程の境界 | `config/genworks-handoff-policy.json` |
| 必須ビュー、必須ポーズ、品質閾値 | `config/release-policy.json` |
| 現在の製品状態、失敗、再開地点 | `Assets/GenWorks/<slug>/ProductManifest.json` |
| job・construction・証拠の共通検証 | `tools/production_contract.py` |
| 正準ワークスペース保護 | `tools/workspace_transaction.py` |
| 利用者向け入口 | `Taskfile.yml` と `tools/manage.py` |

`construction.json`は方式を自動選択した結果ではありません。製品が採用した構築契約を宣言し、研究基準と必要証拠がその契約を満たすかを検証します。

## 正準処理

```text
jobとconstruction contractを完全検証
        ↓
正準ワークスペースをlast-good snapshotで保護
        ↓
Blender buildと最終保存
        ↓
主シェルの連結性・境界ループ・穴を監査
        ↓
FBXと宣言済みPrefabを生成
        ↓
5方向PNGと必須6ポーズPNGを生成
        ↓
BVH交差監査と画像目視監査
        ↓
既知のtechnical FAIL、fit audit FAIL、重大な見た目欠陥を拒否
        ↓
合格したcheckpointをmergeし、作業ブランチを削除
```

Unity、Modular Avatar／NDMF、VRChat関連の既存コードや設定は、外部運用者が別工程で利用するために残る場合があります。しかし、それらは上記の正準処理をブロックしません。

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
    Blender/
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
    Poses/
      neutral.png
      arms-up.png
      arm-cross.png
      crouch.png
      sit.png
      prone.png
  Evidence/Commercial/
  Tests/
  Documentation/
```

`Assets/GenWorks/<slug>/`が、Blend、FBX、Prefab、画像、監査状態を保持する唯一の正規ワークスペースです。

ローカル監査ログと候補コピーは`.image2outfit/products/<slug>/`以下に置かれ、Git管理されません。以前の`Artifacts/`、`Candidates/`、`Release/`は使用しません。

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

`task candidate`では、利用可能なBlender生成、FBX、画像、ポーズ、fit、トポロジー監査を実行します。in-scopeの工程が失敗した場合は`NO-GO`とし、last-good checkpointを保護します。

外部のUnity／VRChat工程は、利用者が明示的に別作業として実行する場合に限って扱います。このリポジトリの通常の完成判定には使用しません。

## 状態の読み方

- `WORKING`: 再開可能な製品状態
- `TECHNICAL_READY`: 下流工程を含む既存の技術状態名
- `HUMAN_REVIEW_PENDING`: 下流の人間レビュー待ちを表す既存状態名
- `REJECTED`: 問題と再開地点を保持した棄却候補
- `RELEASED`: 外部の下流release workflowまで完了した場合の状態名

製品の下流release状態と、リポジトリ作業の完了状態は別です。リポジトリ作業は、Blender、トポロジー、5方向、6ポーズ、交差監査、静的CIが合格し、mainへmergeされ、作業ブランチが削除された時点で完了します。

ファイルが存在するだけでは合格になりません。現在の実画像を開き、形状、シルエット、穴、分離、突起、食い込み、ポーズ変形を確認する必要があります。
