# image2outfit

Blenderで衣装を制作し、FBX、Unity Prefab、Modular Avatar／NDMF、実レンダリング、VRChat確認までを一つの再現可能な製品ワークスペースで管理するUnityプロジェクトです。

## ロジックの正本

同じ判断を複数のファイルへ持たせません。

| 判断 | 唯一の正本 |
| --- | --- |
| 製品ID、入力、正規出力 | `config/products/<slug>/job.json` |
| jobの型・許可フィールド | `config/job.schema.v2.json` |
| 衣装構築方式 | `config/products/<slug>/construction.json` |
| 構築方式の型 | `config/products/construction.schema.v1.json` |
| 必須ビュー、必須ポーズ、品質閾値 | `config/release-policy.json` |
| 現在の製品状態、失敗、再開地点 | `Assets/GenWorks/<slug>/ProductManifest.json` |
| 顧客品質の最終判定 | `tools/customer_quality.py` |
| job・construction・証拠の共通検証 | `tools/production_contract.py` |
| 正準ワークスペース保護 | `tools/workspace_transaction.py` |
| runtime candidate／release保護 | `tools/runtime_transaction.py` |
| release証拠同梱とZIP化 | `tools/release_packager.py` |
| 利用者向け入口 | `Taskfile.yml` と `tools/manage.py` |

`construction.json` は方式を自動選択した結果ではありません。製品が採用した構築契約を宣言し、研究基準と必要証拠がその契約を満たすかを検証します。

## 一本化した処理

```text
jobとconstruction contractを完全検証
        ↓
正準ワークスペースをlast-good snapshotで保護
        ↓
Blender build → FBX → Unity import/save/reload → Modular Avatar/NDMF
        ↓
5方向PNGとrelease-policy所定の全ポーズPNGを検証
        ↓
既知のtechnical FAIL、fit audit FAILを拒否
        ↓
candidateへファイル、ポーズ、研究、構築契約のhashを固定
        ↓
GitHub review参照付きの人間証拠を検証
        ↓
customer_quality.pyで一度だけrelease判定
        ↓
候補、raw evidence、runtime screenshot、commercial evidence、hash manifestをZIP化
```

`tools/release_gate.py` は技術candidate生成専用です。直接releaseする経路は無効です。

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
    Poses/<release-policyの必須ポーズ>.png
  Evidence/Commercial/
  Demo/
  Editor/
  Tests/
  Documentation/
```

`Assets/GenWorks/<slug>/` が、Blend、FBX、Prefab、画像、監査状態を保持する唯一の正規ワークスペースです。

ローカルの監査ログ、候補コピー、配布物は `.image2outfit/products/<slug>/{reports,candidate,release}` に置かれ、Git管理されません。以前の `Artifacts/`、`Candidates/`、`Release/` は使用しません。

## 基本操作

```powershell
uv sync --locked
vpm resolve project .

task explain PRODUCT=<slug>
task candidate PRODUCT=<slug>
task release PRODUCT=<slug>

task audit:repo
task audit:runtime
task audit:genworks
task audit:tools
task audit:methods
task audit:research
task check:python
```

`task candidate` は技術候補を作るだけです。release-policyで要求された全ポーズ、fit、Unity、Modular Avatar／NDMFなどが失敗している場合は、正準ワークスペースをlast-goodへ戻して `NO-GO` にします。

`task release` は、変更されていないcandidateに対して次を要求します。

- 全required viewとrequired poseがcandidate manifestへhash固定されている
- commercial evidenceの入力ファイルがパスだけでなくSHA-256で固定されている
- 人間レビューにGitHub PR review URLがある
- visual、pose penetration、VRChat runtimeの全契約がPASS
- blocker、critical、majorの未解決欠陥がない

release ZIPにはcandidateだけでなく、生の人間レビューJSON、runtime screenshot、commercial evidence、検証結果とhashを含めます。

## 状態

- `WORKING`: 再開可能だが技術ゲートが残る
- `TECHNICAL_READY`: 自動技術ゲートを通過
- `HUMAN_REVIEW_PENDING`: 技術証拠が揃い、人間レビュー待ち
- `REJECTED`: 問題と再開地点を保持した却下候補
- `RELEASED`: 同一candidateが技術・人間・runtime契約を通過

ファイルが存在するだけではPASSになりません。実画像、ポーズ、fit、runtimeおよびそれらのhash bindingが必要です。
