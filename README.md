# image2outfit — VRChat衣装の再現可能な制作・納品パイプライン

image2outfitは、衣装仕様からBlender、FBX、Unity Prefab、実レンダリング、技術監査、人間レビュー、リリースまでを再現可能に管理するUnityプロジェクトです。

メッシュやPrefabが存在するだけでは完成扱いにしません。構造、見た目、ポーズ貫通、Unity／VRChat実動作、人間レビューを別々のゲートとして記録し、同一候補のハッシュへ結び付けます。作業途中や却下済みの状態も、別の開発者がゼロから作り直さず継続できるチェックポイントとしてGitに残します。

## 文書の情報源

リポジトリ共通の管理文書は次の2ファイルだけです。

- `README.md` — 利用者・開発者向けの構成、操作、環境、リリース条件
- `AGENTS.md` — エージェント向けの実行契約、品質ゲート、Git／Actions運用

`docs/` や `Assets/GenWorks/README.md`、`.github/AGENTS.md` のような重複する管理文書は置きません。製品固有の状態、導入方法、既知の問題は `Assets/GenWorks/<slug>/ProductManifest.json` と同じ製品ルートの `README.md` に記録します。履歴や一時的な作業説明を共通文書へ蓄積しません。

## 正規構成

```text
config/
  job.schema.v2.json
  release-policy.json
  genworks-layout.json
  genworks-handoff-policy.json
  toolchain-lock.json
  blender-python-requirements.txt
  products/<slug>/
    job.json
    license.json

Assets/GenWorks/
  <slug>/
    ProductManifest.json
    README.md
    Source/Blender/
    Models/
    Prefab/
    Materials/
    Textures/
    Previews/
    Documentation/
  Shared/
  Legacy/Snapshots/
  OutfitCatalog.json
```

- 現行・作業中・却下済みを含む、継続可能な製品は `Assets/GenWorks/<slug>/` に直接配置します。`Assets/GenWorks/Products/` やアバター名を挟む中間ディレクトリは使用しません。
- 製品Prefabは `Assets/GenWorks/<slug>/Prefab/*.prefab` の直下に置きます。
- `REJECTED` でも、FBX、Prefab、テクスチャ、監査証拠、再開地点があるものは製品ワークスペースです。`Legacy/Snapshots/` へ隔離しません。
- `Legacy/Snapshots/` は、正規製品として継続できない純粋な履歴証拠だけに限定します。
- HAOLANの既存チェックポイントは `Assets/GenWorks/haolan-bordeaux-knit-set/` と `Assets/GenWorks/haolan-cow-hood-knit-set/` に統合済みです。どちらも現在は `REJECTED` / `NO-GO` であり、製品READMEとManifestに不足ゲートを記録します。
- `config/products/<slug>/job.json`、製品ルート、Manifest、ライセンス証拠、納品対象のslugを一致させます。
- 共通Unity Editorコードは `Assets/GenWorks/Shared/Editor/` に置きます。`Assets/Editor/` は禁止です。
- 非公開・購入済みアバター、ローカルjob、秘密情報、キャッシュ、人間レビューのローカル記録は、jobで許可された `Assets/_Local/`、`Assets/_Vendor/`、`Assets/_Reference/` などのGit管理外ルートに置きます。
- Actions artifact、`Artifacts/`、`Candidates/`、`Release/` は輸送・監査・パッケージ用であり、再開可能な作業状態の正本ではありません。

## 製品ライフサイクル

状態名は `config/genworks-handoff-policy.json` を正とします。

```text
WORKING
  → TECHNICAL_READY
  → HUMAN_REVIEW_PENDING
  → RELEASED
```

- `WORKING` — Git追跡済みで再開可能だが、自動技術ゲートが未完了
- `TECHNICAL_READY` — Blender、FBX、Unity Import、Prefab保存・再読込、必要なUnity設定、自動統合検証が完了
- `HUMAN_REVIEW_PENDING` — 技術作業と証拠が揃い、最終の見た目・ポーズ・runtime確認待ち
- `REJECTED` — 問題、証拠、再開地点を残した却下状態。黙って削除したりゼロから再制作したりしない
- `RELEASED` — 変更されていない同一候補が、必要な自動ゲートと人間レビューをすべて通過

## 基本操作

```powershell
task candidate JOB=config/products/<slug>/job.json
task release JOB=config/products/<slug>/job.json

task audit:repo
task audit:genworks
task check:python
```

`task candidate` は技術候補を作りますが、顧客向けリリースを確定しません。見た目、ポーズ、VRChat runtimeの人間レビューを同一候補ハッシュへ結び付けた後、変更されていない候補だけを `task release` で昇格します。

スナップショットの監査・移行は明示的な保守操作です。

```powershell
task maintenance:migrate:genworks
task maintenance:migrate:genworks:apply
task audit:snapshot SNAPSHOT=<snapshot-path> SOURCE=<local-source-path>
task package:snapshot SNAPSHOT=<snapshot-path>
```

Unityでは `GenWorks > Product Catalog` から製品状態、Prefab、プレビュー、製品READMEを確認できます。

## 固定ツールチェーン

正確なバージョンと公式参照先は `config/toolchain-lock.json` を正とします。

| レイヤー | 固定バージョン | 公式情報 |
| --- | --- | --- |
| Blender | 4.4.3 | [Blender 4.4 corrective releases](https://developer.blender.org/docs/release_notes/4.4/corrective_releases/) |
| Blender Python | 3.11.11 | [Blender 4.4 library update](https://projects.blender.org/blender/blender/issues/128577) |
| Pillow | 12.3.0 | [Pillow 12.3.0 release notes](https://pillow.readthedocs.io/en/stable/releasenotes/12.3.0.html) |
| Unity | 2022.3.22f1 | [VRChat VPM CLI — Install Unity](https://vcc.docs.vrchat.com/vpm/cli/#install-unity) |
| VRChat SDK Base／Avatars | 3.10.4 | [VRChat SDK 3.10.4](https://creators.vrchat.com/releases/release-3-10-4/) |
| Modular Avatar | 1.17.1 | [Modular Avatar 1.17.1](https://github.com/bdunderscore/modular-avatar/releases/tag/1.17.1) |
| NDMF | 1.14.1 | [NDMF 1.14.1](https://github.com/bdunderscore/ndmf/releases/tag/1.14.1) |
| Avatar Optimizer | 1.9.16 | [Avatar Optimizer 1.9.16](https://github.com/anatawa12/AvatarOptimizer/releases/tag/v1.9.16) |

コミュニティVPMリポジトリを登録し、プロジェクトの固定Manifestを解決します。

```powershell
vpm add repo https://vpm.nadena.dev/vpm.json
vpm add repo https://vpm.anatawa12.com/vpm.json
vpm resolve project .
python tools/audit_toolchain.py
```

`Packages/vpm-manifest.json` がVPM依存を宣言し、Unityが `Packages/packages-lock.json` を管理します。lockファイルを手作業で書き換えません。Blender用Python依存は `config/blender-python-requirements.txt` から、Git管理外のローカル環境へ復元します。

## Unity／Modular Avatarの契約

`Assets/GenWorks/Shared/Editor/GeneratedOutfitPrefabConfigurator.cs` は、生成PrefabのImport時とEditor domain reload後に必要なModular Avatar設定をPrefabへ保存します。

- 生成衣装側Armatureは名前衝突を避ける `.1` 規約を使う
- `ModularAvatarMergeArmature` のtargetを対応するアバターArmatureへ設定する
- position lockは `BaseToMerge`、unique-bone name manglingは有効にする
- 衣装rootへ `ModularAvatarMeshSettings` を設定し、root bone、probe anchor、boundsを継承する
- 統合PrefabはNDMF処理で検証し、mapping不整合、missing script、renderer消失、無効なSkinnedMeshRendererを技術ゲートで拒否する

既存Prefabの修復はUnityメニュー `Tools > Image2Outfit > Configure Generated Modular Avatar Prefabs` から実行できます。Avatar Optimizerは導入済みですが、fit・pose・runtime検証の代替として自動注入しません。

## 実レンダリングとリリース条件

最低限、front、back、left、right、three-quarter、combined multiview、必須pose reviewを同一候補へ結び付けます。対象ゲートが必要とする場合はUnityまたはVRChat runtime screenshotも追加します。

画像ファイルの存在、解像度、CI成功だけでは合格にしません。実画像を目視し、body penetration、spike、silhouette破綻、scale不整合、detached parts、UV stretch、normal defect、material error、floating hardware、weight／pose failureがあれば改善を続けます。

`GO` または `RELEASED` には、権利証拠、編集可能なBlend、構造監査済みFBX、固定Unity環境でのImport・Prefab保存・再読込、Modular Avatar／NDMF設定、最新の実レンダリング、人間の見た目・ポーズ・runtime承認、全証拠と候補ハッシュの一致が必要です。証拠不足、権利不明、候補変更、重大な貫通、Import／runtime失敗は `NO-GO` です。

## GitHub Actions

- `.github/workflows/build-product-hosted.yml` — hosted Blenderで再現可能なjobの生成・レンダリング監査
- `.github/workflows/build-product-self-hosted.yml` — private target、Unity、Modular Avatar／NDMF、Prefabの技術検証
- `.github/workflows/e2e-self-hosted.yml` — self-hosted end-to-end検証
- `.github/workflows/release-self-hosted.yml` — hash-bound人間証拠を満たす未変更候補のリリース
- `.github/workflows/policy-tests.yml` — Python、JSON契約、ツールチェーン、GenWorks配置、repository hygiene、unit tests
- `.github/workflows/branch-hygiene.yml` — merge・close・supersede後に不要な非`main`ブランチを除去

生成物やログをActions artifactへ保存できますが、artifactだけを引き継ぎ状態にしません。build／validation workflowは最小権限で実行し、runtime state、trigger marker、telemetry、自己変更workflowを `main` へコミットしません。

## 正規の契約ファイル

- `config/job.schema.v2.json` — job必須フィールド
- `config/products/<slug>/job.json` — 製品固有の生成・検証・納品定義
- `config/products/<slug>/license.json` — 権利・再配布境界
- `config/genworks-layout.json` — Unity可視アセット配置
- `config/genworks-handoff-policy.json` — 状態・引き継ぎ・技術／人間ゲート
- `config/release-policy.json` — リリース条件
- `config/toolchain-lock.json` — 固定ツールチェーン
- `tools/release_gate.py` — candidate／release境界
- `tools/audit_repository_hygiene.py` — 残骸、重複管理、汎用性違反
- `tools/audit_genworks_layout.py` — 正規product root、Manifest、asset containment

**README最終監査:** 2026-08-02
